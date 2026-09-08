from __future__ import annotations

from dataclasses import FrozenInstanceError
import json

import pytest

from agentgate.evaluator.judge.contract import (
    MAX_CRITERION_CHARS,
    MAX_REASON_CHARS,
    MAX_RESPONSE_CHARS,
    MAX_VIOLATIONS,
    JudgeContractError,
    parse_verdict,
    response_instructions,
)
from agentgate.evaluator.judge.model_protocol import (
    JudgeModelClient,
    JudgeModelInvalidResponse,
    JudgeModelTimeout,
    JudgeRequest,
    JudgeResponse,
    request_fingerprint,
)


def test_judge_request_is_secret_free_immutable_and_stably_fingerprinted() -> None:
    request = JudgeRequest(
        model_id="judge-1",
        system_prompt="Apply the rubric.",
        user_prompt="Evaluate this output.",
        seed=7,
        max_output_tokens=256,
    )

    assert request_fingerprint(request) == request_fingerprint(request)
    assert request_fingerprint(
        JudgeRequest(model_id="judge-1", user_prompt="Other output.")
    ) != request_fingerprint(request)
    assert "credential" not in request.__dataclass_fields__
    with pytest.raises(FrozenInstanceError):
        request.model_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"model_id": " "}, "model_id"),
        ({"user_prompt": ""}, "user_prompt"),
        ({"temperature": 2.1}, "temperature"),
        ({"max_output_tokens": 0}, "max_output_tokens"),
        ({"response_format": "xml"}, "response_format"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
    ],
)
def test_judge_request_rejects_invalid_fields(changes, message) -> None:
    values = {"model_id": "judge-1", "user_prompt": "Evaluate."}
    with pytest.raises(ValueError, match=message):
        JudgeRequest(**{**values, **changes})


def test_request_fingerprint_excludes_only_the_timeout() -> None:
    baseline = JudgeRequest(model_id="judge-1", user_prompt="Evaluate.")
    longer_wait = JudgeRequest(
        model_id="judge-1",
        user_prompt="Evaluate.",
        timeout_seconds=120,
    )
    changed_generation = JudgeRequest(
        model_id="judge-1",
        user_prompt="Evaluate.",
        temperature=0.5,
    )

    assert request_fingerprint(longer_wait) == request_fingerprint(baseline)
    assert request_fingerprint(changed_generation) != request_fingerprint(baseline)


def test_judge_response_validates_accounting_and_reports_truncation() -> None:
    response = JudgeResponse(
        text='{"verdict":"pass"}',
        resolved_model_id="judge-1-2026",
        input_tokens=10,
        output_tokens=4,
        latency_ms=12.5,
        finish_reason="length",
        attempt_count=2,
    )

    assert response.truncated is True
    with pytest.raises(ValueError, match="input_tokens"):
        JudgeResponse(text="{}", resolved_model_id="judge-1", input_tokens=-1)
    with pytest.raises(ValueError, match="attempt_count"):
        JudgeResponse(text="{}", resolved_model_id="judge-1", attempt_count=0)


def test_judge_client_protocol_and_error_classification() -> None:
    class Client:
        provider_id = "fake"

        def complete(self, request: JudgeRequest) -> JudgeResponse:
            return JudgeResponse(text="{}", resolved_model_id=request.model_id)

    assert isinstance(Client(), JudgeModelClient)
    assert isinstance(JudgeModelTimeout("slow"), TimeoutError)
    assert isinstance(JudgeModelInvalidResponse("bad envelope"), ValueError)


def verdict_json(**changes) -> str:
    payload = {
        "verdict": "pass",
        "score": 1.0,
        "confidence": 0.9,
        "reason": "The answer satisfies the rubric.",
        "violations": [],
    }
    payload.update(changes)
    return json.dumps(payload)


def test_parse_verdict_returns_immutable_normalized_content() -> None:
    parsed = parse_verdict(
        verdict_json(
            verdict="fail",
            score=0.25,
            violations=[{"criterion": "accuracy", "detail": "Amount is wrong."}],
        ),
        pass_threshold=0.8,
    )

    assert parsed.verdict == "fail"
    assert parsed.score == 0.25
    assert parsed.violations[0].criterion == "accuracy"
    with pytest.raises(FrozenInstanceError):
        parsed.score = 1.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "text",
    [
        "not JSON",
        "[]",
        verdict_json(verdict="unknown"),
        verdict_json(score=True),
        verdict_json(confidence=2),
        verdict_json(reason=" "),
        verdict_json(violations={}),
    ],
)
def test_parse_verdict_rejects_malformed_content(text) -> None:
    with pytest.raises(JudgeContractError):
        parse_verdict(text, pass_threshold=0.8)


def test_parse_verdict_requires_exact_fields() -> None:
    missing = json.loads(verdict_json())
    missing.pop("confidence")
    unknown = json.loads(verdict_json())
    unknown["commentary"] = "extra"

    with pytest.raises(JudgeContractError, match="missing fields: confidence"):
        parse_verdict(json.dumps(missing), 0.8)
    with pytest.raises(JudgeContractError, match="unknown fields: commentary"):
        parse_verdict(json.dumps(unknown), 0.8)


def test_parse_verdict_rejects_score_and_verdict_contradictions() -> None:
    with pytest.raises(JudgeContractError, match="pass verdict"):
        parse_verdict(verdict_json(verdict="pass", score=0.79), 0.8)
    with pytest.raises(JudgeContractError, match="fail verdict"):
        parse_verdict(verdict_json(verdict="fail", score=0.8), 0.8)

    assert parse_verdict(
        verdict_json(verdict="review", score=0.95), 0.8
    ).verdict == "review"


def test_parse_verdict_enforces_all_output_bounds() -> None:
    with pytest.raises(JudgeContractError, match="response exceeds"):
        parse_verdict("x" * (MAX_RESPONSE_CHARS + 1), 0.8)
    with pytest.raises(JudgeContractError, match="reason.*exceeds"):
        parse_verdict(verdict_json(reason="x" * (MAX_REASON_CHARS + 1)), 0.8)
    with pytest.raises(JudgeContractError, match="more than"):
        parse_verdict(
            verdict_json(
                violations=[{"criterion": "c", "detail": "d"}]
                * (MAX_VIOLATIONS + 1)
            ),
            0.8,
        )
    with pytest.raises(JudgeContractError, match="criterion.*exceeds"):
        parse_verdict(
            verdict_json(
                violations=[
                    {"criterion": "x" * (MAX_CRITERION_CHARS + 1), "detail": "d"}
                ]
            ),
            0.8,
        )


def test_response_instructions_include_schema_and_threshold() -> None:
    instructions = response_instructions(0.85)

    assert '"verdict"' in instructions
    assert "pass|fail|review" in instructions
    assert "0.85" in instructions
    with pytest.raises(ValueError, match="pass_threshold"):
        response_instructions(1.1)
