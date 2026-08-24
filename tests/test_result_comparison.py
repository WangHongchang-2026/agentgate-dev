from types import SimpleNamespace

import pytest

from agentgate.result.comparison import (
    classify_result_change,
    compare_case_results,
)


def result(evaluator_id, outcome, score, *, name=None, reason="reason"):
    return SimpleNamespace(
        evaluator_id=evaluator_id,
        evaluator_name=name or evaluator_id,
        outcome=outcome,
        score=score,
        reason=reason,
    )


@pytest.mark.parametrize(
    ("before", "after", "expected"),
    [
        (("fail", 0.0), ("pass", 1.0), "improved"),
        (("review", 0.5), ("pass", 1.0), "improved"),
        (("pass", 1.0), ("review", 0.5), "regressed"),
        (("pass", 0.5), ("pass", 0.75), "improved"),
        (("pass", 0.75), ("pass", 0.5), "regressed"),
        (("pass", 1.0), ("pass", 1.0), "unchanged"),
        (("error", None), ("pass", 1.0), "incomparable"),
        (("pass", 1.0), ("not_applicable", None), "incomparable"),
    ],
)
def test_result_change_truth_table(before, after, expected):
    assert classify_result_change(
        result("evaluator", before[0], before[1]),
        result("evaluator", after[0], after[1]),
    ) == expected


def test_missing_result_is_incomparable():
    assert classify_result_change(None, result("evaluator", "pass", 1.0)) == "incomparable"
    assert classify_result_change(result("evaluator", "pass", 1.0), None) == "incomparable"


def test_compare_case_results_pairs_by_evaluator_and_preserves_summaries():
    comparison = compare_case_results(
        [
            result("routing", "fail", 0.0, name="路由", reason="旧路由失败"),
            result("missing-after", "pass", 1.0),
        ],
        [
            result("routing", "pass", 1.0, name="路由", reason="新路由通过"),
            result("missing-before", "pass", 1.0),
        ],
    )

    assert comparison["overall"] == "improved"
    assert comparison["counts"] == {
        "improved": 1,
        "regressed": 0,
        "unchanged": 0,
        "incomparable": 2,
    }
    routing = next(item for item in comparison["evaluators"] if item["evaluator_id"] == "routing")
    assert routing == {
        "evaluator_id": "routing",
        "evaluator_name": "路由",
        "status": "improved",
        "before": {"outcome": "fail", "score": 0.0, "reason": "旧路由失败"},
        "after": {"outcome": "pass", "score": 1.0, "reason": "新路由通过"},
    }


def test_compare_case_results_reports_mixed_changes():
    comparison = compare_case_results(
        [result("a", "fail", 0.0), result("b", "pass", 1.0)],
        [result("a", "pass", 1.0), result("b", "fail", 0.0)],
    )
    assert comparison["overall"] == "mixed"


def test_compare_case_results_reports_unchanged_and_incomparable_only():
    unchanged = compare_case_results(
        [result("a", "pass", 1.0)], [result("a", "pass", 1.0)]
    )
    incomparable = compare_case_results(
        [result("a", "error", None)], [result("a", "pass", 1.0)]
    )
    assert unchanged["overall"] == "unchanged"
    assert incomparable["overall"] == "incomparable"
