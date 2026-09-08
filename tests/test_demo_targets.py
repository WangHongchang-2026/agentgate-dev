import pytest

from agentgate.demo.loan import LoanAgent
from agentgate.demo.targets import (
    LOAN_AGENT_DESCRIPTORS,
    build_demo_target_snapshot,
    get_demo_target_descriptor,
)
from agentgate.domain import TargetDescriptor, TargetType


def test_demo_descriptors_cover_every_agent_version() -> None:
    assert tuple(
        descriptor.ref.external_version_id
        for descriptor in LOAN_AGENT_DESCRIPTORS
    ) == LoanAgent.versions

    for descriptor in LOAN_AGENT_DESCRIPTORS:
        assert descriptor.ref.source_id == "agentgate-demo"
        assert descriptor.ref.target_type is TargetType.AGENT
        assert descriptor.ref.external_target_id == "loan-agent"
        assert len(descriptor.skills) == 4
        assert {skill.external_skill_id for skill in descriptor.skills} == {
            "loan_approval",
            "repayment_plan",
            "complaint",
            "credit_inquiry",
        }
        assert descriptor.content_sha256


def test_demo_descriptors_pin_changed_and_shared_skill_versions() -> None:
    risky = get_demo_target_descriptor("loan-agent-v1-risky")
    fixed = get_demo_target_descriptor("loan-agent-v2-fixed")
    risky_versions = {
        skill.external_skill_id: skill.external_version_id
        for skill in risky.skills
    }
    fixed_versions = {
        skill.external_skill_id: skill.external_version_id
        for skill in fixed.skills
    }

    assert risky_versions["loan_approval"] == "loan-approval-v1-risky"
    assert fixed_versions["loan_approval"] == "loan-approval-v2-fixed"
    assert risky_versions["repayment_plan"] == fixed_versions["repayment_plan"]
    assert risky.content_sha256 != fixed.content_sha256


def test_demo_snapshot_references_exact_descriptor() -> None:
    descriptor = get_demo_target_descriptor("loan-agent-v2-fixed")

    snapshot = build_demo_target_snapshot(descriptor)

    assert snapshot.ref == descriptor.ref
    assert snapshot.display_name == descriptor.display_name
    assert snapshot.descriptor_sha256 == descriptor.content_sha256
    assert snapshot.adapter_type == "demo_loan"
    assert snapshot.adapter_version == "1"


def test_demo_target_helpers_reject_unknown_or_noncanonical_descriptors() -> None:
    with pytest.raises(ValueError, match="unknown demo Target version"):
        get_demo_target_descriptor("missing")

    canonical = get_demo_target_descriptor("loan-agent-v2-fixed")
    changed = TargetDescriptor.model_validate(
        {
            **canonical.model_dump(mode="json"),
            "display_name": "Changed",
            "content_sha256": "",
        }
    )
    with pytest.raises(ValueError, match="not a canonical Loan Agent descriptor"):
        build_demo_target_snapshot(changed)
