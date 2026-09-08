import json

from typer.testing import CliRunner

from agentgate.cli.main import app


def test_cli_runs_demo(tmp_path):
    database = tmp_path / "cli.db"
    result = CliRunner().invoke(
        app,
        [
            "--database",
            str(database),
            "run",
            "evaluate",
            "--version",
            "loan-agent-v2-fixed",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "completed"
    assert payload["release_gate"]["outcome"] == "pass"

    report = CliRunner().invoke(
        app,
        ["--database", str(database), "result", "show", payload["run_id"]],
    )
    assert report.exit_code == 0, report.output
    assert json.loads(report.output)["run"]["id"] == payload["run_id"]


def test_cli_uses_database_environment_variable(tmp_path, monkeypatch):
    database = tmp_path / "environment.db"
    monkeypatch.setenv("AGENTGATE_DB", str(database))

    result = CliRunner().invoke(app, ["dataset", "list"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)[0]["id"] == "loan-risk-policy"
    assert database.exists()
