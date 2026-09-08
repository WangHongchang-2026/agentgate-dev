"""Application-owned evaluator catalog, composition, and preflight."""

from __future__ import annotations

from collections.abc import Sequence
from types import MappingProxyType

from agentgate.domain import (
    Case,
    DatasetVersion,
    EvaluationResult,
    EvaluatorKind,
    EvaluatorSeverity,
    EvaluatorSpec,
    MatchesJsonSchema,
    PolicyExpectation,
    Trace,
)
from agentgate.evaluator.executor import (
    EvaluatorImplementations,
    execute_evaluators,
)
from agentgate.evaluator.judge import AnswerQualityJudge, JudgeModelClient
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


class EvaluatorManagement:
    """Hold one validated evaluator catalog and its exact implementations."""

    __slots__ = ("_available_specs", "_implementations", "_specs_by_id")

    def __init__(
        self,
        evaluator_specs: Sequence[EvaluatorSpec],
        implementations: EvaluatorImplementations,
    ) -> None:
        available_specs = tuple(evaluator_specs)
        if not available_specs:
            raise ValueError("at least one available Evaluator is required")
        specs_by_id = {spec.id: spec for spec in available_specs}
        if len(specs_by_id) != len(available_specs):
            raise DuplicateEvaluatorId("available Evaluator IDs must be unique")

        implementation_copy = dict(implementations)
        if not implementation_copy:
            raise ValueError("at least one Evaluator implementation is required")
        required_keys = {
            (spec.implementation_id, spec.implementation_version)
            for spec in available_specs
        }
        missing_keys = required_keys.difference(implementation_copy)
        if missing_keys:
            implementation_id, implementation_version = sorted(missing_keys)[0]
            raise UnknownEvaluator(
                "unknown evaluator implementation: "
                f"{implementation_id}@{implementation_version}"
            )
        unreferenced_keys = set(implementation_copy).difference(required_keys)
        if unreferenced_keys:
            implementation_id, implementation_version = sorted(unreferenced_keys)[0]
            raise UnknownEvaluator(
                "unreferenced evaluator implementation: "
                f"{implementation_id}@{implementation_version}"
            )

        for spec in available_specs:
            key = (spec.implementation_id, spec.implementation_version)
            implementation = implementation_copy[key]
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

        self._available_specs = available_specs
        self._specs_by_id = MappingProxyType(specs_by_id)
        self._implementations = MappingProxyType(implementation_copy)

    @property
    def available_specs(self) -> tuple[EvaluatorSpec, ...]:
        return self._available_specs

    def select(
        self,
        evaluator_ids: Sequence[str] | None,
    ) -> tuple[EvaluatorSpec, ...]:
        if evaluator_ids is None:
            return self._available_specs
        requested = tuple(evaluator_ids)
        if not requested:
            raise ValueError("at least one Evaluator is required")
        if len(set(requested)) != len(requested):
            raise DuplicateEvaluatorId("evaluator_ids must be unique")
        unknown = set(requested).difference(self._specs_by_id)
        if unknown:
            raise UnknownEvaluator(
                f"unknown Evaluators: {', '.join(sorted(unknown))}"
            )
        return tuple(self._specs_by_id[evaluator_id] for evaluator_id in requested)

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
            available = self._specs_by_id.get(spec.id)
            if available is None:
                raise UnknownEvaluator(f"unknown Evaluator: {spec.id}")
            if spec.version != available.version:
                raise EvaluatorVersionMismatch(
                    f"{spec.id} requires evaluator version {available.version}, "
                    f"not {spec.version}"
                )
            if spec.content_sha256 != available.content_sha256:
                raise ValueError(f"Evaluator content mismatch: {spec.id}")

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

    return EvaluatorManagement(specs, implementations)


DEFAULT_EVALUATOR_MANAGEMENT = build_default_evaluator_management()
