import pytest

from agentgate.domain import (
    Equals,
    OutputExpectation,
    PolicyExpectation,
    StateExpectation,
    ToolArgumentExpectation,
    Trace,
    TraceSpan,
)
from agentgate.evaluator.rule.observations import (
    MISSING,
    Observation,
    observe_expectation,
    value_at_path,
)


TRACE_ID = "0" * 32


def span(
    span_id: str,
    sequence: int,
    operation_type: str,
    *,
    name: str = "operation",
    attributes: dict | None = None,
) -> TraceSpan:
    return TraceSpan(
        trace_id=TRACE_ID,
        span_id=span_id,
        name=name,
        operation_type=operation_type,
        sequence=sequence,
        attributes=attributes or {},
    )


def trace(*spans: TraceSpan) -> Trace:
    return Trace(
        trace_id=TRACE_ID,
        run_id="run",
        case_id="case",
        spans=spans,
        final_output={"answer": None},
        final_state={"application": {"status": "review"}},
    )


def test_observation_requires_aligned_values_and_valid_span_ids() -> None:
    with pytest.raises(ValueError, match="equal lengths"):
        Observation(values=("value",), span_ids=())
    with pytest.raises(ValueError, match="lowercase OTel Span IDs"):
        Observation(values=("value",), span_ids=("invalid",))

    assert Observation(values=(), span_ids=()).values == ()


def test_value_at_path_distinguishes_root_null_and_missing() -> None:
    data = {"answer": None, "nested": {"value": "found"}}

    assert value_at_path(data, None) is data
    assert value_at_path(data, "answer") is None
    assert value_at_path(data, "nested.value") == "found"
    assert value_at_path(data, "nested.other") is MISSING
    assert value_at_path(data, "answer.value") is MISSING
    with pytest.raises(ValueError, match="nonblank dotted segments"):
        value_at_path(data, "nested..value")


def test_state_observation_uses_latest_state_span_by_sequence() -> None:
    later = span("2" * 16, 9, "state")
    earlier = span("1" * 16, 2, "state")
    expectation = StateExpectation(
        path="application.status",
        condition=Equals(expected="review"),
    )

    observation = observe_expectation(trace(later, earlier), expectation)

    assert observation.values == ("review",)
    assert observation.span_ids == (later.span_id,)


def test_output_observation_supports_root_and_json_null() -> None:
    root = observe_expectation(
        trace(),
        OutputExpectation(path=None, condition=Equals(expected={"answer": None})),
    )
    null = observe_expectation(
        trace(),
        OutputExpectation(path="answer", condition=Equals(expected=None)),
    )

    assert root.values == ({"answer": None},)
    assert null.values == (None,)
    assert root.span_ids == null.span_ids == (None,)


@pytest.mark.parametrize(
    ("occurrence", "expected_values", "expected_span_ids"),
    [
        ("first", ("first",), ("1" * 16,)),
        ("last", ("last",), ("2" * 16,)),
        ("any", ("first", "last"), ("1" * 16, "2" * 16)),
        ("all", ("first", "last"), ("1" * 16, "2" * 16)),
    ],
)
def test_tool_observation_orders_and_selects_occurrences(
    occurrence: str,
    expected_values: tuple[str, ...],
    expected_span_ids: tuple[str, ...],
) -> None:
    later = span(
        "2" * 16,
        8,
        "tool",
        name="lookup",
        attributes={"request": {"value": "last"}},
    )
    earlier = span(
        "1" * 16,
        3,
        "tool",
        name="lookup",
        attributes={"request": {"value": "first"}},
    )
    expectation = ToolArgumentExpectation(
        tool="lookup",
        path="request.value",
        occurrence=occurrence,
        condition=Equals(expected="first"),
    )

    observation = observe_expectation(trace(later, earlier), expectation)

    assert observation.values == expected_values
    assert observation.span_ids == expected_span_ids


def test_tool_observation_distinguishes_no_call_from_missing_argument() -> None:
    expectation = ToolArgumentExpectation(
        tool="lookup",
        path="request.value",
        condition=Equals(expected="value"),
    )

    no_call = observe_expectation(trace(), expectation)
    missing = observe_expectation(
        trace(span("1" * 16, 1, "tool", name="lookup")),
        expectation,
    )

    assert no_call == Observation(values=(), span_ids=())
    assert missing.values == (MISSING,)
    assert missing.span_ids == ("1" * 16,)


def test_rejects_unsupported_expectation_types() -> None:
    with pytest.raises(TypeError, match="PolicyExpectation"):
        observe_expectation(
            trace(),
            PolicyExpectation(policy_id="policy"),  # type: ignore[arg-type]
        )
