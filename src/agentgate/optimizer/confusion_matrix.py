"""Observed Skill-routing confusion from persisted evaluation checks."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from agentgate.domain import (
    Case,
    CheckResult,
    Equals,
    EvaluationResult,
    ObservedRoute,
    ObservedRouteKind,
    RoutingConfusionCell,
    RoutingConfusionMatrix,
    RoutingExclusion,
    RoutingObservation,
    SkillRouteExpectation,
)


_EXPECTED_ROUTE_NOT_SINGLE_SKILL = (
    "expected route does not define one explicit Skill ID"
)
_MISSING_ROUTING_CHECK = "no correlated routing CheckResult"
_MULTIPLE_ROUTING_CHECKS = "multiple correlated routing CheckResults"

_ExpectationKey = tuple[str, str, str]
_CheckMatch = tuple[EvaluationResult, CheckResult]
_CellKey = tuple[str, ObservedRouteKind, str | None]


def _expected_skill(expectation: SkillRouteExpectation) -> str | None:
    condition = expectation.condition
    if not isinstance(condition, Equals):
        return None
    expected = condition.expected
    if not isinstance(expected, str) or not expected.strip():
        return None
    return expected


def _actual_route(check: CheckResult) -> ObservedRoute:
    if check.actual_missing:
        return ObservedRoute(kind=ObservedRouteKind.MISSING)
    if isinstance(check.actual, str) and check.actual.strip():
        return ObservedRoute(
            kind=ObservedRouteKind.SKILL,
            skill_id=check.actual,
        )
    return ObservedRoute(kind=ObservedRouteKind.AMBIGUOUS)


def _route_sort_key(route: ObservedRoute) -> tuple[int, str]:
    order = {
        ObservedRouteKind.SKILL: 0,
        ObservedRouteKind.MISSING: 1,
        ObservedRouteKind.AMBIGUOUS: 2,
    }
    return order[route.kind], route.skill_id or ""


def _validate_inputs(
    cases: tuple[Case, ...],
    results: tuple[EvaluationResult, ...],
) -> dict[str, Case]:
    case_ids = tuple(case.id for case in cases)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("confusion-matrix Case IDs must be unique")

    result_ids = tuple(result.id for result in results)
    if len(set(result_ids)) != len(result_ids):
        raise ValueError("confusion-matrix Result IDs must be unique")
    if len({result.run_id for result in results}) > 1:
        raise ValueError("confusion-matrix Results must belong to one Run")

    case_by_id = {case.id: case for case in cases}
    unknown_case_ids = {result.case_id for result in results}.difference(case_by_id)
    if unknown_case_ids:
        unknown = ", ".join(sorted(unknown_case_ids))
        raise ValueError(f"confusion-matrix Results reference unknown Cases: {unknown}")
    return case_by_id


def _check_index(
    results: tuple[EvaluationResult, ...],
) -> dict[_ExpectationKey, list[_CheckMatch]]:
    matches: dict[_ExpectationKey, list[_CheckMatch]] = defaultdict(list)
    for result in results:
        for check in result.checks:
            if check.turn_id is None or check.expectation_id is None:
                continue
            matches[(result.case_id, check.turn_id, check.expectation_id)].append(
                (result, check)
            )
    return matches


def build_routing_confusion_matrix(
    cases: Sequence[Case],
    results: Sequence[EvaluationResult],
) -> RoutingConfusionMatrix:
    """Aggregate comparable Skill-route expectations into observed cells."""

    case_items = tuple(cases)
    result_items = tuple(results)
    _validate_inputs(case_items, result_items)
    checks = _check_index(result_items)

    observations: list[RoutingObservation] = []
    exclusions: list[RoutingExclusion] = []
    for case in sorted(case_items, key=lambda item: item.id):
        for turn in sorted(case.turns, key=lambda item: item.id):
            for expectation in sorted(turn.expectations, key=lambda item: item.id):
                if not isinstance(expectation, SkillRouteExpectation):
                    continue
                identity = (case.id, turn.id, expectation.id)
                expected_skill_id = _expected_skill(expectation)
                if expected_skill_id is None:
                    exclusions.append(RoutingExclusion(
                        case_id=case.id,
                        turn_id=turn.id,
                        expectation_id=expectation.id,
                        reason=_EXPECTED_ROUTE_NOT_SINGLE_SKILL,
                    ))
                    continue

                matched = checks.get(identity, ())
                if not matched:
                    exclusions.append(RoutingExclusion(
                        case_id=case.id,
                        turn_id=turn.id,
                        expectation_id=expectation.id,
                        reason=_MISSING_ROUTING_CHECK,
                    ))
                    continue
                if len(matched) > 1:
                    exclusions.append(RoutingExclusion(
                        case_id=case.id,
                        turn_id=turn.id,
                        expectation_id=expectation.id,
                        reason=_MULTIPLE_ROUTING_CHECKS,
                    ))
                    continue

                result, check = matched[0]
                observations.append(RoutingObservation(
                    case_id=case.id,
                    turn_id=turn.id,
                    expectation_id=expectation.id,
                    result_id=result.id,
                    trace_id=result.trace_id,
                    expected_skill_id=expected_skill_id,
                    actual_route=_actual_route(check),
                    span_ids=tuple(sorted(check.span_ids)),
                ))

    grouped: dict[_CellKey, list[RoutingObservation]] = defaultdict(list)
    for observation in observations:
        route = observation.actual_route
        grouped[
            (observation.expected_skill_id, route.kind, route.skill_id)
        ].append(observation)

    cells = []
    for (expected_skill_id, route_kind, skill_id), values in grouped.items():
        ordered = tuple(sorted(values, key=lambda item: item.identity))
        cells.append(RoutingConfusionCell(
            expected_skill_id=expected_skill_id,
            actual_route=ObservedRoute(kind=route_kind, skill_id=skill_id),
            observations=ordered,
            count=len(ordered),
        ))
    cells.sort(key=lambda cell: (
        cell.expected_skill_id,
        _route_sort_key(cell.actual_route),
    ))
    exclusions.sort(key=lambda item: item.identity)
    return RoutingConfusionMatrix(
        cells=tuple(cells),
        eligible_count=len(observations),
        exclusions=tuple(exclusions),
    )
