from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from agentgate.domain import (
    Case,
    CaseTurn,
    FrozenJsonObject,
    SpanStatus,
    Trace,
    TraceSpan,
)
from agentgate.evaluator.judge.prompt import (
    build_judge_request,
    render_bounded_evidence,
    select_material,
)


TRACE_ID = "a" * 32


def multi_turn_case() -> Case:
    return Case(
        id="case-1",
        name="Multi-turn",
        turns=(
            CaseTurn(id="turn-secret", input={"message": "first raw-secret"}),
            CaseTurn(id="turn-2", input={"message": "second"}),
        ),
    )


def execution_trace() -> Trace:
    return Trace(
        trace_id=TRACE_ID,
        run_id="run-secret",
        case_id="case-1",
        spans=(
            TraceSpan(
                trace_id=TRACE_ID,
                span_id="1" * 16,
                name="turn.execute",
                operation_type="turn",
                sequence=0,
                attributes={"agentgate.turn.id": "turn-secret"},
            ),
            TraceSpan(
                trace_id=TRACE_ID,
                span_id="2" * 16,
                parent_span_id="1" * 16,
                name="lookup_account",
                operation_type="tool",
                sequence=1,
                status=SpanStatus.OK,
                attributes={
                    "agentgate.run.id": "run-secret",
                    "account": "raw-secret",
                },
                events=(FrozenJsonObject({"message": "called"}),),
            ),
        ),
        final_output={"answer": "raw-secret result"},
        final_state={"status": "complete"},
    )


def redact(value: Any) -> Any:
    if isinstance(value, dict) or isinstance(value, FrozenJsonObject):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return value.replace("raw-secret", "[redacted]")
    return value


def request(selection: str = "full_trajectory"):
    return build_judge_request(
        model_id="judge-1",
        instruction="Judge raw-secret answers.",
        rubric={"accuracy": "Do not reveal raw-secret"},
        case=multi_turn_case(),
        trace=execution_trace(),
        input_selection=selection,
        pass_threshold=0.8,
        temperature=0,
        seed=7,
        max_output_tokens=256,
        timeout_seconds=30,
        max_input_chars=4_000,
        redact=redact,
    )


def test_select_material_has_explicit_evidence_levels() -> None:
    case = multi_turn_case()
    trace = execution_trace()

    minimal = select_material(case, trace, "final_output")
    with_tools = select_material(case, trace, "output_and_tools")
    full = select_material(case, trace, "full_trajectory")

    assert set(minimal) == {"turn_inputs", "final_output"}
    assert set(with_tools) == {"turn_inputs", "final_output", "tool_calls"}
    assert set(full) == {
        "turn_inputs",
        "final_output",
        "tool_calls",
        "trajectory",
        "final_state",
    }


def test_prompt_is_case_level_redacted_and_excludes_internal_ids() -> None:
    built = request()
    combined = f"{built.system_prompt}\n{built.user_prompt}"

    assert "first [redacted]" in combined
    assert "second" in combined
    assert "lookup_account" in combined
    assert "raw-secret" not in combined
    assert "run-secret" not in combined
    assert "turn-secret" not in combined
    assert TRACE_ID not in combined
    assert "1" * 16 not in combined
    assert "agentgate." not in combined


def test_prompt_rendering_is_deterministic_and_forces_json_response() -> None:
    first = request()
    second = request()

    assert first == second
    assert first.response_format == "json_object"
    assert '"verdict"' in (first.system_prompt or "")
    assert "0.8" in (first.system_prompt or "")


def test_bounded_evidence_returns_valid_json_with_digest() -> None:
    material = {"message": "x" * 1_000}
    complete = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    bounded = render_bounded_evidence(material, 180)
    payload = json.loads(bounded)

    assert len(bounded) <= 180
    assert payload["truncated"] is True
    assert payload["content_sha256"] == hashlib.sha256(complete.encode()).hexdigest()
    assert complete.startswith(payload["prefix"])


def test_prompt_rejects_invalid_configuration_and_identity() -> None:
    case = multi_turn_case()
    trace = execution_trace()
    with pytest.raises(ValueError, match="input selection"):
        select_material(case, trace, "unknown")
    with pytest.raises(ValueError, match="identities"):
        select_material(
            case,
            trace.model_copy(update={"case_id": "different"}),
            "final_output",
        )
    with pytest.raises(ValueError, match="at least"):
        render_bounded_evidence({"message": "x" * 100}, 10)
