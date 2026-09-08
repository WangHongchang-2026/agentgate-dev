"""Application-owned evaluator catalog, composition, and preflight."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from agentgate.domain import (
    Case,
    CombinationPolicy,
    DatasetVersion,
    EvaluationResult,
    Evaluator,
    EvaluatorDraft,
    EvaluatorKind,
    EvaluatorRef,
    EvaluatorSeverity,
    EvaluatorSource,
    EvaluatorSpec,
    MatchesJsonSchema,
    PolicyExpectation,
    Trace,
    utcnow,
)
from agentgate.evaluator.executor import (
    EvaluatorImplementations,
    execute_evaluators,
)
from agentgate.evaluator.judge import AnswerQualityJudge, JudgeModelClient
from agentgate.evaluator.versioning import (
    clone_evaluator_version_to_draft,
    create_evaluator_draft,
    replace_evaluator_draft,
    publish_evaluator_draft as build_evaluator_publication,
)
from agentgate.evaluator.models import (
    DuplicateEvaluatorId,
    EvaluatorKindMismatch,
    EvaluatorVersionMismatch,
    InvalidHybridEvaluator,
    MissingEvaluatorDependency,
    UnknownEvaluator,
)
from agentgate.evaluator.rule import (
    FinalOutputEvaluator,
    FinalStateEvaluator,
    ForbiddenToolEvaluator,
    PolicyComplianceEvaluator,
    RequiredToolEvaluator,
    SkillRoutingEvaluator,
    ToolArgumentsEvaluator,
)
from agentgate.evaluator.rule.json_schema import validate_json_schema
from agentgate.evaluator.rule.operators import resolve_condition_operator
from agentgate.evaluator.rule.policy import validate_policy_id
from agentgate.storage.repository import AgentGateRepository


class EvaluatorNotFound(UnknownEvaluator, ValueError):
    """A catalog Evaluator identity does not exist."""


class EvaluatorDraftNotFound(ValueError):
    """A user Evaluator has no active draft."""


class EvaluatorVersionNotFound(ValueError):
    """An exact published Evaluator version does not exist."""


class EvaluatorCatalogConflict(ValueError):
    """An Evaluator lifecycle transition conflicts with current state."""


class BuiltinEvaluatorMutation(ValueError):
    """A caller attempted to mutate a source-controlled Evaluator."""


class EvaluatorManagement:
    """Coordinate persistent catalog workflows and evaluator execution."""

    __slots__ = (
        "repository",
        "_builtin_evaluators",
        "_builtin_specs",
        "_builtin_specs_by_id",
        "_implementations",
    )

    def __init__(
        self,
        repository: AgentGateRepository,
        builtin_specs: Sequence[EvaluatorSpec],
        implementations: EvaluatorImplementations,
    ) -> None:
        specs = tuple(builtin_specs)
        if not specs:
            raise ValueError("at least one built-in Evaluator is required")
        specs_by_id = {spec.id: spec for spec in specs}
        if len(specs_by_id) != len(specs):
            raise DuplicateEvaluatorId("built-in Evaluator IDs must be unique")

        implementation_copy = dict(implementations)
        if not implementation_copy:
            raise ValueError("at least one Evaluator implementation is required")
        self.repository = repository
        self._builtin_specs = specs
        self._builtin_specs_by_id = MappingProxyType(specs_by_id)
        self._implementations = MappingProxyType(implementation_copy)
        for spec in specs:
            self._validate_supported_spec(spec)
        self._builtin_evaluators = MappingProxyType(
            {
                spec.id: Evaluator(
                    id=spec.id,
                    name=spec.name,
                    source=EvaluatorSource.BUILTIN,
                    enabled=True,
                    created_at=_BUILTIN_DEFINED_AT,
                    updated_at=_BUILTIN_DEFINED_AT,
                )
                for spec in specs
            }
        )

    @property
    def default_specs(self) -> tuple[EvaluatorSpec, ...]:
        return self._builtin_specs

    def list_evaluators(
        self,
        include_disabled: bool = False,
    ) -> tuple[Evaluator, ...]:
        users = self.repository.list_evaluators(include_disabled=include_disabled)
        collisions = set(self._builtin_evaluators).intersection(
            evaluator.id for evaluator in users
        )
        if collisions:
            raise EvaluatorCatalogConflict(
                f"user Evaluator conflicts with built-in: {sorted(collisions)[0]}"
            )
        return (*self._builtin_evaluators.values(), *users)

    def get_evaluator(self, evaluator_id: str) -> Evaluator:
        builtin = self._builtin_evaluators.get(evaluator_id)
        if builtin is not None:
            return builtin
        evaluator = self.repository.get_evaluator(evaluator_id)
        if evaluator is None:
            raise EvaluatorNotFound(f"unknown Evaluator: {evaluator_id}")
        return evaluator

    def create_evaluator(
        self,
        name: str,
        description: str = "",
        *,
        kind: EvaluatorKind,
        dimension: str,
        metric: str,
        severity: EvaluatorSeverity = EvaluatorSeverity.STANDARD,
        implementation_id: str,
        implementation_version: str = "1",
        config: Mapping[str, Any],
        children: Sequence[EvaluatorRef] = (),
        combination: CombinationPolicy | None = None,
    ) -> tuple[Evaluator, EvaluatorDraft]:
        created_at = utcnow()
        evaluator = Evaluator(
            id=str(uuid4()),
            name=name.strip(),
            description=description.strip(),
            created_at=created_at,
            updated_at=created_at,
        )
        draft = create_evaluator_draft(
            evaluator,
            str(uuid4()),
            created_at,
            kind=kind,
            dimension=dimension,
            metric=metric,
            severity=severity,
            implementation_id=implementation_id,
            implementation_version=implementation_version,
            config=config,
            children=children,
            combination=combination,
        )
        self.repository.save_evaluator_with_draft(evaluator, draft)
        return evaluator, draft

    def update_evaluator(
        self,
        evaluator_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
    ) -> Evaluator:
        evaluator = self._user_evaluator(evaluator_id)
        if name is None and description is None and enabled is None:
            raise ValueError("Evaluator update must contain at least one field")
        if enabled and self.repository.get_latest_evaluator_version(evaluator_id) is None:
            raise EvaluatorCatalogConflict(
                "unpublished Evaluator cannot be enabled"
            )
        changes: dict[str, Any] = {"updated_at": utcnow()}
        if name is not None:
            changes["name"] = name.strip()
        if description is not None:
            changes["description"] = description.strip()
        if enabled is not None:
            changes["enabled"] = enabled
        updated = Evaluator.model_validate(
            {**evaluator.model_dump(mode="json"), **changes}
        )
        self.repository.save_evaluator(updated)
        return updated

    def delete_evaluator(self, evaluator_id: str) -> None:
        self._user_evaluator(evaluator_id)
        if self.repository.get_latest_evaluator_version(evaluator_id) is not None:
            raise EvaluatorCatalogConflict(
                "published Evaluator cannot be deleted; disable it instead"
            )
        self.repository.delete_unpublished_evaluator(evaluator_id)

    def get_draft(self, evaluator_id: str) -> EvaluatorDraft:
        self._user_evaluator(evaluator_id)
        draft = self.repository.get_evaluator_draft(evaluator_id)
        if draft is None:
            raise EvaluatorDraftNotFound(
                f"Evaluator has no active draft: {evaluator_id}"
            )
        return draft

    def create_draft(
        self,
        evaluator_id: str,
        based_on_version: str | None = None,
    ) -> EvaluatorDraft:
        evaluator = self._user_evaluator(evaluator_id)
        if self.repository.get_evaluator_draft(evaluator_id) is not None:
            raise EvaluatorCatalogConflict("Evaluator already has an active draft")
        base = (
            self.get_version(evaluator_id, based_on_version)
            if based_on_version is not None
            else self.repository.get_latest_evaluator_version(evaluator_id)
        )
        if base is None:
            raise EvaluatorCatalogConflict(
                "Evaluator without a publication cannot clone a draft"
            )
        draft = clone_evaluator_version_to_draft(
            evaluator,
            base,
            str(uuid4()),
            utcnow(),
        )
        self.repository.save_evaluator_draft(draft)
        return draft

    def replace_draft(
        self,
        evaluator_id: str,
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
        draft = self.get_draft(evaluator_id)
        updated = replace_evaluator_draft(
            draft,
            utcnow(),
            kind=kind,
            dimension=dimension,
            metric=metric,
            severity=severity,
            implementation_id=implementation_id,
            implementation_version=implementation_version,
            config=config,
            children=children,
            combination=combination,
        )
        self.repository.save_evaluator_draft(updated)
        return updated

    def discard_draft(self, evaluator_id: str) -> None:
        draft = self.get_draft(evaluator_id)
        self.repository.delete_evaluator_draft(evaluator_id, draft.id)

    def list_versions(self, evaluator_id: str) -> tuple[EvaluatorSpec, ...]:
        builtin = self._builtin_specs_by_id.get(evaluator_id)
        if builtin is not None:
            return (builtin,)
        self._user_evaluator(evaluator_id)
        return tuple(self.repository.list_evaluator_versions(evaluator_id))

    def get_version(self, evaluator_id: str, version: str) -> EvaluatorSpec:
        builtin = self._builtin_specs_by_id.get(evaluator_id)
        if builtin is not None:
            if builtin.version == version:
                return builtin
            raise EvaluatorVersionNotFound(
                f"unknown Evaluator version: {evaluator_id}@{version}"
            )
        self._user_evaluator(evaluator_id)
        published = self.repository.get_evaluator_version(evaluator_id, version)
        if published is None:
            raise EvaluatorVersionNotFound(
                f"unknown Evaluator version: {evaluator_id}@{version}"
            )
        return published

    def publish_draft(self, evaluator_id: str) -> EvaluatorSpec:
        evaluator = self._user_evaluator(evaluator_id)
        draft = self.get_draft(evaluator_id)
        latest = self.repository.get_latest_evaluator_version(evaluator_id)
        next_version = int(latest.version) + 1 if latest is not None else 1
        published = build_evaluator_publication(
            evaluator,
            draft,
            next_version,
        )
        self._validate_supported_spec(published)
        self._validate_hybrid_children(published, require_enabled=False)
        try:
            self.repository.publish_evaluator_draft(draft.id, published)
        except ValueError as error:
            raise EvaluatorCatalogConflict(
                "Evaluator draft changed during publication"
            ) from error
        return published

    def select(
        self,
        evaluator_ids: Sequence[str] | None,
    ) -> tuple[EvaluatorSpec, ...]:
        if evaluator_ids is None:
            return self._builtin_specs
        requested = tuple(evaluator_ids)
        if not requested:
            raise ValueError("at least one Evaluator is required")
        if len(set(requested)) != len(requested):
            raise DuplicateEvaluatorId("evaluator_ids must be unique")
        selected: dict[str, EvaluatorSpec] = {}
        for evaluator_id in requested:
            self._add_selectable(evaluator_id, selected)
        return tuple(selected.values())

    def validate_plan(
        self,
        dataset: DatasetVersion,
        evaluator_specs: tuple[EvaluatorSpec, ...],
    ) -> None:
        if not evaluator_specs:
            raise ValueError("at least one Evaluator is required")
        specs_by_id = {spec.id: spec for spec in evaluator_specs}
        if len(specs_by_id) != len(evaluator_specs):
            raise DuplicateEvaluatorId("evaluator IDs must be unique")

        metric_dimensions: dict[str, str] = {}
        for spec in evaluator_specs:
            try:
                available = self.get_version(spec.id, spec.version)
            except (EvaluatorNotFound, EvaluatorVersionNotFound) as exc:
                raise UnknownEvaluator(str(exc)) from exc
            if spec.content_sha256 != available.content_sha256:
                raise ValueError(f"Evaluator content mismatch: {spec.id}")
            self._validate_supported_spec(spec)

            previous_dimension = metric_dimensions.setdefault(
                spec.metric,
                spec.dimension,
            )
            if previous_dimension != spec.dimension:
                raise ValueError(
                    f"metric {spec.metric} cannot belong to both "
                    f"{previous_dimension} and {spec.dimension}"
                )

            children = []
            for child in spec.children:
                child_spec = specs_by_id.get(child.evaluator_id)
                if child_spec is None:
                    raise MissingEvaluatorDependency(child.evaluator_id)
                if child.evaluator_version != child_spec.version:
                    raise EvaluatorVersionMismatch(child.evaluator_id)
                children.append(child_spec)
            if spec.kind == EvaluatorKind.HYBRID:
                if any(child.kind == EvaluatorKind.HYBRID for child in children):
                    raise InvalidHybridEvaluator("nested Hybrid is not supported")
                child_kinds = {child.kind for child in children}
                if not {
                    EvaluatorKind.RULE,
                    EvaluatorKind.LLM_JUDGE,
                }.issubset(child_kinds):
                    raise InvalidHybridEvaluator(
                        "Hybrid requires Rule and LLM Judge children"
                    )

        for case in dataset.cases:
            for turn in case.turns:
                for expectation in turn.expectations:
                    condition = getattr(expectation, "condition", None)
                    if condition is not None:
                        if isinstance(condition, MatchesJsonSchema):
                            validate_json_schema(condition.json_schema)
                        resolve_condition_operator(condition)
                    if isinstance(expectation, PolicyExpectation):
                        validate_policy_id(expectation.policy_id)

    def evaluate_case(
        self,
        case: Case,
        trace: Trace,
        evaluator_specs: tuple[EvaluatorSpec, ...],
    ) -> tuple[EvaluationResult, ...]:
        return execute_evaluators(
            case,
            trace,
            evaluator_specs,
            self._implementations,
        )

    def _user_evaluator(self, evaluator_id: str) -> Evaluator:
        if evaluator_id in self._builtin_evaluators:
            raise BuiltinEvaluatorMutation(
                f"built-in Evaluator is read-only: {evaluator_id}"
            )
        evaluator = self.repository.get_evaluator(evaluator_id)
        if evaluator is None:
            raise EvaluatorNotFound(f"unknown Evaluator: {evaluator_id}")
        return evaluator

    def _validate_supported_spec(self, spec: EvaluatorSpec) -> None:
        key = (spec.implementation_id, spec.implementation_version)
        implementation = self._implementations.get(key)
        if implementation is None:
            raise UnknownEvaluator(
                "unknown evaluator implementation: "
                f"{spec.implementation_id}@{spec.implementation_version}"
            )
        if implementation.implementation_id != spec.implementation_id:
            raise UnknownEvaluator(
                f"implementation key {key!r} does not match "
                f"{implementation.implementation_id!r}"
            )
        if implementation.implementation_version != spec.implementation_version:
            raise EvaluatorVersionMismatch(
                f"{spec.implementation_id} requires version "
                f"{spec.implementation_version}, not "
                f"{implementation.implementation_version}"
            )
        if implementation.kind != spec.kind:
            raise EvaluatorKindMismatch(
                f"{spec.implementation_id} implements "
                f"{implementation.kind}, not {spec.kind}"
            )
        if spec.kind == EvaluatorKind.RULE and spec.config:
            raise ValueError("Rule Evaluator config must be empty")
        if spec.kind == EvaluatorKind.LLM_JUDGE:
            validate_spec = getattr(implementation, "validate_spec", None)
            if not callable(validate_spec):
                raise TypeError("LLM Judge implementation must validate specifications")
            validate_spec(spec)

    def _validate_hybrid_children(
        self,
        spec: EvaluatorSpec,
        *,
        require_enabled: bool,
    ) -> tuple[EvaluatorSpec, ...]:
        children = tuple(
            self.get_version(child.evaluator_id, child.evaluator_version)
            for child in spec.children
        )
        if require_enabled:
            for child in children:
                identity = self.get_evaluator(child.id)
                if not identity.enabled:
                    raise EvaluatorCatalogConflict(
                        f"disabled Evaluator cannot be selected: {child.id}"
                    )
        if spec.kind == EvaluatorKind.HYBRID:
            if any(child.kind == EvaluatorKind.HYBRID for child in children):
                raise InvalidHybridEvaluator("nested Hybrid is not supported")
            child_kinds = {child.kind for child in children}
            if not {EvaluatorKind.RULE, EvaluatorKind.LLM_JUDGE}.issubset(
                child_kinds
            ):
                raise InvalidHybridEvaluator(
                    "Hybrid requires Rule and LLM Judge children"
                )
        return children

    def _add_selectable(
        self,
        evaluator_id: str,
        selected: dict[str, EvaluatorSpec],
        *,
        exact_version: str | None = None,
    ) -> None:
        existing = selected.get(evaluator_id)
        if existing is not None:
            if exact_version is not None and existing.version != exact_version:
                raise EvaluatorVersionMismatch(
                    f"{evaluator_id} requires both evaluator version "
                    f"{existing.version} and {exact_version}"
                )
            return

        identity = self.get_evaluator(evaluator_id)
        if not identity.enabled:
            raise EvaluatorCatalogConflict(
                f"disabled Evaluator cannot be selected: {evaluator_id}"
            )
        if exact_version is not None:
            spec = self.get_version(evaluator_id, exact_version)
        else:
            spec = self._builtin_specs_by_id.get(evaluator_id)
            if spec is None:
                spec = self.repository.get_latest_evaluator_version(evaluator_id)
                if spec is None:
                    raise EvaluatorCatalogConflict(
                        f"unpublished Evaluator cannot be selected: {evaluator_id}"
                    )
        selected[evaluator_id] = spec
        for child in self._validate_hybrid_children(spec, require_enabled=True):
            self._add_selectable(
                child.id,
                selected,
                exact_version=child.version,
            )


_BUILTIN_DEFINED_AT = datetime(2026, 9, 8, tzinfo=UTC)

_BUILTIN_EVALUATOR_SPECS = (
    EvaluatorSpec(
        id="skill-routing",
        name="Skill Routing",
        implementation_id="skill_routing",
        dimension="routing",
        metric="skill_routing_accuracy",
    ),
    EvaluatorSpec(
        id="required-tool",
        name="Required Tool",
        implementation_id="required_tool",
        dimension="tool_use",
        metric="tool_coverage",
    ),
    EvaluatorSpec(
        id="forbidden-tool",
        name="Forbidden Tool",
        implementation_id="forbidden_tool",
        dimension="tool_use",
        metric="forbidden_tool_compliance",
        severity=EvaluatorSeverity.BLOCKING,
    ),
    EvaluatorSpec(
        id="tool-arguments",
        name="Tool Arguments",
        implementation_id="tool_arguments",
        dimension="tool_use",
        metric="tool_argument_accuracy",
    ),
    EvaluatorSpec(
        id="final-state",
        name="Final State",
        implementation_id="final_state",
        dimension="state",
        metric="final_state_match",
    ),
    EvaluatorSpec(
        id="final-output",
        name="Final Output",
        implementation_id="final_output",
        dimension="answer",
        metric="final_output_match",
    ),
    EvaluatorSpec(
        id="policy-compliance",
        name="Policy Compliance",
        implementation_id="policy_compliance",
        dimension="safety",
        metric="policy_compliance",
        severity=EvaluatorSeverity.BLOCKING,
    ),
)

_BUILTIN_IMPLEMENTATIONS = {
    ("skill_routing", "1"): SkillRoutingEvaluator(),
    ("required_tool", "1"): RequiredToolEvaluator(),
    ("forbidden_tool", "1"): ForbiddenToolEvaluator(),
    ("tool_arguments", "1"): ToolArgumentsEvaluator(),
    ("final_state", "1"): FinalStateEvaluator(),
    ("final_output", "1"): FinalOutputEvaluator(),
    ("policy_compliance", "1"): PolicyComplianceEvaluator(),
}


def build_default_evaluator_management(
    repository: AgentGateRepository,
    *,
    judge_client: JudgeModelClient | None = None,
    judge_model_id: str | None = None,
    judge_credential_ref: str | None = None,
) -> EvaluatorManagement:
    """Compose the built-in catalog with an optional answer-quality Judge."""

    judge_arguments = (judge_client, judge_model_id, judge_credential_ref)
    if any(value is not None for value in judge_arguments) and not all(
        value is not None for value in judge_arguments
    ):
        raise ValueError(
            "Judge client, model ID, and credential reference must be provided together"
        )

    specs = _BUILTIN_EVALUATOR_SPECS
    implementations = dict(_BUILTIN_IMPLEMENTATIONS)
    if judge_client is not None:
        assert judge_model_id is not None
        assert judge_credential_ref is not None
        specs = (
            *specs,
            EvaluatorSpec(
                id="answer-quality",
                name="Answer Quality",
                kind=EvaluatorKind.LLM_JUDGE,
                dimension="answer",
                metric="answer_quality",
                implementation_id="answer_quality",
                config={
                    "model": {
                        "provider_id": judge_client.provider_id,
                        "model_id": judge_model_id,
                        "credential_ref": judge_credential_ref,
                    },
                    "instruction": (
                        "Evaluate whether the final answer appropriately responds to "
                        "the user's request using only the supplied execution evidence."
                    ),
                    "rubric": {
                        "correctness": (
                            "The answer is consistent with the supplied inputs and "
                            "execution evidence."
                        ),
                        "completeness": (
                            "The answer addresses the request without omitting essential "
                            "information."
                        ),
                        "relevance": (
                            "The answer is direct and contains no material unrelated "
                            "content."
                        ),
                    },
                    "input_selection": "final_output",
                    "pass_threshold": 0.8,
                    "temperature": 0,
                },
            ),
        )
        implementations[("answer_quality", "1")] = AnswerQualityJudge(
            {judge_client.provider_id: judge_client}
        )

    return EvaluatorManagement(repository, specs, implementations)
