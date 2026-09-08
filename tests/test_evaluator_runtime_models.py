import pytest
from pydantic import ValidationError

from agentgate.domain import FailureStage, Outcome
from agentgate.evaluator.models import CheckDraft, Evaluation, FailureCandidate


def failure_candidate(**overrides: object) -> FailureCandidate:
    values: dict[str, object] = {
        "stage": FailureStage.FINAL_OUTPUT,
        "at_trace_completion": True,
    }
    values.update(overrides)
    return FailureCandidate(**values)


def check_draft(**overrides: object) -> CheckDraft:
    values: dict[str, object] = {
        "name": "Output check",
        "outcome": Outcome.PASS,
        "score": 1.0,
        "reason": "Output passed",
    }
    values.update(overrides)
    return CheckDraft(**values)


def test_failure_candidate_requires_exactly_one_valid_location() -> None:
    with pytest.raises(ValidationError, match="requires span_id or trace-completion"):
        failure_candidate(at_trace_completion=False)
    with pytest.raises(ValidationError, match="cannot use both location forms"):
        failure_candidate(span_id="1" * 16)
    with pytest.raises(ValidationError, match="lowercase OTel Span ID"):
        failure_candidate(span_id="invalid", at_trace_completion=False)

    value = failure_candidate(span_id="1" * 16, at_trace_completion=False)
    assert value.span_id == "1" * 16


def test_check_draft_freezes_json_values_and_is_immutable() -> None:
    value = check_draft(
        expected={"items": ["first"]},
        actual={"items": ["first"]},
    )

    assert value.expected["items"] == ("first",)
    assert value.model_dump(mode="json")["actual"] == {"items": ["first"]}
    with pytest.raises(ValidationError, match="frozen"):
        value.score = 0.5


@pytest.mark.parametrize("field_name", ["name", "reason", "turn_id", "expectation_id"])
def test_check_draft_rejects_blank_text(field_name: str) -> None:
    with pytest.raises(ValidationError, match=field_name):
        check_draft(**{field_name: " "})


def test_check_draft_enforces_outcome_score_and_failure_consistency() -> None:
    with pytest.raises(ValidationError, match="execution errors belong"):
        check_draft(outcome=Outcome.ERROR, score=None)
    with pytest.raises(ValidationError, match="cannot have a score"):
        check_draft(outcome=Outcome.NOT_APPLICABLE, score=0.0)
    with pytest.raises(ValidationError, match="requires a score"):
        check_draft(score=None)
    with pytest.raises(ValidationError, match="requires a failure candidate"):
        check_draft(outcome=Outcome.FAIL, score=0.0)
    with pytest.raises(ValidationError, match="only failed"):
        check_draft(failure=failure_candidate())

    failed = check_draft(
        outcome=Outcome.FAIL,
        score=0.0,
        failure=failure_candidate(),
    )
    assert failed.failure.at_trace_completion


def test_check_draft_validates_span_ids() -> None:
    with pytest.raises(ValidationError, match="lowercase OTel Span IDs"):
        check_draft(span_ids=("invalid",))
    with pytest.raises(ValidationError, match="must be unique"):
        check_draft(span_ids=("1" * 16, "1" * 16))

    value = check_draft(span_ids=("1" * 16, "2" * 16))
    assert value.span_ids == ("1" * 16, "2" * 16)


def test_check_draft_distinguishes_missing_from_json_null() -> None:
    with pytest.raises(ValidationError, match="missing CheckDraft actual value"):
        check_draft(actual="present", actual_missing=True)

    missing = check_draft(actual=None, actual_missing=True)
    json_null = check_draft(actual=None, actual_missing=False)
    assert missing.actual is None and missing.actual_missing
    assert json_null.actual is None and not json_null.actual_missing


def test_evaluation_allows_no_applicable_checks() -> None:
    assert Evaluation(checks=()).checks == ()
