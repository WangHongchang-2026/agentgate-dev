import pytest

from agentgate.domain import (
    CaseTurn,
    Equals,
    EvaluatorSpec,
    FailureStage,
    Outcome,
    OutputExpectation,
    ToolArgumentExpectation,
    ToolCallExpectation,
    Trace,
    TraceSpan,
)
from agentgate.evaluator.rule.tool_use import (
    ForbiddenToolEvaluator,
    RequiredToolEvaluator,
    ToolArgumentsEvaluator,
)


TRACE_ID = "0" * 32


def evaluator_spec(implementation_id: str) -> EvaluatorSpec:
    return EvaluatorSpec(
        id=implementation_id.replace("_", "-"),
        name=implementation_id,
        implementation_id=implementation_id,
        dimension="tool_use",
        metric=implementation_id,
    )


def tool_span(
    span_id: str,
    sequence: int,
    name: str,
    attributes: dict | None = None,
) -> TraceSpan:
    return TraceSpan(
        trace_id=TRACE_ID,
        span_id=span_id,
        name=name,
        operation_type="tool",
        sequence=sequence,
        attributes=attributes or {},
    )


def trace(*spans: TraceSpan) -> Trace:
    return Trace(
        trace_id=TRACE_ID,
        run_id="run",
        case_id="case",
        spans=spans,
    )


def resolve_unexpected(_evaluator_id: str):
    raise AssertionError("Rule tool evaluators must not resolve dependencies")


def test_metadata_and_applicability_are_separated_by_expectation_type() -> None:
    required = RequiredToolEvaluator()
    forbidden = ForbiddenToolEvaluator()
    arguments = ToolArgumentsEvaluator()
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            ToolCallExpectation(tool="lookup"),
            ToolCallExpectation(tool="delete", mode="forbidden"),
            ToolArgumentExpectation(
                tool="lookup",
                path="query",
                condition=Equals(expected="customer"),
            ),
        ),
    )
    unrelated = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(OutputExpectation(condition=Equals(expected={})),),
    )

    assert (required.implementation_id, forbidden.implementation_id) == (
        "required_tool",
        "forbidden_tool",
    )
    assert arguments.implementation_id == "tool_arguments"
    assert all(
        evaluator.kind.value == "rule" and evaluator.implementation_version == "1"
        for evaluator in (required, forbidden, arguments)
    )
    assert required.applies_to(evaluator_spec("required_tool"), turn)
    assert forbidden.applies_to(evaluator_spec("forbidden_tool"), turn)
    assert arguments.applies_to(evaluator_spec("tool_arguments"), turn)
    assert not any(
        evaluator.applies_to(evaluator_spec(evaluator.implementation_id), unrelated)
        for evaluator in (required, forbidden, arguments)
    )


def test_required_tools_preserve_expectation_and_trace_sequence_order() -> None:
    later = tool_span("2" * 16, 8, "lookup")
    earlier = tool_span("1" * 16, 2, "lookup")
    other = tool_span("3" * 16, 5, "audit")
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            ToolCallExpectation(id="lookup", name="Lookup required", tool="lookup"),
            ToolCallExpectation(id="missing", tool="notify"),
        ),
    )

    checks = RequiredToolEvaluator().evaluate(
        evaluator_spec("required_tool"),
        turn,
        trace(later, earlier, other),
        resolve_unexpected,
    ).checks

    assert tuple(check.expectation_id for check in checks) == ("lookup", "missing")
    assert checks[0].name == "Lookup required"
    assert checks[0].outcome == Outcome.PASS
    assert checks[0].actual == ("lookup", "audit", "lookup")
    assert checks[0].span_ids == (earlier.span_id, later.span_id)
    assert checks[0].methods[0].implementation_id == "contains_all"
    assert checks[1].name == "必需工具：notify"
    assert checks[1].outcome == Outcome.FAIL
    assert checks[1].failure is not None
    assert checks[1].failure.stage == FailureStage.TOOL_SELECTION
    assert checks[1].failure.at_trace_completion


def test_forbidden_tool_failure_uses_earliest_violating_span() -> None:
    later = tool_span("2" * 16, 9, "delete")
    earlier = tool_span("1" * 16, 3, "delete")
    allowed = tool_span("3" * 16, 5, "lookup")
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            ToolCallExpectation(id="delete", tool="delete", mode="forbidden"),
            ToolCallExpectation(id="publish", tool="publish", mode="forbidden"),
        ),
    )

    checks = ForbiddenToolEvaluator().evaluate(
        evaluator_spec("forbidden_tool"),
        turn,
        trace(later, allowed, earlier),
        resolve_unexpected,
    ).checks

    assert checks[0].outcome == Outcome.FAIL
    assert checks[0].actual == ("delete", "lookup", "delete")
    assert checks[0].span_ids == (earlier.span_id,)
    assert checks[0].failure is not None
    assert checks[0].failure.span_id == earlier.span_id
    assert checks[0].expected == {"absent_tool": "delete"}
    assert checks[0].methods[0].implementation_id == "contains_none"
    assert checks[1].outcome == Outcome.PASS
    assert checks[1].reason == "未调用 publish"


@pytest.mark.parametrize(
    ("occurrence", "expected_outcome", "expected_actual", "failure_span_id"),
    [
        ("first", Outcome.FAIL, "wrong", "1" * 16),
        ("last", Outcome.PASS, "right", None),
        ("any", Outcome.PASS, ("wrong", "right"), None),
        ("all", Outcome.FAIL, ("wrong", "right"), "1" * 16),
    ],
)
def test_tool_argument_occurrence_semantics(
    occurrence: str,
    expected_outcome: Outcome,
    expected_actual,
    failure_span_id: str | None,
) -> None:
    first = tool_span("1" * 16, 2, "lookup", {"query": "wrong"})
    last = tool_span("2" * 16, 8, "lookup", {"query": "right"})
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            ToolArgumentExpectation(
                id="query",
                tool="lookup",
                path="query",
                occurrence=occurrence,
                condition=Equals(expected="right"),
            ),
        ),
    )

    check = ToolArgumentsEvaluator().evaluate(
        evaluator_spec("tool_arguments"),
        turn,
        trace(last, first),
        resolve_unexpected,
    ).checks[0]

    assert check.outcome == expected_outcome
    assert check.actual == expected_actual
    assert check.span_ids == (
        (last.span_id,) if occurrence == "last" else
        (first.span_id,) if occurrence == "first" else
        (first.span_id, last.span_id)
    )
    assert check.methods[0].implementation_id == "equals"
    assert (check.failure.span_id if check.failure else None) == failure_span_id


def test_absent_tool_argument_is_not_applicable() -> None:
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            ToolArgumentExpectation(
                tool="lookup",
                path="query",
                condition=Equals(expected={"customer": "C-1"}),
            ),
        ),
    )

    check = ToolArgumentsEvaluator().evaluate(
        evaluator_spec("tool_arguments"), turn, trace(), resolve_unexpected
    ).checks[0]

    assert check.outcome == Outcome.NOT_APPLICABLE
    assert check.score is None
    assert check.actual is None
    assert check.actual_missing
    assert check.expected == {
        "kind": "equals",
        "expected": {"customer": "C-1"},
    }
    assert check.failure is None


def test_single_and_multiple_missing_arguments_respect_runtime_invariant() -> None:
    first = tool_span("1" * 16, 2, "lookup")
    last = tool_span("2" * 16, 8, "lookup", {"query": None})
    single_turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            ToolArgumentExpectation(
                tool="lookup",
                path="query",
                occurrence="first",
                condition=Equals(expected=None),
            ),
        ),
    )
    multiple_turn = single_turn.model_copy(
        update={
            "expectations": (
                single_turn.expectations[0].model_copy(update={"occurrence": "any"}),
            )
        }
    )
    evaluator = ToolArgumentsEvaluator()

    single = evaluator.evaluate(
        evaluator_spec("tool_arguments"),
        single_turn,
        trace(last, first),
        resolve_unexpected,
    ).checks[0]
    multiple = evaluator.evaluate(
        evaluator_spec("tool_arguments"),
        multiple_turn,
        trace(last, first),
        resolve_unexpected,
    ).checks[0]

    assert single.outcome == Outcome.FAIL
    assert single.actual is None
    assert single.actual_missing
    assert multiple.outcome == Outcome.PASS
    assert multiple.actual == (None, None)
    assert not multiple.actual_missing
