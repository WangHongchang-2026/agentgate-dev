from agentgate.application import DatasetManagement
from agentgate.dataset.formats.xlsx import dump as dump_xlsx
from agentgate.domain import Case, CaseTurn
from agentgate.storage.sqlite import SQLiteRepository


def test_canonical_json_export_import_round_trip(tmp_path):
    source = DatasetManagement(SQLiteRepository(tmp_path / "source.db"))
    dataset = source.create_dataset("Exported")
    source.create_draft(dataset.id)
    source.save_case(dataset.id, Case(
        id="case", name="Case",
        turns=(CaseTurn(id="turn", input={"message": "hello"}),),
    ))
    published = source.publish_draft(dataset.id)
    exported = source.export_version(dataset.id, published.version, "json")

    target = DatasetManagement(SQLiteRepository(tmp_path / "target.db"))
    imported_dataset, imported_version = target.import_json(exported.content)
    assert imported_dataset == dataset
    assert imported_version.content_sha256 == published.content_sha256
    assert imported_version.cases[0].turns[0].input["message"] == "hello"


def test_xlsx_import_creates_editable_dataset_draft(tmp_path):
    service = DatasetManagement(SQLiteRepository(tmp_path / "xlsx.db"))
    content = dump_xlsx(
        [
            {
                "id": "case",
                "name": "Imported Case",
                "turns": [
                    {
                        "id": "turn",
                        "input": {"message": "hello"},
                        "expectations": [],
                    }
                ],
            }
        ]
    )

    dataset, draft = service.import_xlsx(content, "Imported", "from Excel")

    assert dataset.description == "from Excel"
    assert draft.dataset_id == dataset.id
    assert draft.cases[0].name == "Imported Case"
    assert service.get_draft(dataset.id) == draft
