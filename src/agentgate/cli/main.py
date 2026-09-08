"""AgentGate command-line application composition root."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer

from agentgate.application import (
    DatasetManagement,
    ResultReader,
    RunManagement,
    TargetCatalog,
)
from agentgate.application.evaluator_management import DEFAULT_EVALUATOR_MANAGEMENT
from agentgate.demo.bootstrap import (
    ensure_demo_dataset,
    ensure_demo_target_descriptors,
)
from agentgate.storage.sqlite import SQLiteRepository

from . import dataset_commands, result_commands, run_commands


@dataclass(frozen=True, slots=True)
class CliDependencies:
    """Application boundaries shared by all commands in one CLI invocation."""

    datasets: DatasetManagement
    runs: RunManagement
    results: ResultReader


app = typer.Typer(help="AgentGate 评估工具", no_args_is_help=True)


@app.callback()
def configure(
    context: typer.Context,
    database: Path | None = typer.Option(
        None,
        "--database",
        envvar="AGENTGATE_DB",
        help="SQLite 数据库路径",
    ),
) -> None:
    """配置 AgentGate 命令所使用的共享应用服务。"""

    repository = SQLiteRepository(database or Path("agentgate.db"))
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))
    context.obj = CliDependencies(
        datasets=DatasetManagement(repository),
        runs=RunManagement(repository, DEFAULT_EVALUATOR_MANAGEMENT),
        results=ResultReader(repository),
    )


app.add_typer(dataset_commands.app, name="dataset")
app.add_typer(run_commands.app, name="run")
app.add_typer(result_commands.app, name="result")


if __name__ == "__main__":
    app()


__all__ = ["app"]
