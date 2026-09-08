import pytest

from agentgate.domain import (
    Case,
    CaseTurn,
    CheckResult,
    Equals,
    EvaluationResult,
    EvaluatorKind,
    EvaluatorSeverity,
    FailureStage,
    OneOf,
    Outcome,
    SkillRouteExpectation,
)
from agentgate.optimizer.confusion_matrix import build_routing_confusion_matrix


TRACE_ID = "a" * 32
EVALUATOR_HASH = "b" * 64
SPAN_ID = "c" * 16


def route_case(
    case_id: str,
    *turns: tuple[str, tuple[SkillRouteExpectation, ...]],
) -> Case:
    return Case(
        id=case_id,
        name=case_id,
        turns=tuple(
            CaseTurn(
                id=turn_id,
                input={"message": turn_id},
                expectations=expectations,
            )
            for turn_id, expectations in turns
        ),
    )


def route_expectation(expectation_id: str, expected: object) -> SkillRouteExpectation:
    return SkillRouteExpectation(
        id=expectation_id,
        condition=Equals(expected=expected),
    )


def route_check(
    check_id: str,
    *,
    turn_id: str,
    expectation_id: str,
    actual: object = "loan",
    actual_missing: bool = False,
    passed: bool = True,
) -> CheckResult:
    return CheckResult(
        id=check_id,
        name="route",
        turn_id=turn_id,
        expectation_id=expectation_id,
        outcome=Outcome.PASS if passed else Outcome.FAIL,
        score=1 if passed else 0,
        reason="checked",
        expected={"kind": "equals", "expected": "loan"},
        actual=None if actual_missing else actual,
        actual_missing=actual_missing,
        span_ids=(SPAN_ID,),
        failure_stage=None if passed else FailureStage.ROUTING,
        failure_sequence=None if passed else 1,
        failure_span_id=None if passed else SPAN_ID,
    )


def evaluation_result(
    result_id: str,
    case_id: str,
    *checks: CheckResult,
    run_id: str = "run-1",
) -> EvaluationResult:
    failed = tuple(check for check in checks if check.outcome == Outcome.FAIL)
    return EvaluationResult(
        id=result_id,
        run_id=run_id,
        case_id=case_id,
        trace_id=TRACE_ID,
        evaluator_id="routing",
        evaluator_name="Routing",
        evaluator_version="1",
        evaluator_content_sha256=EVALUATOR_HASH,
        evaluator_kind=EvaluatorKind.RULE,
        dimension="routing",
        metric="skill_route",
        severity=EvaluatorSeverity.STANDARD,
        outcome=Outcome.FAIL if failed else Outcome.PASS,
        score=0 if failed else 1,
        reason="evaluated",
        checks=checks,
        primary_failure_stage=FailureStage.ROUTING if failed else None,
    )


def test_aggregates_correct_and_incorrect_routes_into_cells() -> None:
    cases = (
        route_case("case-2", ("turn", (route_expectation("exp-2", "loan"),))),
        route_case("case-1", ("turn", (route_expectation("exp-1", "loan"),))),
        route_case("case-3", ("turn", (route_expectation("exp-3", "card"),))),
    )
    results = (
        evaluation_result(
            "result-2",
            "case-2",
            route_check(
                "check-2",
                turn_id="turn",
                expectation_id="exp-2",
                actual="card",
                passed=False,
            ),
        ),
        evaluation_result(
            "result-1",
            "case-1",
            route_check("check-1", turn_id="turn", expectation_id="exp-1"),
        ),
        evaluation_result(
            "result-3",
            "case-3",
            route_check(
                "check-3",
                turn_id="turn",
                expectation_id="exp-3",
                actual="card",
            ),
        ),
    )

    matrix = build_routing_confusion_matrix(cases, results)

    assert matrix.eligible_count == 3
    assert matrix.exclusions == ()
    assert [
        (cell.expected_skill_id, cell.actual_route.skill_id, cell.count)
        for cell in matrix.cells
    ] == [
        ("card", "card", 1),
        ("loan", "card", 1),
        ("loan", "loan", 1),
    ]


def test_classifies_missing_and_non_string_actual_routes() -> None:
    case = route_case(
        "case-1",
        (
            "turn",
            (
                route_expectation("missing", "loan"),
                route_expectation("ambiguous", "loan"),
            ),
        ),
    )
    result = evaluation_result(
        "result-1",
        "case-1",
        route_check(
            "check-missing",
            turn_id="turn",
            expectation_id="missing",
            actual_missing=True,
            passed=False,
        ),
        route_check(
            "check-ambiguous",
            turn_id="turn",
            expectation_id="ambiguous",
            actual=("loan", "card"),
            passed=False,
        ),
    )

    matrix = build_routing_confusion_matrix((case,), (result,))

    assert [cell.actual_route.kind.value for cell in matrix.cells] == [
        "missing",
        "ambiguous",
    ]


def test_correlates_each_multi_turn_expectation_independently() -> None:
    case = route_case(
        "case-1",
        ("turn-2", (route_expectation("exp-2", "card"),)),
        ("turn-1", (route_expectation("exp-1", "loan"),)),
    )
    result = evaluation_result(
        "result-1",
        "case-1",
        route_check("check-2", turn_id="turn-2", expectation_id="exp-2", actual="card"),
        route_check("check-1", turn_id="turn-1", expectation_id="exp-1"),
    )

    matrix = build_routing_confusion_matrix((case,), (result,))

    identities = {
        observation.identity
        for cell in matrix.cells
        for observation in cell.observations
    }
    assert identities == {
        ("case-1", "turn-1", "exp-1"),
        ("case-1", "turn-2", "exp-2"),
    }


def test_excludes_expectations_without_one_explicit_expected_skill() -> None:
    unsupported = SkillRouteExpectation(
        id="exp-many",
        condition=OneOf(allowed=("loan", "card")),
    )
    blank = route_expectation("exp-blank", " ")
    case = route_case("case-1", ("turn", (unsupported, blank)))

    matrix = build_routing_confusion_matrix((case,), ())

    assert matrix.eligible_count == 0
    assert [item.expectation_id for item in matrix.exclusions] == [
        "exp-blank",
        "exp-many",
    ]
    assert all(
        item.reason == "expected route does not define one explicit Skill ID"
        for item in matrix.exclusions
    )


def test_excludes_missing_and_duplicate_correlated_checks() -> None:
    case = route_case(
        "case-1",
        (
            "turn",
            (
                route_expectation("exp-missing", "loan"),
                route_expectation("exp-duplicate", "card"),
            ),
        ),
    )
    result = evaluation_result(
        "result-1",
        "case-1",
        route_check(
            "check-1",
            turn_id="turn",
            expectation_id="exp-duplicate",
            actual="card",
        ),
        route_check(
            "check-2",
            turn_id="turn",
            expectation_id="exp-duplicate",
            actual="card",
        ),
    )

    matrix = build_routing_confusion_matrix((case,), (result,))

    assert [(item.expectation_id, item.reason) for item in matrix.exclusions] == [
        ("exp-duplicate", "multiple correlated routing CheckResults"),
        ("exp-missing", "no correlated routing CheckResult"),
    ]


def test_input_order_does_not_change_matrix() -> None:
    cases = (
        route_case("case-2", ("turn", (route_expectation("exp-2", "card"),))),
        route_case("case-1", ("turn", (route_expectation("exp-1", "loan"),))),
    )
    results = (
        evaluation_result(
            "result-2",
            "case-2",
            route_check("check-2", turn_id="turn", expectation_id="exp-2", actual="card"),
        ),
        evaluation_result(
            "result-1",
            "case-1",
            route_check("check-1", turn_id="turn", expectation_id="exp-1"),
        ),
    )

    forward = build_routing_confusion_matrix(cases, results)
    reverse = build_routing_confusion_matrix(
        tuple(reversed(cases)),
        tuple(reversed(results)),
    )

    assert forward == reverse


def test_rejects_duplicate_cases_results_mixed_runs_and_unknown_cases() -> None:
    case = route_case("case-1", ("turn", (route_expectation("exp-1", "loan"),)))
    result = evaluation_result(
        "result-1",
        "case-1",
        route_check("check-1", turn_id="turn", expectation_id="exp-1"),
    )
    with pytest.raises(ValueError, match="Case IDs must be unique"):
        build_routing_confusion_matrix((case, case), (result,))
    with pytest.raises(ValueError, match="Result IDs must be unique"):
        build_routing_confusion_matrix((case,), (result, result))
    with pytest.raises(ValueError, match="one Run"):
        build_routing_confusion_matrix(
            (case,),
            (result, result.model_copy(update={"id": "result-2", "run_id": "run-2"})),
        )
    with pytest.raises(ValueError, match="unknown Cases"):
        build_routing_confusion_matrix(
            (case,),
            (result.model_copy(update={"case_id": "case-unknown"}),),
        )
