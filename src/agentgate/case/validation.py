"""Whole-Dataset validation performed before a draft is published."""

from __future__ import annotations

from agentgate.domain import (
    DatasetVersion, DomainModel, MatchesJsonSchema, ToolArgumentExpectation,
)


class ValidationIssue(DomainModel):
    path: str
    message: str


class DatasetValidationError(ValueError):
    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{item.path}: {item.message}" for item in issues))


def validate_dataset_version(version: DatasetVersion) -> None:
    issues: list[ValidationIssue] = []
    if not version.cases:
        issues.append(ValidationIssue(path="cases", message="测评集至少需要一个用例"))

    case_ids: set[str] = set()
    for case_index, case in enumerate(version.cases):
        base = f"cases[{case_index}]"
        if not case.id.strip():
            issues.append(ValidationIssue(path=f"{base}.id", message="用例 ID 不能为空"))
        if case.id in case_ids:
            issues.append(ValidationIssue(path=f"{base}.id", message="用例 ID 必须唯一"))
        case_ids.add(case.id)
        if not case.name.strip():
            issues.append(ValidationIssue(path=f"{base}.name", message="用例名称不能为空"))

        turn_ids: set[str] = set()
        expectation_ids: set[str] = set()
        for turn_index, turn in enumerate(case.turns):
            turn_base = f"{base}.turns[{turn_index}]"
            if not turn.id.strip():
                issues.append(ValidationIssue(
                    path=f"{turn_base}.id", message="轮次 ID 不能为空"
                ))
            if turn.id in turn_ids:
                issues.append(ValidationIssue(
                    path=f"{turn_base}.id", message="同一用例内轮次 ID 必须唯一"
                ))
            turn_ids.add(turn.id)
            if not turn.input:
                issues.append(ValidationIssue(
                    path=f"{turn_base}.input", message="每一轮必须包含输入"
                ))
            for expectation_index, expectation in enumerate(turn.expectations):
                exp_base = f"{turn_base}.expectations[{expectation_index}]"
                if expectation.id in expectation_ids:
                    issues.append(ValidationIssue(
                        path=f"{exp_base}.id", message="同一用例内期望 ID 必须唯一"
                    ))
                expectation_ids.add(expectation.id)
                if isinstance(expectation, ToolArgumentExpectation):
                    if not expectation.tool.strip() or not expectation.path.strip():
                        issues.append(ValidationIssue(
                            path=exp_base, message="工具参数期望需要工具名和参数路径"
                        ))
                elif expectation.kind == "state" and not str(expectation.path).strip():
                    issues.append(ValidationIssue(
                        path=exp_base, message="最终状态期望需要字段路径"
                    ))
                condition = getattr(expectation, "condition", None)
                if isinstance(condition, MatchesJsonSchema):
                    issues.append(ValidationIssue(
                        path=f"{exp_base}.condition",
                        message="JSON Schema 检查尚未实现，不能发布该用例",
                    ))

    if issues:
        raise DatasetValidationError(tuple(issues))
