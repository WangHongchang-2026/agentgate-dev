from agentgate.domain import (
    Case, CaseTurn, EvaluatorKind, Outcome, EvaluatorSpec, Trace,
)
from agentgate.evaluator.base import Evaluator
from agentgate.evaluator.models import Evaluation
from agentgate.evaluator.registry import register_evaluator
from agentgate.evaluator.runner import evaluate_case


@register_evaluator
class CrashingEvaluator(Evaluator):
    kind = EvaluatorKind.RULE
    implementation_id = "test_crash"

    def evaluate(self, spec, turn, trace, resolve):
        raise RuntimeError("provider token=secret-value")


@register_evaluator
class TimeoutEvaluator(Evaluator):
    kind = EvaluatorKind.RULE
    implementation_id = "test_timeout"

    def evaluate(self, spec, turn, trace, resolve):
        raise TimeoutError("too slow")


@register_evaluator
class MalformedEvaluator(Evaluator):
    kind = EvaluatorKind.RULE
    implementation_id = "test_malformed"

    def evaluate(self, spec, turn, trace, resolve):
        return {"not": "an Evaluation"}


@register_evaluator
class HealthyEvaluator(Evaluator):
    kind = EvaluatorKind.RULE
    implementation_id = "test_healthy"

    def evaluate(self, spec, turn, trace, resolve):
        return Evaluation(checks=())


def spec(implementation_id):
    return EvaluatorSpec(
        id=implementation_id,
        name=implementation_id,
        dimension="state",
        metric=implementation_id,
        implementation_id=implementation_id,
    )


def simple_case():
    return Case(
        id="case", name="case",
        turns=(CaseTurn(id="turn", input={"message": "hello"}),),
    )


def test_evaluator_errors_are_results_and_are_sanitized():
    case = simple_case()
    trace = Trace(trace_id="0" * 32, run_id="run", case_id="case", spans=())
    results = evaluate_case(
        case, trace, (spec("test_crash"), spec("test_timeout"), spec("test_malformed"))
    )
    assert [item.outcome for item in results] == [Outcome.ERROR] * 3
    assert [item.error_detail.category for item in results] == [
        "crash", "timeout", "invalid_output",
    ]
    assert all(item.score is None and item.primary_failure_stage is None for item in results)
    assert "secret-value" not in results[0].error_detail.message


def test_independent_evaluator_continues_after_error():
    results = evaluate_case(
        simple_case(), Trace(trace_id="0" * 32, run_id="run", case_id="case", spans=()),
        (spec("test_crash"), spec("test_healthy")),
    )
    assert results[0].outcome == Outcome.ERROR
    assert results[1].outcome == Outcome.NOT_APPLICABLE
