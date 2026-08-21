from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from agentgate.control_plane import EvaluationService
from agentgate.storage.sqlite import SQLiteRepository

app = typer.Typer(help="AgentGate 演示评估工具", no_args_is_help=True)


def _service(database: Path | None = None) -> EvaluationService:
    return EvaluationService(SQLiteRepository(database or os.getenv("AGENTGATE_DB", "agentgate.db")))


@app.command()
def evaluate(version: str = typer.Option("loan-agent-v2-fixed", help="目标代理版本"),
             database: Path | None = typer.Option(None, help="SQLite 数据库路径")) -> None:
    """运行贷款审批演示数据集。"""
    service = _service(database)
    run = service.launch(version)
    report = service.run_detail(run.id)
    typer.echo(json.dumps({
        "run_id": run.id,
        "status": run.status,
        "gate": report.gate.model_dump(mode="json"),
    }, ensure_ascii=False))


@app.command("runs")
def list_runs(database: Path | None = typer.Option(None, help="SQLite 数据库路径")) -> None:
    for run in _service(database).repository.list_runs():
        typer.echo(f"{run.id}\t{run.snapshot.target.version}\t{run.status}")


@app.command()
def show(run_id: str, database: Path | None = typer.Option(None, help="SQLite 数据库路径")) -> None:
    report = _service(database).run_detail(run_id)
    if report is None:
        raise typer.BadParameter("run not found")
    typer.echo(json.dumps({
        "run": report.run.model_dump(mode="json"),
        "results": [item.model_dump(mode="json") for item in report.results],
        "metrics": [item.model_dump(mode="json") for item in report.metrics],
        "gate": report.gate.model_dump(mode="json"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    app()
