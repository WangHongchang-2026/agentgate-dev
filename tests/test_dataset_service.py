from agentgate.application import DatasetManagement
from agentgate.domain import Case, CaseTurn
from agentgate.storage.sqlite import SQLiteRepository


def test_create_edit_publish_and_preserve_old_version(tmp_path):
    service = DatasetManagement(SQLiteRepository(tmp_path / "datasets.db"))
    dataset = service.create_dataset("My Dataset", "demo")
    draft = service.create_draft(dataset.id)
    case = Case(
        id="case-1", name="Case 1",
        turns=(CaseTurn(id="turn-1", input={"message": "hello"}),),
    )
    service.save_case(dataset.id, case)
    first = service.publish_draft(dataset.id)
    assert first.version == 1
    assert first.cases[0].name == "Case 1"

    service.create_draft(dataset.id, based_on_version=1)
    changed = case.model_copy(update={"name": "Case 1 changed"})
    service.save_case(dataset.id, changed)
    second = service.publish_draft(dataset.id)
    assert second.version == 2
    assert service.get_version(dataset.id, 1).cases[0].name == "Case 1"
    assert service.get_version(dataset.id, 2).cases[0].name == "Case 1 changed"


def test_copy_dataset_has_independent_identity_and_draft(tmp_path):
    service = DatasetManagement(SQLiteRepository(tmp_path / "copy.db"))
    source = service.create_dataset("Source")
    service.create_draft(source.id)
    service.save_case(source.id, Case(
        id="case", name="Case",
        turns=(CaseTurn(id="turn", input={"message": "hello"}),),
    ))
    service.publish_draft(source.id)
    copied, draft = service.copy_dataset(source.id, "Copy")
    assert copied.id != source.id
    assert draft.dataset_id == copied.id
    assert draft.status == "draft"
    assert draft.cases[0].id != "case"


def test_archiving_hides_catalog_entry_but_preserves_published_versions(tmp_path):
    service = DatasetManagement(SQLiteRepository(tmp_path / "archive.db"))
    dataset = service.create_dataset("Archive me")
    service.create_draft(dataset.id)
    service.save_case(dataset.id, Case(
        id="case", name="Case",
        turns=(CaseTurn(id="turn", input={"message": "hello"}),),
    ))
    published = service.publish_draft(dataset.id)

    archived = service.archive_dataset(dataset.id)

    assert archived.archived is True
    assert dataset.id not in {item.id for item in service.list_datasets()}
    assert dataset.id in {
        item.id for item in service.list_datasets(include_archived=True)
    }
    assert service.get_version(dataset.id, published.version).content_sha256 == (
        published.content_sha256
    )


def test_content_hash_changes_with_case_content_not_catalog_display_name(tmp_path):
    service = DatasetManagement(SQLiteRepository(tmp_path / "hash.db"))
    dataset = service.create_dataset("Original name")
    draft = service.create_draft(dataset.id)
    empty_hash = draft.content_sha256
    case = Case(
        id="case", name="Case",
        turns=(CaseTurn(id="turn", input={"risk": "high"}),),
    )
    with_case = service.save_case(dataset.id, case)
    assert with_case.content_sha256 != empty_hash

    service.update_dataset(dataset.id, name="Renamed catalog entry")
    after_rename = service.get_draft(dataset.id)
    assert after_rename.content_sha256 == with_case.content_sha256

    changed = case.model_copy(update={
        "turns": (CaseTurn(id="turn", input={"risk": "low"}),),
    })
    changed_version = service.save_case(dataset.id, changed)
    assert changed_version.content_sha256 != with_case.content_sha256


def test_copy_reorder_remove_cases_and_discard_draft(tmp_path):
    service = DatasetManagement(SQLiteRepository(tmp_path / "case-workflows.db"))
    dataset = service.create_dataset("Case workflows")
    service.create_draft(dataset.id)
    first = Case(
        id="first", name="First",
        turns=(CaseTurn(id="first-turn", input={"message": "first"}),),
    )
    second = Case(
        id="second", name="Second",
        turns=(CaseTurn(id="second-turn", input={"message": "second"}),),
    )
    service.save_case(dataset.id, first)
    service.save_case(dataset.id, second)

    copied_version = service.copy_case(dataset.id, first.id)
    copied = next(item for item in copied_version.cases if item.id not in {"first", "second"})
    assert copied.name == "First（副本）"

    reordered = service.reorder_cases(
        dataset.id, ["second", copied.id, "first"]
    )
    assert [item.id for item in reordered.cases] == ["second", copied.id, "first"]

    removed = service.remove_case(dataset.id, "first")
    assert [item.id for item in removed.cases] == ["second", copied.id]
    service.discard_draft(dataset.id)
    assert service.get_draft(dataset.id) is None
