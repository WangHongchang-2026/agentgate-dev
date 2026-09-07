"""Parse a small provider-facing blueprint and compile it into domain Cases."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from jsonschema import Draft202012Validator

from agentgate.domain import (
    Case,
    CaseTurn,
    Equals,
    MatchesJsonSchema,
    MatchesPattern,
    OutputExpectation,
    TargetDescriptor,
    ToolArgumentExpectation,
)

from .models import (
    CandidateIssue,
    GeneratedCandidate,
    GeneratedCaseBlueprint,
)
from .parser import MAX_GENERATED_RESPONSE_BYTES, _path
from .policy import _schema_has_path


def _leaf_values(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            yield from _leaf_values(child, path)
    else:
        yield prefix, value


def _resolve_identifier(value: str, allowed: tuple[str, ...]) -> str:
    stripped = value.strip()
    if stripped in allowed:
        return stripped
    compact = re.sub(r"\s+", "", stripped)
    matches = [item for item in allowed if re.sub(r"\s+", "", item) == compact]
    return matches[0] if len(matches) == 1 else stripped


def _literal_contains_pattern(text: str) -> str:
    """Compile provider text into an explicit, injection-safe regex."""
    return f"(?s:.*{re.escape(text)}.*)"


def _normalize_blueprint_identifiers(raw_case: Any, descriptor: TargetDescriptor) -> Any:
    if not isinstance(raw_case, dict) or not isinstance(raw_case.get("turns"), list):
        return raw_case
    normalized = deepcopy(raw_case)
    skills = tuple(item.name for item in descriptor.skills)
    tools = tuple(item.name for item in descriptor.tools)
    for turn in normalized["turns"]:
        if not isinstance(turn, dict):
            continue
        if isinstance(turn.get("expected_skill"), str):
            turn["expected_skill"] = _resolve_identifier(turn["expected_skill"], skills)
        if isinstance(turn.get("forbidden_tools"), list):
            turn["forbidden_tools"] = [
                _resolve_identifier(item, tools) if isinstance(item, str) else item
                for item in turn["forbidden_tools"]
            ]
        if isinstance(turn.get("required_tool_calls"), list):
            for call in turn["required_tool_calls"]:
                if isinstance(call, dict) and isinstance(call.get("tool"), str):
                    call["tool"] = _resolve_identifier(call["tool"], tools)
    return normalized


def _blueprint_target_issues(
    blueprint: GeneratedCaseBlueprint,
    descriptor: TargetDescriptor,
) -> tuple[CandidateIssue, ...]:
    issues = []
    has_actionable_signal = any(
        turn.expected_skill is not None
        or turn.required_tool_calls
        or turn.forbidden_tools
        or turn.output_contains
        for turn in blueprint.turns
    )
    if not has_actionable_signal:
        issues.append(CandidateIssue(
            path="turns",
            code="insufficient_evaluation_signal",
            message="候选至少需要 Skill、工具调用/禁调或稳定输出关键词之一",
        ))
    if re.fullmatch(r"(?:case|测试)[_\- ]*\d+", blueprint.name.strip(), re.IGNORECASE):
        issues.append(CandidateIssue(
            path="name",
            code="placeholder_case_name",
            message="用例名称必须描述具体业务场景，不能使用序号占位名称",
        ))
    skills = {item.name for item in descriptor.skills}
    skill_tools = {item.name: set(item.tools) for item in descriptor.skills}
    tools = {item.name: item.arguments_schema.to_dict() for item in descriptor.tools}
    for turn_index, turn in enumerate(blueprint.turns):
        base = f"turns[{turn_index}]"
        if turn.expected_skill is not None and turn.expected_skill not in skills:
            issues.append(CandidateIssue(
                path=f"{base}.expected_skill", code="unknown_skill",
                message=f"Target 未声明 Skill：{turn.expected_skill}",
            ))
        required = {call.tool for call in turn.required_tool_calls}
        if turn.expected_skill in skill_tools and skill_tools[turn.expected_skill]:
            mismatched = sorted(required - skill_tools[turn.expected_skill])
            if mismatched:
                issues.append(CandidateIssue(
                    path=f"{base}.required_tool_calls",
                    code="skill_tool_mismatch",
                    message=(
                        f"Skill {turn.expected_skill} 未声明这些工具："
                        f"{', '.join(mismatched)}"
                    ),
                ))
        overlap = sorted(required & set(turn.forbidden_tools))
        if overlap:
            issues.append(CandidateIssue(
                path=base, code="tool_conflict",
                message=f"工具不能同时必需和禁止：{', '.join(overlap)}",
            ))
        for call_index, call in enumerate(turn.required_tool_calls):
            schema = tools.get(call.tool)
            path = f"{base}.required_tool_calls[{call_index}]"
            if schema is None:
                issues.append(CandidateIssue(
                    path=f"{path}.tool", code="unknown_tool",
                    message=f"Target 未声明工具：{call.tool}",
                ))
                continue
            validator = Draft202012Validator(schema)
            for error in sorted(validator.iter_errors(call.arguments), key=lambda e: list(e.path)):
                suffix = ".".join(str(item) for item in error.path)
                issues.append(CandidateIssue(
                    path=f"{path}.arguments" + (f".{suffix}" if suffix else ""),
                    code="tool_arguments_schema_mismatch", message=error.message,
                ))
        for tool in sorted(set(turn.forbidden_tools) - set(tools)):
            issues.append(CandidateIssue(
                path=f"{base}.forbidden_tools", code="unknown_tool",
                message=f"Target 未声明工具：{tool}",
            ))
    return tuple(issues)


def case_from_blueprint(
    blueprint: GeneratedCaseBlueprint,
    descriptor: TargetDescriptor,
) -> Case:
    output_schema = descriptor.output_schema.to_dict()
    message_path = "message" if _schema_has_path(output_schema, "message") else None
    turns = []
    for turn in blueprint.turns:
        expected_skill = turn.expected_skill
        if expected_skill is None:
            # A forbidden tool says what must not happen; it does not prove which
            # Skill should own the user's intent. Only positive tool evidence can
            # safely infer a unique Skill.
            referenced_tools = {call.tool for call in turn.required_tool_calls}
            skill_candidates = [
                {skill.name for skill in descriptor.skills if tool in skill.tools}
                for tool in referenced_tools
            ]
            if skill_candidates:
                common_skills = set.intersection(*skill_candidates)
                if len(common_skills) == 1:
                    expected_skill = next(iter(common_skills))
        required_tools = tuple(dict.fromkeys(call.tool for call in turn.required_tool_calls))
        expectations = []
        for call in turn.required_tool_calls:
            for path, expected in _leaf_values(call.arguments):
                if path:
                    expectations.append(ToolArgumentExpectation(
                        tool=call.tool,
                        path=path,
                        occurrence=call.occurrence,
                        condition=Equals(expected=expected),
                        name=f"{call.tool}.{path}",
                    ))
        for text in dict.fromkeys(item.strip() for item in turn.output_contains if item.strip()):
            expectations.append(OutputExpectation(
                path=message_path,
                condition=MatchesPattern(pattern=_literal_contains_pattern(text)),
                name=f"输出包含：{text}",
            ))
        if output_schema:
            expectations.append(OutputExpectation(
                path=None,
                condition=MatchesJsonSchema(json_schema=output_schema),
                name="输出符合 Target Schema",
            ))
        turns.append(CaseTurn(
            input=turn.input,
            expected_skill=expected_skill,
            expectations=tuple(expectations),
            required_tools=required_tools,
            forbidden_tools=tuple(dict.fromkeys(turn.forbidden_tools)),
            notes=turn.notes,
        ))
    return Case(
        name=blueprint.name,
        turns=tuple(turns),
        category=blueprint.category,
        difficulty=blueprint.difficulty,
        tags=blueprint.tags,
        notes=blueprint.notes,
    )


def parse_blueprint_response(
    content: str,
    descriptor: TargetDescriptor,
) -> tuple[tuple[GeneratedCandidate, ...], int, tuple[CandidateIssue, ...]]:
    if len(content.encode("utf-8")) > MAX_GENERATED_RESPONSE_BYTES:
        return (), 0, (CandidateIssue(
            path="response", code="response_too_large", message="模型响应超过 2 MiB 大小限制",
        ),)
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        return (), 0, (CandidateIssue(
            path="response", code="invalid_json", message=f"模型响应不是有效 JSON：{exc}",
        ),)
    if not isinstance(payload, dict) or set(payload) != {"cases"}:
        return (), 0, (CandidateIssue(
            path="response", code="invalid_envelope", message="模型响应必须是只包含 cases 的对象",
        ),)
    raw_cases = payload["cases"]
    if not isinstance(raw_cases, list):
        return (), 0, (CandidateIssue(
            path="response.cases", code="invalid_type", message="cases 必须是数组",
        ),)
    candidates = []
    for index, raw_case in enumerate(raw_cases[:100]):
        candidate_id = str(uuid4())
        try:
            normalized = _normalize_blueprint_identifiers(raw_case, descriptor)
            blueprint = GeneratedCaseBlueprint.model_validate(normalized)
            candidates.append(GeneratedCandidate(
                candidate_id=candidate_id,
                slot_index=blueprint.slot_index,
                case=case_from_blueprint(blueprint, descriptor),
                issues=_blueprint_target_issues(blueprint, descriptor),
            ))
        except ValidationError as exc:
            candidates.append(GeneratedCandidate(
                candidate_id=candidate_id,
                slot_index=(
                    raw_case.get("slot_index")
                    if isinstance(raw_case, dict)
                    and isinstance(raw_case.get("slot_index"), int)
                    and not isinstance(raw_case.get("slot_index"), bool)
                    and 0 <= raw_case["slot_index"] <= 19
                    else None
                ),
                issues=tuple(CandidateIssue(
                    path=_path(f"cases[{index}]", tuple(error["loc"])),
                    code="invalid_blueprint",
                    message=error["msg"],
                ) for error in exc.errors(include_url=False)),
            ))
    issues = ()
    if len(raw_cases) > 100:
        issues = (CandidateIssue(
            path="response.cases", code="too_many_candidates", message="模型返回超过 100 条候选",
        ),)
    return tuple(candidates), len(raw_cases), issues
