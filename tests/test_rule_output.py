from agentgate.domain import (
    CaseTurn,
    Equals,
    EvaluatorSpec,
    FailureStage,
    MatchesJsonSchema,
    MatchesPattern,
    MustBeMissing,
    Outcome,
    OutputExpectation,
    StateExpectation,
    Trace,
)
from agentgate.evaluator.rule.output import FinalOutputEvaluator


def evaluator_spec() -> EvaluatorSpec:
    return EvaluatorSpec(
        id="final-output",
        name="Final output",
        implementation_id="final_output",
        dimension="answer",
        metric="final_output_match",
    )


def trace(final_output: dict) -> Trace:
    return Trace(
        trace_id="0" * 32,
        run_id="run",
        case_id="case",
        spans=(),
        final_output=final_output,
    )


def resolve_unexpected(_evaluator_id: str):
    raise AssertionError("FinalOutputEvaluator must not resolve dependencies")


def test_metadata_and_applicability_are_exact() -> None:
    evaluator = FinalOutputEvaluator()
    output_turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(OutputExpectation(condition=Equals(expected={})),),
    )
    state_turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            StateExpectation(path="status", condition=Equals(expected="done")),
        ),
    )

    assert evaluator.kind.value == "rule"
    assert evaluator.implementation_id == "final_output"
    assert evaluator.implementation_version == "1"
    assert evaluator.applies_to(evaluator_spec(), output_turn)
    assert not evaluator.applies_to(evaluator_spec(), state_turn)


def test_evaluate_preserves_output_expectation_order_and_details() -> None:
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            OutputExpectation(
                id="status",
                name="Decision status",
                path="decision.status",
                condition=Equals(expected="approved"),
            ),
            StateExpectation(path="status", condition=Equals(expected="ignored")),
            OutputExpectation(
                id="message",
                path="message",
                condition=MatchesPattern(pattern=r"approved"),
            ),
        ),
    )

    evaluation = FinalOutputEvaluator().evaluate(
        evaluator_spec(),
        turn,
        trace({"decision": {"status": "approved"}, "message": "not approved"}),
        resolve_unexpected,
    )

    assert tuple(check.expectation_id for check in evaluation.checks) == (
        "status",
        "message",
    )
    first, second = evaluation.checks
    assert first.name == "Decision status"
    assert first.outcome == Outcome.PASS
    assert first.score == 1.0
    assert first.reason == "最终输出符合预期"
    assert first.expected == {"kind": "equals", "expected": "approved"}
    assert first.actual == "approved"
    assert first.methods[0].implementation_id == "equals"
    assert first.methods[0].implementation_version == "1"
    assert first.span_ids == ()
    assert first.failure is None
    assert second.name == "最终输出：message"


def test_root_output_and_json_null_remain_observable_values() -> None:
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            OutputExpectation(
                id="root",
                condition=Equals(expected={"answer": None}),
            ),
            OutputExpectation(
                id="null",
                path="answer",
                condition=Equals(expected=None),
            ),
        ),
    )

    checks = FinalOutputEvaluator().evaluate(
        evaluator_spec(), turn, trace({"answer": None}), resolve_unexpected
    ).checks

    assert checks[0].name == "最终输出：完整输出"
    assert checks[0].actual == {"answer": None}
    assert checks[1].actual is None
    assert all(check.outcome == Outcome.PASS for check in checks)
    assert all(not check.actual_missing for check in checks)


def test_missing_output_path_has_distinct_actual_and_terminal_failure() -> None:
    expectation = OutputExpectation(
        id="missing",
        path="decision.reason",
        condition=MustBeMissing(),
    )
    present = trace({"decision": {"reason": None}})
    absent = trace({"decision": {}})
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(expectation,),
    )
    evaluator = FinalOutputEvaluator()

    failed = evaluator.evaluate(
        evaluator_spec(), turn, present, resolve_unexpected
    ).checks[0]
    passed = evaluator.evaluate(
        evaluator_spec(), turn, absent, resolve_unexpected
    ).checks[0]

    assert failed.outcome == Outcome.FAIL
    assert failed.score == 0.0
    assert failed.actual is None
    assert not failed.actual_missing
    assert failed.failure is not None
    assert failed.failure.stage == FailureStage.FINAL_OUTPUT
    assert failed.failure.at_trace_completion
    assert failed.failure.span_id is None
    assert passed.outcome == Outcome.PASS
    assert passed.actual is None
    assert passed.actual_missing
    assert passed.failure is None


def test_json_schema_condition_evaluates_complete_output_with_provenance() -> None:
    condition = MatchesJsonSchema(
        json_schema={
            "type": "object",
            "required": ["answer"],
            "properties": {"answer": {"type": "string"}},
        }
    )
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            OutputExpectation(
                path=None,
                condition=condition,
            ),
        ),
    )

    evaluator = FinalOutputEvaluator()
    passed = evaluator.evaluate(
        evaluator_spec(), turn, trace({"answer": "ok"}), resolve_unexpected
    ).checks[0]
    failed = evaluator.evaluate(
        evaluator_spec(), turn, trace({"answer": 7}), resolve_unexpected
    ).checks[0]

    assert passed.outcome == Outcome.PASS
    assert passed.score == 1.0
    assert passed.reason == "最终输出符合预期"
    assert passed.actual == {"answer": "ok"}
    assert passed.methods[0].implementation_id == "matches_json_schema"
    assert passed.methods[0].implementation_version == "1"
    assert failed.outcome == Outcome.FAIL
    assert failed.score == 0.0
    assert failed.reason == "JSON Schema violation at $.answer (type)"
    assert failed.actual == {"answer": 7}
    assert failed.methods[0].implementation_id == "matches_json_schema"
    assert failed.failure is not None
    assert failed.failure.stage == FailureStage.FINAL_OUTPUT
    assert failed.failure.at_trace_completion
