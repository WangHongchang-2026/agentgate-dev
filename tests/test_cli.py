import json

from typer.testing import CliRunner

from agentgate.cli.application import app


def test_cli_runs_demo(tmp_path):
    database = tmp_path / "cli.db"
    result = CliRunner().invoke(app, ["evaluate", "--version", "loan-agent-v2-fixed", "--database", str(database)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "completed"
    assert payload["release_gate"]["outcome"] == "pass"
