from __future__ import annotations

import json
from types import SimpleNamespace

import typer
from typer.testing import CliRunner

from agentgate.application import ResultReader, RunManagement
from agentgate.application.evaluator_management import DEFAULT_EVALUATOR_MANAGEMENT
from agentgate.cli import run_commands
from agentgate.demo.bootstrap import ensure_demo_dataset
from agentgate.demo.loan import LOAN_DATASET
from agentgate.storage.sqlite import SQLiteRepository


def cli_for(repository: SQLiteRepository, runs: RunManagement | None = None):
    management = runs or RunManagement(repository, DEFAULT_EVALUATOR_MANAGEMENT)
    reader = ResultReader(repository)
    app = typer.Typer()

    @app.callback()
    def configure(context: typer.Context) -> None:
        context.obj = SimpleNamespace(runs=management, results=reader)

    app.add_typer(run_commands.app, name="run")
    return app, management, reader


def test_run_evaluate_executes_fixed_and_risky_versions(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "evaluate.db")
    ensure_demo_dataset(repository)
    app, _, reader = cli_for(repository)

    fixed = CliRunner().invoke(
        app,
        [
            "run",
            "evaluate",
            "--version",
            "loan-agent-v2-fixed",
            "--dataset-version",
            "1",
            "--evaluator",
            "skill-routing",
            "--evaluator",
            "final-state",
        ],
    )
    risky = CliRunner().invoke(
        app,
        ["run", "evaluate", "--version", "loan-agent-v1-risky"],
    )

    assert fixed.exit_code == 0, fixed.output
    fixed_payload = json.loads(fixed.output)
    assert fixed_payload["status"] == "completed"
    assert fixed_payload["release_gate"]["outcome"] == "pass"
    fixed_run = next(
        run for run in reader.list_runs() if run.id == fixed_payload["run_id"]
    )
    assert fixed_run.manifest.dataset.dataset_id == LOAN_DATASET.id
    assert fixed_run.manifest.dataset.version == 1
    assert [spec.id for spec in fixed_run.manifest.evaluator_specs] == [
        "skill-routing",
        "final-state",
    ]

    assert risky.exit_code == 0, risky.output
    risky_payload = json.loads(risky.output)
    assert risky_payload["status"] == "completed"
    assert risky_payload["release_gate"]["outcome"] == "fail"


def test_run_list_status_and_activity_use_read_projections(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "reads.db")
    ensure_demo_dataset(repository)
    app, _, _ = cli_for(repository)
    evaluated = CliRunner().invoke(app, ["run", "evaluate"])
    run_id = json.loads(evaluated.output)["run_id"]

    listed = CliRunner().invoke(
        app, ["run", "list", "--status", "completed", "--limit", "1"]
    )
    status = CliRunner().invoke(app, ["run", "status", run_id])
    activity = CliRunner().invoke(
        app, ["run", "activity", "--recent-limit", "1"]
    )

    assert listed.exit_code == 0, listed.output
    assert [item["id"] for item in json.loads(listed.output)] == [run_id]
    assert status.exit_code == 0, status.output
    status_payload = json.loads(status.output)
    assert status_payload["run_id"] == run_id
    assert status_payload["status"] == "completed"
    assert status_payload["progress"] == 1
    assert activity.exit_code == 0, activity.output
    activity_payload = json.loads(activity.output)
    assert activity_payload["status_counts"]["completed"] == 1
    assert [item["run_id"] for item in activity_payload["recent"]] == [run_id]


def test_run_commands_reject_unknown_target_and_run(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "errors.db")
    ensure_demo_dataset(repository)
    app, _, _ = cli_for(repository)

    unknown_target = CliRunner().invoke(
        app, ["run", "evaluate", "--version", "missing"]
    )
    unknown_run = CliRunner().invoke(app, ["run", "status", "missing"])

    assert unknown_target.exit_code == 2
    assert "unknown demo Target version" in unknown_target.output
    assert unknown_run.exit_code == 2
    assert "unknown EvaluationRun" in unknown_run.output


def test_run_evaluate_sanitizes_failures_and_shuts_down_capture(
    tmp_path, monkeypatch
) -> None:
    repository = SQLiteRepository(tmp_path / "failure.db")
    ensure_demo_dataset(repository)
    app, _, reader = cli_for(repository)

    class RecordingCapture:
        shutdown_called = False

        def resolve(self, request, result):
            raise AssertionError("resolve must not be called")

        def shutdown(self) -> None:
            type(self).shutdown_called = True

    class FailingAdapter:
        adapter_type = "demo_loan"
        adapter_version = "1"

        def __init__(self, capture) -> None:
            self.capture = capture

        def start(self, request) -> str:
            raise RuntimeError("token=raw-secret")

        def get_status(self, handle):
            raise AssertionError("status must not be read")

        def wait(self, handle, timeout_seconds):
            raise AssertionError("wait must not be called")

        def cancel(self, handle) -> None:
            raise AssertionError("cancel must not be called")

    monkeypatch.setattr(run_commands, "InMemoryTraceCapture", RecordingCapture)
    monkeypatch.setattr(run_commands, "DemoLoanTargetAdapter", FailingAdapter)

    result = CliRunner().invoke(app, ["run", "evaluate"])

    assert result.exit_code == 1
    assert "RuntimeError" in result.output
    assert "raw-secret" not in result.output
    assert RecordingCapture.shutdown_called is True
    failed = reader.list_runs()[0]
    assert failed.status.value == "failed"
    assert "raw-secret" not in (failed.error or "")
