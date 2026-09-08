"""Run commands backed by application workflows and Target integrations."""

from __future__ import annotations

import json
from typing import Any, NoReturn

import typer

from agentgate.application import ResultReader, RunManagement
from agentgate.demo.loan import LOAN_DATASET, LoanAgent
from agentgate.domain import (
    RunStatus,
    TargetRef,
    TargetSnapshot,
    TargetType,
    content_sha256,
)
from agentgate.integrations.observability import InMemoryTraceCapture
from agentgate.integrations.targets import DemoLoanTargetAdapter


app = typer.Typer(help="运行和查看评估任务", no_args_is_help=True)


def _run_management(context: typer.Context) -> RunManagement:
    management = getattr(context.obj, "runs", None)
    if not isinstance(management, RunManagement):
        raise RuntimeError("CLI Run dependencies are not configured")
    return management


def _result_reader(context: typer.Context) -> ResultReader:
    reader = getattr(context.obj, "results", None)
    if not isinstance(reader, ResultReader):
        raise RuntimeError("CLI Result dependencies are not configured")
    return reader


def _demo_target(version: str) -> TargetSnapshot:
    if version not in LoanAgent.versions:
        raise ValueError(f"unknown demo Target version: {version}")
    return TargetSnapshot(
        ref=TargetRef(
            source_id="agentgate-demo",
            target_type=TargetType.AGENT,
            external_target_id="loan-agent",
            external_version_id=version,
        ),
        display_name="Loan Agent",
        adapter_type=DemoLoanTargetAdapter.adapter_type,
        adapter_version=DemoLoanTargetAdapter.adapter_version,
        descriptor_sha256=content_sha256(
            {
                "name": "loan-agent",
                "versions": LoanAgent.versions,
            }
        ),
        invocation_config={"provider": "deterministic"},
    )


def _emit_json(value: Any) -> None:
    typer.echo(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _fail_validation(error: Exception) -> NoReturn:
    raise typer.BadParameter(str(error)) from error


def _fail_execution(error: Exception) -> NoReturn:
    typer.echo(f"运行失败：{type(error).__name__}", err=True)
    raise typer.Exit(code=1) from error


@app.command("evaluate")
def evaluate(
    context: typer.Context,
    version: str = typer.Option("loan-agent-v2-fixed", help="目标代理版本"),
    dataset_id: str = typer.Option(LOAN_DATASET.id, help="数据集 ID"),
    dataset_version: int | None = typer.Option(None, min=1, help="数据集版本"),
    evaluator_ids: list[str] | None = typer.Option(
        None,
        "--evaluator",
        help="评估器 ID，可重复指定",
    ),
    timeout_seconds: float = typer.Option(300, min=0.001, help="单案例超时秒数"),
) -> None:
    """同步运行一次演示评估。"""

    management = _run_management(context)
    reader = _result_reader(context)
    try:
        target = _demo_target(version)
        run = management.create_run(
            target,
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            evaluator_ids=evaluator_ids,
            timeout_seconds=timeout_seconds,
        )
    except ValueError as error:
        _fail_validation(error)

    try:
        capture = InMemoryTraceCapture()
        try:
            completed = management.execute_run(
                run.id,
                DemoLoanTargetAdapter(capture),
                capture.resolve,
            )
        finally:
            capture.shutdown()
        report = reader.get_report(completed.id)
    except Exception as error:
        _fail_execution(error)

    _emit_json(
        {
            "release_gate": report.release_gate.model_dump(mode="json"),
            "run_id": completed.id,
            "status": completed.status,
        }
    )


@app.command("list")
def list_runs(
    context: typer.Context,
    status: RunStatus | None = typer.Option(None, help="运行状态"),
    limit: int = typer.Option(50, min=1, max=200, help="最大返回数量"),
) -> None:
    """列出评估任务。"""

    runs = _result_reader(context).list_runs(limit=limit, status=status)
    _emit_json([run.model_dump(mode="json") for run in runs])


@app.command("status")
def run_status(
    context: typer.Context,
    run_id: str = typer.Argument(..., help="运行 ID"),
) -> None:
    """查看一个任务的状态和进度。"""

    try:
        _run_management(context).fail_stale_runs()
        progress = _result_reader(context).get_run_progress(run_id)
    except (LookupError, ValueError) as error:
        _fail_validation(error)
    _emit_json(progress.model_dump(mode="json"))


@app.command("activity")
def run_activity(
    context: typer.Context,
    recent_limit: int = typer.Option(20, min=1, max=100, help="最近任务数量"),
) -> None:
    """查看队列、运行中和最近完成的任务。"""

    try:
        management = _run_management(context)
        management.fail_stale_runs()
        activity = _result_reader(context).activity(recent_limit=recent_limit)
    except ValueError as error:
        _fail_validation(error)
    _emit_json(activity.model_dump(mode="json"))


__all__ = ["app"]
