from __future__ import annotations

import json
from types import SimpleNamespace

import typer
from typer.testing import CliRunner

from agentgate.application import DatasetManagement
from agentgate.cli.dataset_commands import app as dataset_app
from agentgate.demo.loan import LOAN_DATASET, LOAN_DATASET_VERSION
from agentgate.storage.sqlite import SQLiteRepository


def cli_for(management: DatasetManagement) -> typer.Typer:
    app = typer.Typer()

    @app.callback()
    def configure(context: typer.Context) -> None:
        context.obj = SimpleNamespace(datasets=management)

    app.add_typer(dataset_app, name="dataset")
    return app


def source_exports(tmp_path):
    repository = SQLiteRepository(tmp_path / "source.db")
    repository.save_dataset_with_version(LOAN_DATASET, LOAN_DATASET_VERSION)
    management = DatasetManagement(repository)
    return (
        management.export_version(LOAN_DATASET.id, 1, "json"),
        management.export_version(LOAN_DATASET.id, 1, "xlsx"),
    )


def test_dataset_list_and_show_use_application_workflows(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "catalog.db")
    repository.save_dataset_with_version(LOAN_DATASET, LOAN_DATASET_VERSION)
    management = DatasetManagement(repository)
    archived = management.create_dataset("已归档")
    management.archive_dataset(archived.id)
    app = cli_for(management)

    visible = CliRunner().invoke(app, ["dataset", "list"])
    all_items = CliRunner().invoke(
        app, ["dataset", "list", "--include-archived"]
    )
    shown = CliRunner().invoke(
        app, ["dataset", "show", LOAN_DATASET.id, "--version", "1"]
    )

    assert visible.exit_code == 0, visible.output
    assert [item["id"] for item in json.loads(visible.output)] == [LOAN_DATASET.id]
    assert all_items.exit_code == 0, all_items.output
    assert {item["id"] for item in json.loads(all_items.output)} == {
        LOAN_DATASET.id,
        archived.id,
    }
    assert shown.exit_code == 0, shown.output
    payload = json.loads(shown.output)
    assert payload["dataset"]["id"] == LOAN_DATASET.id
    assert [item["version"] for item in payload["versions"]] == [1]


def test_dataset_imports_json_and_xlsx_then_publishes_draft(tmp_path) -> None:
    json_export, xlsx_export = source_exports(tmp_path)
    json_path = tmp_path / "dataset.json"
    xlsx_path = tmp_path / "dataset.xlsx"
    json_path.write_bytes(json_export.content)
    xlsx_path.write_bytes(xlsx_export.content)
    management = DatasetManagement(SQLiteRepository(tmp_path / "target.db"))
    app = cli_for(management)

    imported_json = CliRunner().invoke(
        app, ["dataset", "import", str(json_path)]
    )
    missing_name = CliRunner().invoke(
        app, ["dataset", "import", str(xlsx_path)]
    )
    imported_xlsx = CliRunner().invoke(
        app,
        [
            "dataset",
            "import",
            str(xlsx_path),
            "--name",
            "客户工作簿",
            "--description",
            "命令行导入",
        ],
    )

    assert imported_json.exit_code == 0, imported_json.output
    assert json.loads(imported_json.output)["dataset"]["id"] == LOAN_DATASET.id
    assert missing_name.exit_code == 2
    assert "--name" in missing_name.output
    assert imported_xlsx.exit_code == 0, imported_xlsx.output
    xlsx_payload = json.loads(imported_xlsx.output)
    assert xlsx_payload["dataset"]["name"] == "客户工作簿"
    assert xlsx_payload["version"]["version"] is None

    published = CliRunner().invoke(
        app,
        ["dataset", "publish", xlsx_payload["dataset"]["id"]],
    )

    assert published.exit_code == 0, published.output
    assert json.loads(published.output)["version"] == 1


def test_dataset_export_refuses_implicit_overwrite_and_supports_force(tmp_path) -> None:
    json_export, _ = source_exports(tmp_path)
    repository = SQLiteRepository(tmp_path / "export.db")
    repository.save_dataset_with_version(LOAN_DATASET, LOAN_DATASET_VERSION)
    app = cli_for(DatasetManagement(repository))
    output = tmp_path / "out.json"

    exported = CliRunner().invoke(
        app,
        [
            "dataset",
            "export",
            LOAN_DATASET.id,
            "1",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )
    refused = CliRunner().invoke(
        app,
        [
            "dataset",
            "export",
            LOAN_DATASET.id,
            "1",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )
    forced = CliRunner().invoke(
        app,
        [
            "dataset",
            "export",
            LOAN_DATASET.id,
            "1",
            "--format",
            "json",
            "--output",
            str(output),
            "--force",
        ],
    )

    assert exported.exit_code == 0, exported.output
    assert output.read_bytes() == json_export.content
    assert json.loads(exported.output)["bytes"] == len(json_export.content)
    assert refused.exit_code == 2
    assert "已存在" in refused.output
    assert forced.exit_code == 0, forced.output


def test_dataset_commands_report_unknown_format_and_malformed_input(tmp_path) -> None:
    management = DatasetManagement(SQLiteRepository(tmp_path / "errors.db"))
    app = cli_for(management)
    malformed = tmp_path / "bad.json"
    malformed.write_text("{", encoding="utf-8")

    unknown = CliRunner().invoke(
        app, ["dataset", "show", "missing"]
    )
    invalid_format = CliRunner().invoke(
        app,
        ["dataset", "import", str(malformed), "--format", "csv"],
    )
    invalid_json = CliRunner().invoke(
        app, ["dataset", "import", str(malformed)]
    )

    assert unknown.exit_code == 2
    assert "unknown Dataset" in unknown.output
    assert invalid_format.exit_code == 2
    assert "json" in invalid_format.output
    assert "xlsx" in invalid_format.output
    assert invalid_json.exit_code == 2
    assert "Expecting property name" in invalid_json.output
