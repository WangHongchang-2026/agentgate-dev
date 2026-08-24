"""Pure comparison of evaluation Results for one Case."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from agentgate.domain import Outcome, Result


_INCOMPARABLE = {Outcome.ERROR, Outcome.NOT_APPLICABLE, "error", "not_applicable"}


def summarize_result(result: Result | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "outcome": result.outcome,
        "score": result.score,
        "reason": result.reason,
    }


def classify_result_change(before: Result | None, after: Result | None) -> str:
    if before is None or after is None:
        return "incomparable"
    if before.outcome in _INCOMPARABLE or after.outcome in _INCOMPARABLE:
        return "incomparable"
    if before.outcome == after.outcome and before.score == after.score:
        return "unchanged"
    if before.outcome in {Outcome.FAIL, Outcome.REVIEW, "fail", "review"} and after.outcome in {
        Outcome.PASS, "pass",
    }:
        return "improved"
    if before.outcome in {Outcome.PASS, "pass"} and after.outcome in {
        Outcome.FAIL, Outcome.REVIEW, "fail", "review",
    }:
        return "regressed"
    if before.score is not None and after.score is not None:
        if after.score > before.score:
            return "improved"
        if after.score < before.score:
            return "regressed"
    return "unchanged"


def _overall(counts: dict[str, int], total: int) -> str:
    if counts["improved"] and counts["regressed"]:
        return "mixed"
    if counts["regressed"]:
        return "regressed"
    if counts["improved"]:
        return "improved"
    if total and counts["unchanged"] == total:
        return "unchanged"
    return "incomparable"


def compare_case_results(
    before_results: Iterable[Result],
    after_results: Iterable[Result],
) -> dict[str, Any]:
    before_by_id = {item.evaluator_id: item for item in before_results}
    after_by_id = {item.evaluator_id: item for item in after_results}
    comparisons = []
    for evaluator_id in sorted(set(before_by_id) | set(after_by_id)):
        before = before_by_id.get(evaluator_id)
        after = after_by_id.get(evaluator_id)
        comparisons.append({
            "evaluator_id": evaluator_id,
            "evaluator_name": (after or before).evaluator_name,
            "status": classify_result_change(before, after),
            "before": summarize_result(before),
            "after": summarize_result(after),
        })
    counts = {
        status: sum(item["status"] == status for item in comparisons)
        for status in ("improved", "regressed", "unchanged", "incomparable")
    }
    return {
        "overall": _overall(counts, len(comparisons)),
        "counts": counts,
        "evaluators": comparisons,
    }
