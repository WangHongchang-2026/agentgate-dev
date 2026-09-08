"""Result commands backed by the read-only Result application boundary."""

from __future__ import annotations

import json
from typing import Any, NoReturn

import typer

from agentgate.application import ResultReader
from agentgate.domain import Outcome


app = typer.Typer(help="查看评估结果和证据", no_args_is_help=True)
_BADCASE_OUTCOMES = frozenset({Outcome.FAIL, Outcome.REVIEW, Outcome.ERROR})


def _result_reader(context: typer.Context) -> ResultReader:
    reader = getattr(context.obj, "results", None)
    if not isinstance(reader, ResultReader):
        raise RuntimeError("CLI Result dependencies are not configured")
    return reader


def _emit_json(value: Any) -> None:
    typer.echo(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def _fail(error: Exception) -> NoReturn:
    raise typer.BadParameter(str(error)) from error


@app.command("show")
def show_result(
    context: typer.Context,
    run_id: str = typer.Argument(..., help="运行 ID"),
) -> None:
    """查看完整评估报告。"""

    try:
        report = _result_reader(context).get_report(run_id)
    except (LookupError, ValueError) as error:
        _fail(error)
    _emit_json(report.model_dump(mode="json"))


@app.command("badcases")
def list_badcases(
    context: typer.Context,
    run_id: str = typer.Argument(..., help="运行 ID"),
) -> None:
    """查看需要处理的失败、复核和错误案例。"""

    try:
        report = _result_reader(context).get_report(run_id)
    except (LookupError, ValueError) as error:
        _fail(error)

    primary_ids = set(report.run.manifest.primary_evaluator_ids)
    results_by_case: dict[str, list[dict[str, Any]]] = {}
    for result in report.results:
        if result.evaluator_id in primary_ids and result.outcome in _BADCASE_OUTCOMES:
            results_by_case.setdefault(result.case_id, []).append(
                result.model_dump(mode="json")
            )
    badcases = [
        {
            "case": case.model_dump(mode="json"),
            "results": results_by_case[case.id],
        }
        for case in report.run.manifest.dataset.cases
        if case.id in results_by_case
    ]
    _emit_json(
        {
            "badcases": badcases,
            "missing_results": report.release_gate.missing_results,
            "run_id": report.run.id,
        }
    )


@app.command("trace")
def show_trace(
    context: typer.Context,
    run_id: str = typer.Argument(..., help="运行 ID"),
    case_id: str = typer.Argument(..., help="案例 ID"),
) -> None:
    """查看一个案例的受保护追踪。"""

    try:
        trace = _result_reader(context).get_trace(run_id, case_id)
    except (LookupError, ValueError) as error:
        _fail(error)
    _emit_json(trace.model_dump(mode="json"))


@app.command("gate")
def check_gate(
    context: typer.Context,
    run_id: str = typer.Argument(..., help="运行 ID"),
) -> None:
    """读取发布门结论，并将通过或失败映射为 CI 退出码。"""

    try:
        decision = _result_reader(context).get_report(run_id).release_gate
    except (LookupError, ValueError) as error:
        _fail(error)
    _emit_json(decision.model_dump(mode="json"))
    if decision.outcome is Outcome.FAIL:
        raise typer.Exit(code=1)


__all__ = ["app"]
