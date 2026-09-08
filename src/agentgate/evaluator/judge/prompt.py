"""Deterministically render protected Case evidence into Judge requests."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Any, Literal, TypeAlias

from agentgate.domain import Case, Trace, canonical_json

from .contract import response_instructions
from .model_protocol import JudgeRequest


JudgeInputSelection: TypeAlias = Literal[
    "final_output",
    "output_and_tools",
    "full_trajectory",
]
RedactValue: TypeAlias = Callable[[Any], Any]
_INPUT_SELECTIONS = frozenset(
    {"final_output", "output_and_tools", "full_trajectory"}
)


def _behavior_attributes(attributes: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in attributes.items()
        if not key.startswith("agentgate.")
    }


def _tool_calls(trace: Trace) -> list[dict[str, Any]]:
    return [
        {
            "arguments": _behavior_attributes(span.attributes),
            "name": span.name,
            "status": span.status,
        }
        for span in sorted(trace.spans, key=lambda item: item.sequence)
        if span.operation_type == "tool"
    ]


def _trajectory(trace: Trace) -> list[dict[str, Any]]:
    return [
        {
            "attributes": _behavior_attributes(span.attributes),
            "events": span.events,
            "name": span.name,
            "operation_type": span.operation_type,
            "sequence": span.sequence,
            "status": span.status,
        }
        for span in sorted(trace.spans, key=lambda item: item.sequence)
    ]


def select_material(
    case: Case,
    trace: Trace,
    input_selection: JudgeInputSelection,
) -> dict[str, Any]:
    """Select case-level behavior while excluding correlation bookkeeping."""

    if input_selection not in _INPUT_SELECTIONS:
        raise ValueError(f"unknown Judge input selection: {input_selection}")
    if trace.case_id != case.id:
        raise ValueError("Trace and Case identities do not match")

    material: dict[str, Any] = {
        "turn_inputs": [
            {"index": index, "input": turn.input}
            for index, turn in enumerate(case.turns)
        ],
        "final_output": trace.final_output,
    }
    if input_selection in {"output_and_tools", "full_trajectory"}:
        material["tool_calls"] = _tool_calls(trace)
    if input_selection == "full_trajectory":
        material["trajectory"] = _trajectory(trace)
        material["final_state"] = trace.final_state
    return material


def render_bounded_evidence(material: Any, max_input_chars: int) -> str:
    """Render canonical evidence or a valid JSON envelope with a bounded prefix."""

    if isinstance(max_input_chars, bool) or not isinstance(max_input_chars, int):
        raise ValueError("max_input_chars must be a positive integer")
    if max_input_chars < 1:
        raise ValueError("max_input_chars must be a positive integer")

    rendered = canonical_json(material)
    if len(rendered) <= max_input_chars:
        return rendered

    digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
    envelope = {
        "content_sha256": digest,
        "prefix": "",
        "truncated": True,
    }
    minimum = canonical_json(envelope)
    if len(minimum) > max_input_chars:
        raise ValueError(
            f"max_input_chars must be at least {len(minimum)} for truncated evidence"
        )

    prefix_length = max_input_chars - len(minimum)
    while prefix_length >= 0:
        envelope["prefix"] = rendered[:prefix_length]
        bounded = canonical_json(envelope)
        if len(bounded) <= max_input_chars:
            return bounded
        prefix_length -= len(bounded) - max_input_chars
    raise AssertionError("bounded evidence size calculation failed")


def build_judge_request(
    *,
    model_id: str,
    instruction: str,
    rubric: Mapping[str, Any],
    case: Case,
    trace: Trace,
    input_selection: JudgeInputSelection,
    pass_threshold: float,
    temperature: float,
    seed: int | None,
    max_output_tokens: int,
    timeout_seconds: float,
    max_input_chars: int,
    redact: RedactValue,
) -> JudgeRequest:
    """Build one secret-free, case-level request for a Judge provider."""

    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("Judge instruction must not be blank")
    if not isinstance(rubric, Mapping) or not rubric:
        raise ValueError("Judge rubric must not be empty")
    if not callable(redact):
        raise TypeError("Judge prompt requires a redaction callable")

    protected_instruction = redact(instruction.strip())
    protected_rubric = redact(rubric)
    protected_material = redact(select_material(case, trace, input_selection))
    if not isinstance(protected_instruction, str):
        raise TypeError("Judge redactor must return text for instruction input")

    system_prompt = "\n\n".join(
        (
            protected_instruction,
            f"Rubric:\n{canonical_json(protected_rubric)}",
            response_instructions(pass_threshold),
        )
    )
    user_prompt = (
        "Evaluate this Agent execution against the rubric.\n"
        f"Evidence selection: {input_selection}\n\n"
        f"Evidence:\n{render_bounded_evidence(protected_material, max_input_chars)}"
    )
    return JudgeRequest(
        model_id=model_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        seed=seed,
        max_output_tokens=max_output_tokens,
        response_format="json_object",
        timeout_seconds=timeout_seconds,
    )


__all__ = [
    "JudgeInputSelection",
    "RedactValue",
    "build_judge_request",
    "render_bounded_evidence",
    "select_material",
]
