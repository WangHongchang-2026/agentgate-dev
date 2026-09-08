from agentgate.evaluator import rule
from agentgate.evaluator.rule.output import FinalOutputEvaluator
from agentgate.evaluator.rule.policy import (
    PolicyComplianceEvaluator,
    UnsupportedPolicy,
)
from agentgate.evaluator.rule.routing import SkillRoutingEvaluator
from agentgate.evaluator.rule.state import FinalStateEvaluator
from agentgate.evaluator.rule.tool_use import (
    ForbiddenToolEvaluator,
    RequiredToolEvaluator,
    ToolArgumentsEvaluator,
)


def test_rule_package_exports_only_the_approved_public_symbols() -> None:
    expected = [
        "FinalOutputEvaluator",
        "FinalStateEvaluator",
        "ForbiddenToolEvaluator",
        "PolicyComplianceEvaluator",
        "RequiredToolEvaluator",
        "SkillRoutingEvaluator",
        "ToolArgumentsEvaluator",
        "UnsupportedPolicy",
    ]

    assert rule.__all__ == expected
    assert rule.FinalOutputEvaluator is FinalOutputEvaluator
    assert rule.FinalStateEvaluator is FinalStateEvaluator
    assert rule.ForbiddenToolEvaluator is ForbiddenToolEvaluator
    assert rule.PolicyComplianceEvaluator is PolicyComplianceEvaluator
    assert rule.RequiredToolEvaluator is RequiredToolEvaluator
    assert rule.SkillRoutingEvaluator is SkillRoutingEvaluator
    assert rule.ToolArgumentsEvaluator is ToolArgumentsEvaluator
    assert rule.UnsupportedPolicy is UnsupportedPolicy
