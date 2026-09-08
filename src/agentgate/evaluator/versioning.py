"""Pure transformations for Evaluator drafts and published specifications."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from agentgate.domain import (
    CombinationPolicy,
    Evaluator,
    EvaluatorDraft,
    EvaluatorKind,
    EvaluatorRef,
    EvaluatorSeverity,
    EvaluatorSource,
    EvaluatorSpec,
    normalize_utc,
)


def _require_user_evaluator(evaluator: Evaluator) -> None:
    if evaluator.source != EvaluatorSource.USER:
        raise ValueError("Evaluator draft operation requires a user Evaluator")


def create_evaluator_draft(
    evaluator: Evaluator,
    draft_id: str,
    created_at: datetime,
    *,
    kind: EvaluatorKind,
    dimension: str,
    metric: str,
    severity: EvaluatorSeverity,
    implementation_id: str,
    implementation_version: str,
    config: Mapping[str, Any],
    children: Sequence[EvaluatorRef],
    combination: CombinationPolicy | None,
) -> EvaluatorDraft:
    """Create a complete draft without a base publication."""

    _require_user_evaluator(evaluator)
    created = normalize_utc(created_at, "EvaluatorDraft created_at")
    if created < evaluator.created_at:
        raise ValueError("draft creation cannot precede Evaluator creation")
    return EvaluatorDraft(
        id=draft_id,
        evaluator_id=evaluator.id,
        kind=kind,
        dimension=dimension,
        metric=metric,
        severity=severity,
        implementation_id=implementation_id,
        implementation_version=implementation_version,
        config=config,
        children=tuple(children),
        combination=combination,
        created_at=created,
        updated_at=created,
    )


def clone_evaluator_version_to_draft(
    evaluator: Evaluator,
    base_spec: EvaluatorSpec,
    draft_id: str,
    created_at: datetime,
) -> EvaluatorDraft:
    """Create a draft from one exact publication belonging to the Evaluator."""

    _require_user_evaluator(evaluator)
    if base_spec.id != evaluator.id:
        raise ValueError("Evaluator draft base belongs to another Evaluator")
    return create_evaluator_draft(
        evaluator,
        draft_id,
        created_at,
        kind=base_spec.kind,
        dimension=base_spec.dimension,
        metric=base_spec.metric,
        severity=base_spec.severity,
        implementation_id=base_spec.implementation_id,
        implementation_version=base_spec.implementation_version,
        config=base_spec.config,
        children=base_spec.children,
        combination=base_spec.combination,
    ).model_copy(update={"based_on_version": base_spec.version})


def replace_evaluator_draft(
    draft: EvaluatorDraft,
    updated_at: datetime,
    *,
    kind: EvaluatorKind,
    dimension: str,
    metric: str,
    severity: EvaluatorSeverity,
    implementation_id: str,
    implementation_version: str,
    config: Mapping[str, Any],
    children: Sequence[EvaluatorRef],
    combination: CombinationPolicy | None,
) -> EvaluatorDraft:
    """Replace the complete editable body while preserving draft identity."""

    updated = normalize_utc(updated_at, "EvaluatorDraft updated_at")
    if updated < draft.updated_at:
        raise ValueError("updated_at must not precede the current draft update")
    return EvaluatorDraft(
        id=draft.id,
        evaluator_id=draft.evaluator_id,
        based_on_version=draft.based_on_version,
        kind=kind,
        dimension=dimension,
        metric=metric,
        severity=severity,
        implementation_id=implementation_id,
        implementation_version=implementation_version,
        config=config,
        children=tuple(children),
        combination=combination,
        created_at=draft.created_at,
        updated_at=updated,
    )


def publish_evaluator_draft(
    evaluator: Evaluator,
    draft: EvaluatorDraft,
    version: int,
) -> EvaluatorSpec:
    """Build one immutable numbered specification from the current draft."""

    _require_user_evaluator(evaluator)
    if draft.evaluator_id != evaluator.id:
        raise ValueError("Evaluator draft belongs to another Evaluator")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError("Evaluator version must be a positive integer")
    return EvaluatorSpec(
        id=evaluator.id,
        name=evaluator.name,
        version=str(version),
        kind=draft.kind,
        dimension=draft.dimension,
        metric=draft.metric,
        severity=draft.severity,
        implementation_id=draft.implementation_id,
        implementation_version=draft.implementation_version,
        config=draft.config,
        children=draft.children,
        combination=draft.combination,
    )
