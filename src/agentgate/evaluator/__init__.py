"""Public evaluator API."""

from agentgate.domain import EvaluatorSeverity, EvaluatorSpec

from . import operators as _operators
from . import rules as _rules
from .runner import evaluate_case
from .validation import validate_evaluation_plan


def _rule(
    evaluator_id: str,
    name: str,
    implementation_id: str,
    dimension: str,
    metric: str,
    *,
    operator: str | None = None,
    severity: EvaluatorSeverity = EvaluatorSeverity.STANDARD,
) -> EvaluatorSpec:
    config = (
        {"operator": operator, "operator_version": "1"} if operator else {}
    )
    return EvaluatorSpec(
        id=evaluator_id,
        name=name,
        implementation_id=implementation_id,
        dimension=dimension,
        metric=metric,
        severity=severity,
        config=config,
    )


EVALUATORS = (
    _rule(
        "skill-routing", "Skill Routing", "skill_routing", "routing",
        "skill_routing_accuracy", operator="equals",
    ),
    _rule(
        "required-tool", "Required Tool", "required_tool", "tool_use",
        "tool_coverage", operator="contains_all",
    ),
    _rule(
        "forbidden-tool", "Forbidden Tool", "forbidden_tool", "tool_use",
        "forbidden_tool_compliance", operator="contains_none",
        severity=EvaluatorSeverity.BLOCKING,
    ),
    _rule(
        "tool-arguments", "Tool Arguments", "tool_arguments", "tool_use",
        "tool_argument_accuracy",
    ),
    _rule(
        "final-state", "Final State", "final_state", "state", "final_state_match",
    ),
    _rule(
        "final-output", "Final Output", "final_output", "answer",
        "final_output_match",
    ),
    _rule(
        "policy-compliance", "Policy Compliance", "policy_compliance", "safety",
        "policy_compliance", severity=EvaluatorSeverity.BLOCKING,
    ),
)

__all__ = ["EVALUATORS", "evaluate_case", "validate_evaluation_plan"]
