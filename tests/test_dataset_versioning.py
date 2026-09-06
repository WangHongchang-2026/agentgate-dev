from datetime import UTC, datetime, timedelta

import pytest

from agentgate.dataset.versioning import (
    copy_case,
    create_draft,
    publish_draft,
    remove_case,
    reorder_cases,
    with_case,
)
from agentgate.domain import (
    Case,
    CaseTurn,
    Dataset,
    DatasetVersion,
    DatasetVersionStatus,
)


NOW = datetime(2026, 9, 6, tzinfo=UTC)


def case(case_id: str, name: str | None = None) -> Case:
    return Case(
        id=case_id,
        name=name or case_id,
        turns=(CaseTurn(id=f"{case_id}-turn", input={"message": case_id}),),
    )


def empty_draft() -> DatasetVersion:
    dataset = Dataset(id="dataset", name="Dataset", created_at=NOW, updated_at=NOW)
    return create_draft(dataset, None, "draft", NOW)


def test_create_draft_from_empty_and_published_base():
    dataset = Dataset(id="dataset", name="Dataset", created_at=NOW, updated_at=NOW)
    first_draft = create_draft(dataset, None, "draft-1", NOW)
    populated = with_case(first_draft, case("case"), NOW)
    published = publish_draft(populated, "published-1", 1, NOW)
    next_draft = create_draft(dataset, published, "draft-2", NOW + timedelta(seconds=1))

    assert first_draft.cases == ()
    assert next_draft.based_on_version == 1
    assert next_draft.cases == published.cases


def test_create_draft_rejects_invalid_base():
    dataset = Dataset(id="dataset", name="Dataset", created_at=NOW, updated_at=NOW)
    with pytest.raises(ValueError, match="base must be published"):
        create_draft(dataset, empty_draft(), "new", NOW)

    other = Dataset(id="other", name="Other", created_at=NOW, updated_at=NOW)
    published = publish_draft(with_case(empty_draft(), case("case"), NOW), "v1", 1, NOW)
    with pytest.raises(ValueError, match="another Dataset"):
        create_draft(other, published, "new", NOW)


def test_case_transformations_preserve_draft_identity_and_order():
    draft = empty_draft()
    draft = with_case(draft, case("first"), NOW)
    draft = with_case(draft, case("second"), NOW)
    changed = with_case(draft, case("first", "Changed"), NOW)
    copied = copy_case(changed, "first", "copy", "Copy", NOW)
    reordered = reorder_cases(copied, ("second", "copy", "first"), NOW)
    removed = remove_case(reordered, "first", NOW)

    assert changed.id == draft.id
    assert [item.name for item in changed.cases] == ["Changed", "second"]
    assert [item.id for item in reordered.cases] == ["second", "copy", "first"]
    assert [item.id for item in removed.cases] == ["second", "copy"]


def test_case_transformations_reject_unknown_incomplete_and_stale_changes():
    draft = with_case(empty_draft(), case("first"), NOW)
    with pytest.raises(ValueError, match="unknown Case"):
        remove_case(draft, "missing", NOW)
    with pytest.raises(ValueError, match="unknown Case"):
        copy_case(draft, "missing", "copy", "Copy", NOW)
    with pytest.raises(ValueError, match="every draft Case"):
        reorder_cases(draft, (), NOW)
    with pytest.raises(ValueError, match="must not precede"):
        with_case(draft, case("second"), NOW - timedelta(seconds=1))


def test_publish_requires_nonempty_draft_and_explicit_publication_values():
    with pytest.raises(ValueError, match="at least one Case"):
        publish_draft(empty_draft(), "published", 1, NOW)

    draft = with_case(empty_draft(), case("case"), NOW)
    published = publish_draft(draft, "published", 3, NOW + timedelta(seconds=1))

    assert published.id == "published"
    assert published.version == 3
    assert published.status == DatasetVersionStatus.PUBLISHED
    assert published.created_at == draft.created_at
    assert published.content_sha256 == draft.content_sha256
    with pytest.raises(ValueError, match="requires a draft"):
        publish_draft(published, "again", 4, NOW + timedelta(seconds=2))
