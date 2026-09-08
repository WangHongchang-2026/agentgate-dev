from agentgate.domain import (
    CaseTurn,
    Equals,
    EvaluatorSpec,
    FailureStage,
    MatchesJsonSchema,
    MustBeMissing,
    Outcome,
    OutputExpectation,
    StateExpectation,
    Trace,
    TraceSpan,
)
from agentgate.evaluator.rule.state import FinalStateEvaluator


TRACE_ID = "0" * 32


def evaluator_spec() -> EvaluatorSpec:
    return EvaluatorSpec(
        id="final-state",
        name="Final state",
        implementation_id="final_state",
        dimension="state",
        metric="final_state_match",
    )


def state_span(span_id: str, sequence: int) -> TraceSpan:
    return TraceSpan(
        trace_id=TRACE_ID,
        span_id=span_id,
        name="state",
        operation_type="state",
        sequence=sequence,
    )


def trace(final_state: dict, *spans: TraceSpan) -> Trace:
    return Trace(
        trace_id=TRACE_ID,
        run_id="run",
        case_id="case",
        spans=spans,
        final_state=final_state,
    )


def resolve_unexpected(_evaluator_id: str):
    raise AssertionError("FinalStateEvaluator must not resolve dependencies")


def test_metadata_and_applicability_are_exact() -> None:
    evaluator = FinalStateEvaluator()
    state_turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            StateExpectation(path="status", condition=Equals(expected="done")),
        ),
    )
    output_turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(OutputExpectation(condition=Equals(expected={})),),
    )

    assert evaluator.kind.value == "rule"
    assert evaluator.implementation_id == "final_state"
    assert evaluator.implementation_version == "1"
    assert evaluator.applies_to(evaluator_spec(), state_turn)
    assert not evaluator.applies_to(evaluator_spec(), output_turn)


def test_evaluate_preserves_order_details_and_latest_span_evidence() -> None:
    later = state_span("2" * 16, 9)
    earlier = state_span("1" * 16, 2)
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            StateExpectation(
                id="decision",
                name="Decision state",
                path="decision",
                condition=Equals(expected={"status": "approved"}),
            ),
            OutputExpectation(condition=Equals(expected={})),
            StateExpectation(
                id="status",
                path="decision.status",
                condition=Equals(expected="approved"),
            ),
        ),
    )

    checks = FinalStateEvaluator().evaluate(
        evaluator_spec(),
        turn,
        trace({"decision": {"status": "approved"}}, later, earlier),
        resolve_unexpected,
    ).checks

    assert tuple(check.expectation_id for check in checks) == ("decision", "status")
    first, second = checks
    assert first.name == "Decision state"
    assert first.outcome == Outcome.PASS
    assert first.score == 1.0
    assert first.reason == "decision 符合预期"
    assert first.expected == {
        "kind": "equals",
        "expected": {"status": "approved"},
    }
    assert first.actual == {"status": "approved"}
    assert first.methods[0].implementation_id == "equals"
    assert first.methods[0].implementation_version == "1"
    assert first.span_ids == (later.span_id,)
    assert first.failure is None
    assert second.name == "最终状态：decision.status"
    assert second.span_ids == (later.span_id,)


def test_json_null_and_missing_state_are_distinct() -> None:
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            StateExpectation(
                id="null",
                path="decision.reason",
                condition=Equals(expected=None),
            ),
            StateExpectation(
                id="missing",
                path="decision.owner",
                condition=MustBeMissing(),
            ),
        ),
    )

    checks = FinalStateEvaluator().evaluate(
        evaluator_spec(),
        turn,
        trace({"decision": {"reason": None}}),
        resolve_unexpected,
    ).checks

    assert checks[0].actual is None
    assert not checks[0].actual_missing
    assert checks[1].actual is None
    assert checks[1].actual_missing
    assert all(check.outcome == Outcome.PASS for check in checks)


def test_failure_uses_state_span_or_trace_completion() -> None:
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            StateExpectation(path="status", condition=Equals(expected="approved")),
        ),
    )
    span = state_span("1" * 16, 4)
    evaluator = FinalStateEvaluator()

    located = evaluator.evaluate(
        evaluator_spec(), turn, trace({"status": "denied"}, span), resolve_unexpected
    ).checks[0]
    terminal = evaluator.evaluate(
        evaluator_spec(), turn, trace({"status": "denied"}), resolve_unexpected
    ).checks[0]

    assert located.outcome == Outcome.FAIL
    assert located.score == 0.0
    assert located.failure is not None
    assert located.failure.stage == FailureStage.FINAL_STATE
    assert located.failure.span_id == span.span_id
    assert not located.failure.at_trace_completion
    assert terminal.failure is not None
    assert terminal.failure.span_id is None
    assert terminal.failure.at_trace_completion
    assert terminal.span_ids == ()


def test_json_schema_condition_evaluates_state_path_and_missing_value() -> None:
    condition = MatchesJsonSchema(
        json_schema={
            "type": "object",
            "required": ["status"],
            "properties": {
                "status": {"enum": ["approved", "pending_review"]},
            },
        }
    )
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            StateExpectation(
                path="decision",
                condition=condition,
            ),
        ),
    )

    evaluator = FinalStateEvaluator()
    passed = evaluator.evaluate(
        evaluator_spec(),
        turn,
        trace({"decision": {"status": "approved"}}, state_span("1" * 16, 1)),
        resolve_unexpected,
    ).checks[0]
    failed = evaluator.evaluate(
        evaluator_spec(),
        turn,
        trace({"decision": {"status": "denied"}}, state_span("2" * 16, 2)),
        resolve_unexpected,
    ).checks[0]
    missing = evaluator.evaluate(
        evaluator_spec(), turn, trace({}), resolve_unexpected
    ).checks[0]

    assert passed.outcome == Outcome.PASS
    assert passed.reason == "decision 符合预期"
    assert passed.methods[0].implementation_id == "matches_json_schema"
    assert passed.methods[0].implementation_version == "1"
    assert failed.outcome == Outcome.FAIL
    assert failed.reason == "JSON Schema violation at $.status (enum)"
    assert failed.span_ids == ("2" * 16,)
    assert failed.failure is not None
    assert failed.failure.stage == FailureStage.FINAL_STATE
    assert failed.failure.span_id == "2" * 16
    assert missing.outcome == Outcome.FAIL
    assert missing.reason == "JSON value is missing"
    assert missing.actual_missing
    assert missing.methods[0].implementation_id == "matches_json_schema"
    assert missing.failure is not None
    assert missing.failure.stage == FailureStage.FINAL_STATE
    assert missing.failure.at_trace_completion
