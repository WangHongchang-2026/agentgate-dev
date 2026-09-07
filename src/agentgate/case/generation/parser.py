"""Strict parsing of model output with per-candidate failures."""

from __future__ import annotations

import json
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from agentgate.domain import Case, CaseTurn, Expectation

from .models import CandidateIssue, GeneratedCandidate, GeneratedCaseDraft

_expectation_adapter = TypeAdapter(Expectation)
MAX_GENERATED_RESPONSE_BYTES = 2 * 1024 * 1024


def _path(prefix: str, location: tuple[object, ...]) -> str:
    result = prefix
    for part in location:
        result += f"[{part}]" if isinstance(part, int) else f".{part}"
    return result


def case_from_generated(draft: GeneratedCaseDraft) -> Case:
    turns = []
    for turn in draft.turns:
        expectations = tuple(
            _expectation_adapter.validate_python(item.model_dump(mode="json"))
            for item in turn.expectations
        )
        turns.append(CaseTurn(
            input=turn.input,
            expected_skill=(turn.expected_skill.strip() or None) if turn.expected_skill else None,
            expectations=expectations,
            required_tools=turn.required_tools,
            forbidden_tools=turn.forbidden_tools,
            policy_rules=turn.policy_rules,
            notes=turn.notes,
        ))
    return Case(
        name=draft.name,
        turns=tuple(turns),
        initial_state=draft.initial_state,
        category=draft.category,
        difficulty=draft.difficulty,
        tags=draft.tags,
        notes=draft.notes,
    )


def parse_generated_response(
    content: str,
) -> tuple[tuple[GeneratedCandidate, ...], int, tuple[CandidateIssue, ...]]:
    if len(content.encode("utf-8")) > MAX_GENERATED_RESPONSE_BYTES:
        return (), 0, (CandidateIssue(
            path="response",
            code="response_too_large",
            message="模型响应超过 2 MiB 大小限制",
        ),)
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError) as exc:
        return (), 0, (CandidateIssue(
            path="response",
            code="invalid_json",
            message=f"模型响应不是有效 JSON：{exc}",
        ),)
    if not isinstance(payload, dict) or set(payload) != {"cases"}:
        return (), 0, (CandidateIssue(
            path="response",
            code="invalid_envelope",
            message="模型响应必须是只包含 cases 的对象",
        ),)
    raw_cases = payload["cases"]
    if not isinstance(raw_cases, list):
        return (), 0, (CandidateIssue(
            path="response.cases",
            code="invalid_type",
            message="cases 必须是数组",
        ),)
    candidates = []
    for index, raw_case in enumerate(raw_cases[:100]):
        candidate_id = str(uuid4())
        try:
            parsed = GeneratedCaseDraft.model_validate(raw_case)
            item = case_from_generated(parsed)
            candidates.append(GeneratedCandidate(candidate_id=candidate_id, case=item))
        except ValidationError as exc:
            issues = tuple(CandidateIssue(
                path=_path(f"cases[{index}]", tuple(error["loc"])),
                code="invalid_candidate",
                message=error["msg"],
            ) for error in exc.errors(include_url=False))
            candidates.append(GeneratedCandidate(candidate_id=candidate_id, issues=issues))
    batch_issues = ()
    if len(raw_cases) > 100:
        batch_issues = (CandidateIssue(
            path="response.cases",
            code="too_many_candidates",
            message="模型返回超过 100 条，超出部分已忽略",
        ),)
    return tuple(candidates), len(raw_cases), batch_issues
