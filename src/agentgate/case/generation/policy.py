"""Deterministic safety and Target-capability checks for generated Cases."""

from __future__ import annotations

from jsonschema import Draft202012Validator

from agentgate.domain import (
    Case,
    OutputExpectation,
    TargetDescriptor,
    ToolArgumentExpectation,
    canonical_json,
)

from .models import CandidateIssue, TurnMode

_FORBIDDEN_TOPICS = (
    "越狱", "提示词注入", "攻击载荷", "恶意软件", "绕过安全", "jailbreak",
    "prompt injection", "malware", "exploit payload",
)
MAX_CANDIDATE_BYTES = 256 * 1024


def instruction_issues(instructions: str) -> tuple[CandidateIssue, ...]:
    lowered = instructions.casefold()
    if any(topic in lowered for topic in _FORBIDDEN_TOPICS):
        return (CandidateIssue(
            path="instructions",
            code="forbidden_topic",
            message="P1 不生成安全、越狱、攻击或对抗类用例",
        ),)
    return ()


def _local_ref(root: dict, ref: str) -> object | None:
    """Resolve a local JSON Pointer without performing network or file retrieval."""
    if ref == "#":
        return root
    if not ref.startswith("#/"):
        return None
    current: object = root
    for raw_part in ref[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _expanded_schema_nodes(
    schema: object,
    root: dict,
    seen: frozenset[int] = frozenset(),
) -> tuple[object, ...]:
    """Expand local refs and composition keywords for path discovery."""
    if not isinstance(schema, dict) or id(schema) in seen:
        return (schema,)
    next_seen = seen | {id(schema)}
    nodes: list[object] = [schema]
    ref = schema.get("$ref")
    if isinstance(ref, str):
        resolved = _local_ref(root, ref)
        if resolved is not None:
            nodes.extend(_expanded_schema_nodes(resolved, root, next_seen))
    for keyword in ("allOf", "anyOf", "oneOf"):
        branches = schema.get(keyword)
        if isinstance(branches, list):
            for branch in branches:
                nodes.extend(_expanded_schema_nodes(branch, root, next_seen))
    return tuple(nodes)


def _schema_has_path(schema: dict, path: str | None) -> bool:
    if path in (None, ""):
        return True
    if path.startswith("$.") or any(not part for part in path.split(".")):
        return False
    current: tuple[object, ...] = (schema,)
    for part in path.split("."):
        next_nodes: list[object] = []
        for candidate in current:
            for node in _expanded_schema_nodes(candidate, schema):
                if not isinstance(node, dict):
                    continue
                properties = node.get("properties")
                if isinstance(properties, dict) and part in properties:
                    next_nodes.append(properties[part])
                if part.isdigit():
                    index = int(part)
                    prefix_items = node.get("prefixItems")
                    if isinstance(prefix_items, list) and index < len(prefix_items):
                        next_nodes.append(prefix_items[index])
                    items = node.get("items")
                    if isinstance(items, (dict, bool)):
                        next_nodes.append(items)
        if not next_nodes:
            return False
        current = tuple(next_nodes)
    return True


def validate_case_for_target(
    case: Case,
    descriptor: TargetDescriptor,
    turn_mode: TurnMode | None = None,
    max_turns_per_case: int | None = 5,
) -> tuple[CandidateIssue, ...]:
    issues: list[CandidateIssue] = []
    if len(canonical_json(case).encode("utf-8")) > MAX_CANDIDATE_BYTES:
        issues.append(CandidateIssue(
            path="case",
            code="candidate_too_large",
            message="单个候选用例超过 256 KiB 大小限制",
        ))
    skill_names = {item.name for item in descriptor.skills}
    skill_tools = {item.name: set(item.tools) for item in descriptor.skills}
    tool_schemas = {item.name: item.arguments_schema.to_dict() for item in descriptor.tools}
    if turn_mode == TurnMode.SINGLE and len(case.turns) != 1:
        issues.append(CandidateIssue(
            path="turns", code="turn_count_mismatch", message="单轮模式必须恰好包含一轮",
        ))
    if turn_mode == TurnMode.MULTI and len(case.turns) < 2:
        issues.append(CandidateIssue(
            path="turns", code="turn_count_mismatch", message="多轮模式必须至少包含两轮",
        ))
    if max_turns_per_case is not None and len(case.turns) > max_turns_per_case:
        issues.append(CandidateIssue(
            path="turns", code="too_many_turns", message="用例轮数超过生成配置上限",
        ))
    input_validator = Draft202012Validator(descriptor.input_schema.to_dict())
    for turn_index, turn in enumerate(case.turns):
        base = f"turns[{turn_index}]"
        if not turn.input:
            issues.append(CandidateIssue(
                path=f"{base}.input",
                code="empty_turn_input",
                message="每轮输入必须是非空 JSON 对象",
            ))
        if turn.expected_skill is not None and turn.expected_skill not in skill_names:
            issues.append(CandidateIssue(
                path=f"{base}.expected_skill",
                code="unknown_skill",
                message=f"Target 未声明 Skill：{turn.expected_skill}",
            ))
        unknown_tools = sorted(
            (set(turn.required_tools) | set(turn.forbidden_tools)) - set(tool_schemas)
        )
        for tool in unknown_tools:
            issues.append(CandidateIssue(
                path=base, code="unknown_tool", message=f"Target 未声明工具：{tool}",
            ))
        if turn.expected_skill in skill_tools and skill_tools[turn.expected_skill]:
            mismatched = sorted(set(turn.required_tools) - skill_tools[turn.expected_skill])
            if mismatched:
                issues.append(CandidateIssue(
                    path=f"{base}.required_tools",
                    code="skill_tool_mismatch",
                    message=(
                        f"Skill {turn.expected_skill} 未声明这些工具："
                        f"{', '.join(mismatched)}"
                    ),
                ))
        overlap = sorted(set(turn.required_tools) & set(turn.forbidden_tools))
        if overlap:
            issues.append(CandidateIssue(
                path=base,
                code="tool_conflict",
                message=f"工具不能同时必需和禁止：{', '.join(overlap)}",
            ))
        for error in sorted(input_validator.iter_errors(turn.input.to_dict()), key=lambda e: list(e.path)):
            suffix = ".".join(str(item) for item in error.path)
            issues.append(CandidateIssue(
                path=f"{base}.input" + (f".{suffix}" if suffix else ""),
                code="input_schema_mismatch",
                message=error.message,
            ))
        for expectation_index, expectation in enumerate(turn.expectations):
            path = f"{base}.expectations[{expectation_index}]"
            if isinstance(expectation, ToolArgumentExpectation):
                schema = tool_schemas.get(expectation.tool)
                if schema is None:
                    issues.append(CandidateIssue(
                        path=f"{path}.tool",
                        code="unknown_tool",
                        message=f"Target 未声明工具：{expectation.tool}",
                    ))
                elif not _schema_has_path(schema, expectation.path):
                    issues.append(CandidateIssue(
                        path=f"{path}.path",
                        code="unknown_tool_path",
                        message=f"工具参数路径不存在：{expectation.path}",
                    ))
            elif isinstance(expectation, OutputExpectation) and not _schema_has_path(
                descriptor.output_schema.to_dict(), expectation.path
            ):
                issues.append(CandidateIssue(
                    path=f"{path}.path",
                    code="unknown_output_path",
                    message=f"输出路径不存在：{expectation.path}",
                ))
    return tuple(issues)
