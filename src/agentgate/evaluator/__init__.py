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
        "skill-routing", "技能路由", "skill_routing", "routing",
        "skill_routing_accuracy", operator="equals",
    ),
    _rule(
        "required-tool", "必需工具", "required_tool", "tool_use",
        "tool_coverage", operator="contains_all",
    ),
    _rule(
        "forbidden-tool", "禁用工具", "forbidden_tool", "tool_use",
        "forbidden_tool_compliance", operator="contains_none",
        severity=EvaluatorSeverity.BLOCKING,
    ),
    _rule(
        "tool-arguments", "工具参数", "tool_arguments", "tool_use",
        "tool_argument_accuracy",
    ),
    _rule(
        "final-state", "最终状态", "final_state", "state", "final_state_match",
    ),
    _rule(
        "final-output", "最终输出", "final_output", "answer",
        "final_output_match",
    ),
    _rule(
        "policy-compliance", "策略合规", "policy_compliance", "safety",
        "policy_compliance", severity=EvaluatorSeverity.BLOCKING,
    ),
)

__all__ = ["EVALUATORS", "evaluate_case", "validate_evaluation_plan"]
