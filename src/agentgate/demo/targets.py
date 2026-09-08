"""Canonical Target metadata for the deterministic Loan Agent demo."""

from __future__ import annotations

from agentgate.demo.loan import DEMO_CREATED_AT, LoanAgent
from agentgate.domain import (
    SkillDescriptor,
    TargetDescriptor,
    TargetRef,
    TargetSnapshot,
    TargetType,
    ToolDescriptor,
)
from agentgate.integrations.targets import DemoLoanTargetAdapter


_CREDIT_INQUIRY = ToolDescriptor(
    name="credit_inquiry",
    description="Read the risk classification for one loan application.",
)
_APPROVE_LOAN = ToolDescriptor(
    name="approve_loan",
    description="Approve one eligible loan application.",
)
_REQUEST_HUMAN_REVIEW = ToolDescriptor(
    name="request_human_review",
    description="Send one loan application to human review.",
)
_REPAYMENT_PLAN = ToolDescriptor(
    name="repayment_plan",
    description="Calculate a repayment schedule for one application.",
)
_COMPLAINT = ToolDescriptor(
    name="complaint",
    description="Open a complaint for one application.",
)


def _skills(agent_version: str) -> tuple[SkillDescriptor, ...]:
    approval_version = (
        "loan-approval-v1-risky"
        if agent_version == "loan-agent-v1-risky"
        else "loan-approval-v2-fixed"
    )
    return (
        SkillDescriptor(
            external_skill_id="loan_approval",
            external_version_id=approval_version,
            name="Loan Approval",
            description="Assess a loan application and choose an approval action.",
            tools=(_CREDIT_INQUIRY, _APPROVE_LOAN, _REQUEST_HUMAN_REVIEW),
        ),
        SkillDescriptor(
            external_skill_id="repayment_plan",
            external_version_id="repayment-plan-v1",
            name="Repayment Plan",
            description="Calculate repayment installments for a loan application.",
            tools=(_REPAYMENT_PLAN,),
        ),
        SkillDescriptor(
            external_skill_id="complaint",
            external_version_id="complaint-v1",
            name="Complaint",
            description="Record a complaint associated with a loan application.",
            tools=(_COMPLAINT,),
        ),
        SkillDescriptor(
            external_skill_id="credit_inquiry",
            external_version_id="credit-inquiry-v1",
            name="Credit Inquiry",
            description="Retrieve the risk classification for a loan application.",
            tools=(_CREDIT_INQUIRY,),
        ),
    )


def _descriptor(version: str) -> TargetDescriptor:
    policy = (
        "May approve high-risk applications without human review."
        if version == "loan-agent-v1-risky"
        else "High-risk applications must be sent to human review."
    )
    return TargetDescriptor(
        ref=TargetRef(
            source_id="agentgate-demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id=version,
        ),
        display_name="Loan Agent",
        description="Deterministic multi-skill Agent used by the AgentGate demo.",
        prompt=f"Route financial requests to the correct Skill. {policy}",
        skills=_skills(version),
        tools=(
            _CREDIT_INQUIRY,
            _APPROVE_LOAN,
            _REQUEST_HUMAN_REVIEW,
            _REPAYMENT_PLAN,
            _COMPLAINT,
        ),
        fetched_at=DEMO_CREATED_AT,
    )


LOAN_AGENT_DESCRIPTORS = tuple(_descriptor(version) for version in LoanAgent.versions)
_DESCRIPTORS_BY_VERSION = {
    descriptor.ref.external_version_id: descriptor
    for descriptor in LOAN_AGENT_DESCRIPTORS
}


def get_demo_target_descriptor(version: str) -> TargetDescriptor:
    try:
        return _DESCRIPTORS_BY_VERSION[version]
    except KeyError as error:
        raise ValueError(f"unknown demo Target version: {version}") from error


def build_demo_target_snapshot(descriptor: TargetDescriptor) -> TargetSnapshot:
    if descriptor not in LOAN_AGENT_DESCRIPTORS:
        raise ValueError("descriptor is not a canonical Loan Agent descriptor")
    return TargetSnapshot(
        ref=descriptor.ref,
        display_name=descriptor.display_name,
        adapter_type=DemoLoanTargetAdapter.adapter_type,
        adapter_version=DemoLoanTargetAdapter.adapter_version,
        descriptor_sha256=descriptor.content_sha256,
        invocation_config={"provider": "deterministic"},
    )


__all__ = [
    "LOAN_AGENT_DESCRIPTORS",
    "build_demo_target_snapshot",
    "get_demo_target_descriptor",
]
