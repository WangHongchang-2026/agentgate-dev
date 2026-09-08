"""Dataset commands backed by the Dataset application boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

import typer

from agentgate.application import DatasetManagement


app = typer.Typer(help="管理评估数据集", no_args_is_help=True)
_SUPPORTED_FORMATS = frozenset({"json", "xlsx"})


def _management(context: typer.Context) -> DatasetManagement:
    management = getattr(context.obj, "datasets", None)
    if not isinstance(management, DatasetManagement):
        raise RuntimeError("CLI Dataset dependencies are not configured")
    return management


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


def _resolve_format(source: Path, requested: str | None) -> str:
    format_name = (
        requested.lower().lstrip(".")
        if requested
        else source.suffix.lower().lstrip(".")
    )
    if format_name not in _SUPPORTED_FORMATS:
        raise ValueError("格式必须是 json 或 xlsx")
    return format_name


@app.command("list")
def list_datasets(
    context: typer.Context,
    include_archived: bool = typer.Option(False, help="包含已归档数据集"),
) -> None:
    """列出数据集。"""

    datasets = _management(context).list_datasets(include_archived=include_archived)
    _emit_json([dataset.model_dump(mode="json") for dataset in datasets])


@app.command("show")
def show_dataset(
    context: typer.Context,
    dataset_id: str = typer.Argument(..., help="数据集 ID"),
    version: int | None = typer.Option(None, min=1, help="已发布版本号"),
) -> None:
    """查看数据集及其版本。"""

    management = _management(context)
    try:
        dataset = management.get_dataset(dataset_id)
        versions = (
            [management.get_version(dataset_id, version)]
            if version is not None
            else management.list_versions(dataset_id)
        )
    except ValueError as error:
        _fail(error)
    _emit_json(
        {
            "dataset": dataset.model_dump(mode="json"),
            "versions": [item.model_dump(mode="json") for item in versions],
        }
    )


@app.command("import")
def import_dataset(
    context: typer.Context,
    source: Path = typer.Argument(..., help="JSON 或 XLSX 文件"),
    format_name: str | None = typer.Option(None, "--format", help="json 或 xlsx"),
    name: str | None = typer.Option(None, help="XLSX 数据集名称"),
    description: str = typer.Option("", help="XLSX 数据集描述"),
) -> None:
    """导入 JSON 或 XLSX 数据集。"""

    try:
        resolved_format = _resolve_format(source, format_name)
        content = source.read_bytes()
        management = _management(context)
        if resolved_format == "json":
            dataset, version = management.import_json(content)
        else:
            if name is None or not name.strip():
                raise ValueError("导入 XLSX 时必须提供 --name")
            dataset, version = management.import_xlsx(
                content,
                name=name,
                description=description,
            )
    except (OSError, ValueError) as error:
        _fail(error)
    _emit_json(
        {
            "dataset": dataset.model_dump(mode="json"),
            "version": version.model_dump(mode="json"),
        }
    )


@app.command("export")
def export_dataset(
    context: typer.Context,
    dataset_id: str = typer.Argument(..., help="数据集 ID"),
    version: int = typer.Argument(..., min=1, help="已发布版本号"),
    format_name: str = typer.Option(..., "--format", help="json 或 xlsx"),
    output: Path = typer.Option(..., "--output", help="输出文件路径"),
    force: bool = typer.Option(False, help="覆盖已存在的输出文件"),
) -> None:
    """导出一个已发布的数据集版本。"""

    try:
        resolved_format = _resolve_format(output, format_name)
        exported = _management(context).export_version(
            dataset_id,
            version,
            resolved_format,
        )
        mode = "wb" if force else "xb"
        with output.open(mode) as destination:
            destination.write(exported.content)
    except FileExistsError:
        _fail(ValueError(f"输出文件已存在：{output}"))
    except (OSError, ValueError) as error:
        _fail(error)
    _emit_json(
        {
            "bytes": len(exported.content),
            "filename": exported.filename,
            "media_type": exported.media_type,
            "path": str(output),
        }
    )


@app.command("publish")
def publish_dataset(
    context: typer.Context,
    dataset_id: str = typer.Argument(..., help="数据集 ID"),
) -> None:
    """发布数据集当前草稿。"""

    try:
        version = _management(context).publish_draft(dataset_id)
    except ValueError as error:
        _fail(error)
    _emit_json(version.model_dump(mode="json"))


__all__ = ["app"]
