from __future__ import annotations

import json
from types import SimpleNamespace

import typer
from typer.testing import CliRunner

from agentgate.application import ResultReader, RunManagement, TargetCatalog
from agentgate.application.evaluator_management import (
    build_default_evaluator_management,
)
from agentgate.cli import result_commands, run_commands
from agentgate.demo.bootstrap import (
    ensure_demo_dataset,
    ensure_demo_target_descriptors,
)
from agentgate.domain import FrozenJsonObject
from agentgate.storage.sqlite import SQLiteRepository


def cli_for(repository: SQLiteRepository):
    ensure_demo_target_descriptors(TargetCatalog(repository))
    runs = RunManagement(
        repository,
        build_default_evaluator_management(repository),
    )
    results = ResultReader(repository)
    app = typer.Typer()

    @app.callback()
    def configure(context: typer.Context) -> None:
        context.obj = SimpleNamespace(runs=runs, results=results)

    app.add_typer(run_commands.app, name="run")
    app.add_typer(result_commands.app, name="result")
    return app, runs


def evaluate(app: typer.Typer, version: str) -> str:
    result = CliRunner().invoke(
        app,
        ["run", "evaluate", "--version", version],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["run_id"]


def test_result_show_returns_the_complete_report(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "show.db")
    ensure_demo_dataset(repository)
    app, _ = cli_for(repository)
    run_id = evaluate(app, "loan-agent-v2-fixed")

    result = CliRunner().invoke(app, ["result", "show", run_id])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run"]["id"] == run_id
    assert payload["results"]
    assert payload["metrics"]
    assert payload["release_gate"]["outcome"] == "pass"


def test_result_badcases_groups_only_actionable_primary_results(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "badcases.db")
    ensure_demo_dataset(repository)
    app, _ = cli_for(repository)
    run_id = evaluate(app, "loan-agent-v1-risky")

    result = CliRunner().invoke(app, ["result", "badcases", run_id])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["run_id"] == run_id
    assert payload["badcases"]
    assert payload["missing_results"] == []
    outcomes = {
        evaluation["outcome"]
        for badcase in payload["badcases"]
        for evaluation in badcase["results"]
    }
    assert outcomes <= {"fail", "review", "error"}
    assert "fail" in outcomes


def test_result_trace_returns_only_the_protected_view(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "trace.db")
    ensure_demo_dataset(repository)
    app, _ = cli_for(repository)
    run_id = evaluate(app, "loan-agent-v2-fixed")
    stored = repository.get_trace(run_id, "high-risk-approval")
    assert stored is not None
    repository.save_trace(
        stored.model_copy(
            update={
                "final_state": FrozenJsonObject(
                    {"status": "human_review", "api_key": "raw-secret"}
                )
            }
        )
    )

    result = CliRunner().invoke(
        app,
        ["result", "trace", run_id, "high-risk-approval"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["final_state"]["api_key"] == "[redacted]"
    assert "raw-secret" not in result.output
    raw = repository.get_trace(run_id, "high-risk-approval")
    assert raw is not None
    assert raw.final_state["api_key"] == "raw-secret"


def test_result_gate_maps_pass_and_fail_to_ci_exit_codes(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "gate.db")
    ensure_demo_dataset(repository)
    app, _ = cli_for(repository)
    passing_id = evaluate(app, "loan-agent-v2-fixed")
    failing_id = evaluate(app, "loan-agent-v1-risky")

    passing = CliRunner().invoke(app, ["result", "gate", passing_id])
    failing = CliRunner().invoke(app, ["result", "gate", failing_id])

    assert passing.exit_code == 0, passing.output
    assert json.loads(passing.output)["outcome"] == "pass"
    assert failing.exit_code == 1, failing.output
    assert json.loads(failing.output)["outcome"] == "fail"


def test_result_commands_reject_unknown_and_incomplete_runs(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "errors.db")
    ensure_demo_dataset(repository)
    app, runs = cli_for(repository)
    fixed_id = evaluate(app, "loan-agent-v2-fixed")
    fixed = repository.get_run(fixed_id)
    assert fixed is not None
    pending = runs.create_run(
        fixed.manifest.target,
        dataset_id=fixed.manifest.dataset.dataset_id,
    )

    unknown = CliRunner().invoke(app, ["result", "show", "missing"])
    incomplete = CliRunner().invoke(app, ["result", "gate", pending.id])
    missing_trace = CliRunner().invoke(
        app,
        ["result", "trace", fixed_id, "missing"],
    )

    assert unknown.exit_code == 2
    assert "unknown EvaluationRun" in unknown.output
    assert incomplete.exit_code == 2
    assert "completed EvaluationRun" in incomplete.output
    assert missing_trace.exit_code == 2
    assert "unknown Trace" in missing_trace.output
