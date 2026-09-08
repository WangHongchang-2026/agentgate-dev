from datetime import UTC, datetime, timedelta

from agentgate.domain import (
    SkillDescriptor,
    TargetDescriptor,
    TargetRef,
    TargetType,
)
from agentgate.storage.sqlite import SQLiteRepository


FETCHED_AT = datetime(2026, 9, 8, tzinfo=UTC)


def target_ref(version: str = "v1") -> TargetRef:
    return TargetRef(
        source_id="customer-platform",
        target_type=TargetType.AGENT,
        external_target_id="loan-agent",
        external_version_id=version,
    )


def descriptor(
    *,
    prompt: str = "Route loan requests",
    fetched_at: datetime = FETCHED_AT,
) -> TargetDescriptor:
    return TargetDescriptor(
        ref=target_ref(),
        display_name="Loan Agent",
        prompt=prompt,
        skills=(
            SkillDescriptor(
                external_skill_id="loan-approval",
                external_version_id="v2",
                name="Loan Approval",
            ),
        ),
        fetched_at=fetched_at,
    )


def test_target_descriptor_round_trip_and_empty_lookup(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "target-descriptor.db")
    value = descriptor()

    assert repository.get_target_descriptor(value.content_sha256) is None
    assert repository.list_target_descriptors() == []

    repository.save_target_descriptor(value)

    assert repository.get_target_descriptor(value.content_sha256) == value
    assert repository.list_target_descriptors() == [value]
    assert repository.list_target_descriptors(value.ref) == [value]
    assert repository.list_target_descriptors(target_ref("unknown")) == []


def test_saving_same_descriptor_content_is_idempotent(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "target-idempotent.db")
    first = descriptor()
    later_fetch = descriptor(fetched_at=FETCHED_AT + timedelta(hours=1))

    assert later_fetch.content_sha256 == first.content_sha256

    repository.save_target_descriptor(first)
    repository.save_target_descriptor(first)
    repository.save_target_descriptor(later_fetch)

    assert repository.list_target_descriptors() == [first]


def test_changed_external_version_content_keeps_both_descriptors(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "target-revisions.db")
    first = descriptor()
    changed = descriptor(
        prompt="Changed routing prompt",
        fetched_at=FETCHED_AT + timedelta(hours=1),
    )

    assert changed.ref == first.ref
    assert changed.content_sha256 != first.content_sha256

    repository.save_target_descriptor(first)
    repository.save_target_descriptor(changed)

    assert repository.list_target_descriptors(first.ref) == [changed, first]
    assert repository.get_target_descriptor(first.content_sha256) == first
    assert repository.get_target_descriptor(changed.content_sha256) == changed


def test_target_descriptor_filter_uses_exact_reference(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "target-filter.db")
    version_one = descriptor()
    version_two = version_one.model_copy(
        update={
            "ref": target_ref("v2"),
            "fetched_at": FETCHED_AT + timedelta(hours=1),
            "content_sha256": "",
        }
    )
    version_two = TargetDescriptor.model_validate(
        version_two.model_dump(mode="json")
    )
    repository.save_target_descriptor(version_one)
    repository.save_target_descriptor(version_two)

    assert repository.list_target_descriptors(target_ref("v1")) == [version_one]
    assert repository.list_target_descriptors(target_ref("v2")) == [version_two]
