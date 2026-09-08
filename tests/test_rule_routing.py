from agentgate.domain import (
    CaseTurn,
    Equals,
    EvaluatorSpec,
    FailureStage,
    MatchesJsonSchema,
    MustBeMissing,
    Outcome,
    OutputExpectation,
    SkillRouteExpectation,
    Trace,
    TraceSpan,
)
from agentgate.evaluator.rule.routing import SkillRoutingEvaluator


TRACE_ID = "0" * 32


def evaluator_spec() -> EvaluatorSpec:
    return EvaluatorSpec(
        id="skill-routing",
        name="Skill routing",
        implementation_id="skill_routing",
        dimension="routing",
        metric="skill_routing_accuracy",
    )


def routing_span(
    span_id: str,
    sequence: int,
    attributes: dict | None = None,
) -> TraceSpan:
    return TraceSpan(
        trace_id=TRACE_ID,
        span_id=span_id,
        name="route",
        operation_type="routing",
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
    raise AssertionError("SkillRoutingEvaluator must not resolve dependencies")


def test_metadata_and_applicability_are_exact() -> None:
    evaluator = SkillRoutingEvaluator()
    routing_turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            SkillRouteExpectation(condition=Equals(expected="loan")),
        ),
    )
    output_turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(OutputExpectation(condition=Equals(expected={})),),
    )

    assert evaluator.kind.value == "rule"
    assert evaluator.implementation_id == "skill_routing"
    assert evaluator.implementation_version == "1"
    assert evaluator.applies_to(evaluator_spec(), routing_turn)
    assert not evaluator.applies_to(evaluator_spec(), output_turn)


def test_evaluate_preserves_expectation_order_and_earliest_routing_span() -> None:
    later = routing_span("2" * 16, 8, {"selected_skill": "other"})
    earlier = routing_span("1" * 16, 2, {"selected_skill": "loan"})
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            SkillRouteExpectation(
                id="loan",
                name="Loan route",
                condition=Equals(expected="loan"),
            ),
            OutputExpectation(condition=Equals(expected={})),
            SkillRouteExpectation(
                id="other",
                condition=Equals(expected="other"),
            ),
        ),
    )

    checks = SkillRoutingEvaluator().evaluate(
        evaluator_spec(), turn, trace(later, earlier), resolve_unexpected
    ).checks

    assert tuple(check.expectation_id for check in checks) == ("loan", "other")
    first, second = checks
    assert first.name == "Loan route"
    assert first.outcome == Outcome.PASS
    assert first.score == 1.0
    assert first.reason == "路由正确"
    assert first.expected == {"kind": "equals", "expected": "loan"}
    assert first.actual == "loan"
    assert first.methods[0].implementation_id == "equals"
    assert first.methods[0].implementation_version == "1"
    assert first.span_ids == (earlier.span_id,)
    assert first.failure is None
    assert second.name == "技能路由"
    assert second.outcome == Outcome.FAIL
    assert second.failure is not None
    assert second.failure.span_id == earlier.span_id


def test_absent_routing_span_fails_at_trace_completion() -> None:
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            SkillRouteExpectation(condition=Equals(expected={"skill": "loan"})),
        ),
    )

    check = SkillRoutingEvaluator().evaluate(
        evaluator_spec(), turn, trace(), resolve_unexpected
    ).checks[0]

    assert check.outcome == Outcome.FAIL
    assert check.score == 0.0
    assert check.reason == "未产生路由决策"
    assert check.actual is None
    assert check.actual_missing
    assert check.span_ids == ()
    assert check.failure is not None
    assert check.failure.stage == FailureStage.ROUTING
    assert check.failure.at_trace_completion
    assert check.expected == {
        "kind": "equals",
        "expected": {"skill": "loan"},
    }


def test_missing_selected_skill_is_distinct_from_json_null() -> None:
    missing_turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            SkillRouteExpectation(condition=MustBeMissing()),
        ),
    )
    null_turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            SkillRouteExpectation(condition=Equals(expected=None)),
        ),
    )
    evaluator = SkillRoutingEvaluator()

    missing = evaluator.evaluate(
        evaluator_spec(),
        missing_turn,
        trace(routing_span("1" * 16, 1)),
        resolve_unexpected,
    ).checks[0]
    null = evaluator.evaluate(
        evaluator_spec(),
        null_turn,
        trace(routing_span("1" * 16, 1, {"selected_skill": None})),
        resolve_unexpected,
    ).checks[0]

    assert missing.outcome == Outcome.PASS
    assert missing.actual is None
    assert missing.actual_missing
    assert null.outcome == Outcome.PASS
    assert null.actual is None
    assert not null.actual_missing
    assert missing.span_ids == null.span_ids == ("1" * 16,)


def test_json_schema_condition_handles_present_and_absent_routing() -> None:
    condition = MatchesJsonSchema(
        json_schema={"type": "string", "pattern": "^loan_"}
    )
    turn = CaseTurn(
        id="turn",
        input={"message": "start"},
        expectations=(
            SkillRouteExpectation(condition=condition),
        ),
    )

    evaluator = SkillRoutingEvaluator()
    passed = evaluator.evaluate(
        evaluator_spec(),
        turn,
        trace(routing_span("1" * 16, 1, {"selected_skill": "loan_approval"})),
        resolve_unexpected,
    ).checks[0]
    failed = evaluator.evaluate(
        evaluator_spec(),
        turn,
        trace(routing_span("2" * 16, 1, {"selected_skill": 7})),
        resolve_unexpected,
    ).checks[0]
    absent = evaluator.evaluate(
        evaluator_spec(), turn, trace(), resolve_unexpected
    ).checks[0]

    assert passed.outcome == Outcome.PASS
    assert passed.reason == "路由正确"
    assert passed.methods[0].implementation_id == "matches_json_schema"
    assert passed.methods[0].implementation_version == "1"
    assert failed.outcome == Outcome.FAIL
    assert failed.reason == "JSON Schema violation at $ (type)"
    assert failed.span_ids == ("2" * 16,)
    assert failed.failure is not None
    assert failed.failure.stage == FailureStage.ROUTING
    assert failed.failure.span_id == "2" * 16
    assert absent.outcome == Outcome.FAIL
    assert absent.reason == "未产生路由决策"
    assert absent.actual_missing
    assert absent.methods[0].implementation_id == "matches_json_schema"
    assert absent.failure is not None
    assert absent.failure.stage == FailureStage.ROUTING
    assert absent.failure.at_trace_completion
