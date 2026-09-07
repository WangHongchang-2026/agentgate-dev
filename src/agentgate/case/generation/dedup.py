"""Deterministic functional fingerprinting for generated Cases."""

from __future__ import annotations

from agentgate.domain import Case, canonical_json, content_sha256


def _expectation_payload(item) -> dict:
    payload = item.model_dump(mode="json", exclude={"id", "name"})
    condition = payload.get("condition")
    if isinstance(condition, dict) and condition.get("kind") == "one_of":
        condition["allowed"] = sorted(condition["allowed"], key=canonical_json)
    return payload


def case_functional_payload(case: Case) -> dict:
    turns = []
    for turn in case.turns:
        expectations = sorted(
            (_expectation_payload(item) for item in turn.expectations),
            key=canonical_json,
        )
        turns.append({
            "input": turn.input,
            "expected_skill": turn.expected_skill,
            "expectations": expectations,
            "required_tools": sorted(set(turn.required_tools)),
            "forbidden_tools": sorted(set(turn.forbidden_tools)),
            "policy_rules": sorted(set(turn.policy_rules)),
        })
    return {
        "initial_state": case.initial_state,
        "category": case.category.value,
        "difficulty": case.difficulty.value,
        "tags": sorted(set(case.tags)),
        "turns": turns,
    }


def case_functional_fingerprint(case: Case) -> str:
    return content_sha256(case_functional_payload(case))
