import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from agentgate.domain import (
    SkillDescriptor,
    TargetDescriptor,
    TargetRef,
    TargetSnapshot,
    TargetType,
    ToolDescriptor,
)


def target_ref(target_type: TargetType = TargetType.AGENT) -> TargetRef:
    return TargetRef(
        source_id="customer-prod",
        target_type=target_type,
        external_target_id="loan-agent",
        external_version_id="v1",
    )


def tool(name: str = "credit") -> ToolDescriptor:
    return ToolDescriptor(name=name, input_schema={"type": "object"})


def skill(skill_id: str = "loan", name: str = "Loan") -> SkillDescriptor:
    return SkillDescriptor(
        external_skill_id=skill_id,
        external_version_id="v1",
        name=name,
        prompt="Handle loans",
        tools=(tool(),),
    )


def test_target_ref_requires_exact_nonblank_external_identity():
    with pytest.raises(ValidationError):
        TargetRef(
            source_id=" ",
            target_type=TargetType.AGENT,
            external_target_id="agent",
            external_version_id="v1",
        )


def test_prompt_hash_is_generated_and_mismatch_is_rejected():
    descriptor = skill()
    assert descriptor.prompt_sha256 == hashlib.sha256(b"Handle loans").hexdigest()

    with pytest.raises(ValidationError, match="does not match"):
        SkillDescriptor(
            external_skill_id="loan",
            external_version_id="v1",
            name="Loan",
            prompt="Handle loans",
            prompt_sha256="0" * 64,
        )


def test_descriptor_identity_and_tool_invariants():
    duplicate_name = TargetDescriptor(
        ref=target_ref(),
        display_name="Agent",
        skills=(skill("one", "Same"), skill("two", "Same")),
    )
    assert len(duplicate_name.skills) == 2

    with pytest.raises(ValidationError, match="Skill identities must be unique"):
        TargetDescriptor(
            ref=target_ref(),
            display_name="Agent",
            skills=(skill("same"), skill("same")),
        )
    with pytest.raises(ValidationError, match="Tool names must be unique"):
        TargetDescriptor(
            ref=target_ref(),
            display_name="Agent",
            tools=(tool(), tool()),
        )
    with pytest.raises(ValidationError, match="cannot contain nested Skills"):
        TargetDescriptor(
            ref=target_ref(TargetType.SKILL),
            display_name="Skill",
            skills=(skill(),),
        )


def test_descriptor_hash_ignores_fetch_time_but_tracks_content():
    first = TargetDescriptor(
        ref=target_ref(),
        display_name="Agent",
        prompt="System prompt",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    later = TargetDescriptor(
        ref=target_ref(),
        display_name="Agent",
        prompt="System prompt",
        fetched_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    changed = TargetDescriptor(
        ref=target_ref(),
        display_name="Agent",
        prompt="Changed prompt",
        fetched_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert later.content_sha256 == first.content_sha256
    assert changed.content_sha256 != first.content_sha256


def test_metadata_and_invocation_config_reject_plaintext_credentials():
    with pytest.raises(ValidationError, match="credential-like"):
        SkillDescriptor(
            external_skill_id="skill",
            external_version_id="v1",
            name="Skill",
            metadata={"api_key": "plaintext"},
        )
    with pytest.raises(ValidationError, match="credential-like"):
        TargetSnapshot(
            ref=target_ref(),
            display_name="Agent",
            adapter_type="http",
            adapter_version="1",
            descriptor_sha256="a" * 64,
            invocation_config={"auth": {"access_token": "plaintext"}},
        )


def test_snapshot_hash_ignores_display_and_capture_time():
    snapshot = TargetSnapshot(
        ref=target_ref(),
        display_name="Old name",
        adapter_type="http",
        adapter_version="1",
        descriptor_sha256="a" * 64,
        invocation_config={"base_url": "https://agent.internal"},
        credential_ref="vault/customer-agent",
        captured_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    changed_display = TargetSnapshot(
        ref=target_ref(),
        display_name="New name",
        adapter_type="http",
        adapter_version="1",
        descriptor_sha256="a" * 64,
        invocation_config={"base_url": "https://agent.internal"},
        credential_ref="vault/customer-agent",
        captured_at=snapshot.captured_at + timedelta(days=1),
    )
    assert changed_display.content_sha256 == snapshot.content_sha256

