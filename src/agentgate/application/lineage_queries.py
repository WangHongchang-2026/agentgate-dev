"""Read-only lineage graphs derived from immutable Evaluation Run records."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from agentgate.domain import (
    Case,
    DatasetVersion,
    EvaluationRun,
    EvaluatorSpec,
    SkillDescriptor,
    TargetDescriptor,
    TargetRef,
    TargetType,
    content_sha256,
)
from agentgate.domain.base import require_non_blank, require_sha256
from agentgate.storage.repository import AgentGateRepository

from .target_catalog import TargetCatalog


LineageNodeKind: TypeAlias = Literal[
    "run",
    "dataset",
    "case",
    "agent",
    "skill",
    "evaluator",
]
LineageRelation: TypeAlias = Literal[
    "uses_dataset",
    "contains_case",
    "evaluates_agent",
    "evaluates_skill",
    "includes_skill",
    "uses_evaluator",
]


class LineageNode(BaseModel):
    """Sanitized version identity displayed as one lineage graph node."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: LineageNodeKind
    external_id: str
    label: str
    version: str | None = None
    content_sha256: str | None = None

    @field_validator("id", "external_id", "label")
    @classmethod
    def validate_required_text(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"LineageNode {info.field_name}")

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_non_blank(value, "LineageNode version")

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return require_sha256(value, "LineageNode content_sha256")


class LineageEdge(BaseModel):
    """One typed directed relationship between two lineage nodes."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    target_id: str
    relation: LineageRelation

    @field_validator("source_id", "target_id")
    @classmethod
    def validate_endpoint(cls, value: str, info: ValidationInfo) -> str:
        return require_non_blank(value, f"LineageEdge {info.field_name}")


class LineageGraph(BaseModel):
    """Deterministic, internally consistent lineage graph read model."""

    model_config = ConfigDict(frozen=True)

    root_node_id: str
    nodes: tuple[LineageNode, ...] = Field(min_length=1)
    edges: tuple[LineageEdge, ...] = ()

    @field_validator("root_node_id")
    @classmethod
    def validate_root_id(cls, value: str) -> str:
        return require_non_blank(value, "LineageGraph root_node_id")

    @model_validator(mode="after")
    def validate_graph(self) -> "LineageGraph":
        ordered_node_ids = tuple(node.id for node in self.nodes)
        node_ids = set(ordered_node_ids)
        if len(node_ids) != len(ordered_node_ids):
            raise ValueError("LineageGraph node IDs must be unique")
        if self.root_node_id not in node_ids:
            raise ValueError("LineageGraph root node does not exist")

        edge_keys = tuple(
            (edge.source_id, edge.target_id, edge.relation)
            for edge in self.edges
        )
        if len(set(edge_keys)) != len(edge_keys):
            raise ValueError("LineageGraph edges must be unique")
        unknown_endpoints = {
            endpoint
            for edge in self.edges
            for endpoint in (edge.source_id, edge.target_id)
            if endpoint not in node_ids
        }
        if unknown_endpoints:
            raise ValueError("LineageGraph edge references an unknown node")
        return self


class LineageQueries:
    """Build lineage views from persisted immutable records."""

    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository
        self.target_catalog = TargetCatalog(repository)

    def get_run_lineage(self, run_id: str) -> LineageGraph:
        run_identity = require_non_blank(run_id, "EvaluationRun id")
        run = self.repository.get_run(run_identity)
        if run is None:
            raise LookupError(f"unknown EvaluationRun: {run_identity}")
        descriptor = self.target_catalog.resolve_descriptor(
            run.manifest.target.ref,
            run.manifest.target.descriptor_sha256,
        )
        return _build_run_graph(run, descriptor)

    def get_dataset_lineage(
        self, dataset_id: str, version: int, limit: int = 50
    ) -> LineageGraph:
        dataset = self.repository.get_published_dataset_version(
            require_non_blank(dataset_id, "Dataset id"), version
        )
        if dataset is None:
            raise LookupError(f"unknown published DatasetVersion: {dataset_id} v{version}")
        return self._expand_reverse(
            _dataset_node(dataset),
            self.repository.list_runs_by_dataset_version(
                dataset.dataset_id, version, limit
            ),
        )

    def get_case_lineage(
        self,
        dataset_id: str,
        version: int,
        case_id: str,
        limit: int = 50,
    ) -> LineageGraph:
        dataset = self.repository.get_published_dataset_version(
            require_non_blank(dataset_id, "Dataset id"), version
        )
        if dataset is None:
            raise LookupError(f"unknown published DatasetVersion: {dataset_id} v{version}")
        case_identity = require_non_blank(case_id, "Case id")
        case = next((item for item in dataset.cases if item.id == case_identity), None)
        if case is None:
            raise LookupError(
                f"unknown Case in DatasetVersion: {case_identity}"
            )
        case_hash = content_sha256(case)
        return self._expand_reverse(
            _case_node(dataset, case),
            self.repository.list_runs_by_case_content(
                dataset.dataset_id,
                version,
                case.id,
                case_hash,
                limit,
            ),
        )

    def get_target_lineage(
        self,
        ref: TargetRef,
        content_hash: str | None = None,
        limit: int = 50,
    ) -> LineageGraph:
        descriptors = self.target_catalog.list_descriptors(ref)
        descriptor = _select_descriptor(descriptors, content_hash)
        root = _target_node(descriptor)
        runs = self.repository.list_runs_by_target_version(
            ref.source_id,
            ref.target_type,
            ref.external_target_id,
            ref.external_version_id,
            limit,
            content_sha256=descriptor.content_sha256,
        )
        return self._expand_reverse(root, runs, require_root_in_run=True)

    def get_skill_lineage(
        self,
        source_id: str,
        skill_id: str,
        version: str,
        content_hash: str | None = None,
        limit: int = 50,
    ) -> LineageGraph:
        source = require_non_blank(source_id, "Skill source_id")
        identity = require_non_blank(skill_id, "Skill id")
        skill_version = require_non_blank(version, "Skill version")
        candidates: dict[str, LineageNode] = {}
        for descriptor in self.target_catalog.list_descriptors():
            if descriptor.ref.source_id != source:
                continue
            if (
                descriptor.ref.target_type is TargetType.SKILL
                and descriptor.ref.external_target_id == identity
                and descriptor.ref.external_version_id == skill_version
            ):
                node = _target_node(descriptor)
                candidates[node.id] = node
            for skill in descriptor.skills:
                if (
                    skill.external_skill_id == identity
                    and skill.external_version_id == skill_version
                ):
                    node = _skill_node(descriptor, skill)
                    candidates[node.id] = node
        root = _select_node(
            tuple(candidates.values()),
            "Skill version",
            f"{source}/{identity}/{skill_version}",
            content_hash,
        )
        runs = self.repository.list_runs_by_skill_version(
            source,
            identity,
            skill_version,
            limit,
            content_sha256=root.content_sha256,
        )
        return self._expand_reverse(root, runs, require_root_in_run=True)

    def get_evaluator_lineage(
        self,
        evaluator_id: str,
        version: str,
        content_hash: str | None = None,
        limit: int = 50,
    ) -> LineageGraph:
        identity = require_non_blank(evaluator_id, "Evaluator id")
        evaluator_version = require_non_blank(version, "Evaluator version")
        runs = self.repository.list_runs_by_evaluator_version(
            identity, evaluator_version, limit
        )
        candidates = {
            node.id: node
            for run in runs
            for evaluator in run.manifest.evaluator_specs
            if evaluator.id == identity and evaluator.version == evaluator_version
            for node in (_evaluator_node(evaluator),)
        }
        root = _select_node(
            tuple(candidates.values()),
            "Evaluator version",
            f"{identity}/{evaluator_version}",
            content_hash,
        )
        return self._expand_reverse(root, runs, require_root_in_run=True)

    def _expand_reverse(
        self,
        root: LineageNode,
        runs: list[EvaluationRun],
        *,
        require_root_in_run: bool = False,
    ) -> LineageGraph:
        nodes = {root.id: root}
        edges: set[tuple[str, str, LineageRelation]] = set()
        for run in runs:
            descriptor = self.target_catalog.resolve_descriptor(
                run.manifest.target.ref,
                run.manifest.target.descriptor_sha256,
            )
            graph = _build_run_graph(run, descriptor)
            if require_root_in_run and all(
                node.id != root.id for node in graph.nodes
            ):
                continue
            for node in graph.nodes:
                _add_node(nodes, node)
            for edge in graph.edges:
                _add_edge(
                    edges,
                    edge.source_id,
                    edge.target_id,
                    edge.relation,
                )
        return _lineage_graph(root.id, nodes, edges)


def _build_run_graph(
    run: EvaluationRun,
    descriptor: TargetDescriptor,
) -> LineageGraph:
    nodes: dict[str, LineageNode] = {}
    edges: set[tuple[str, str, LineageRelation]] = set()

    run_node = _run_node(run)
    dataset_node = _dataset_node(run.manifest.dataset)
    target_node = _target_node(descriptor)
    _add_node(nodes, run_node)
    _add_node(nodes, dataset_node)
    _add_node(nodes, target_node)
    _add_edge(edges, run_node.id, dataset_node.id, "uses_dataset")
    target_relation: LineageRelation = (
        "evaluates_agent"
        if descriptor.ref.target_type is TargetType.AGENT
        else "evaluates_skill"
    )
    _add_edge(edges, run_node.id, target_node.id, target_relation)

    for case in run.manifest.execution_cases:
        case_node = _case_node(run.manifest.dataset, case)
        _add_node(nodes, case_node)
        _add_edge(edges, dataset_node.id, case_node.id, "contains_case")

    if descriptor.ref.target_type is TargetType.AGENT:
        for skill in descriptor.skills:
            skill_node = _skill_node(descriptor, skill)
            _add_node(nodes, skill_node)
            _add_edge(edges, target_node.id, skill_node.id, "includes_skill")

    for evaluator in run.manifest.evaluator_specs:
        evaluator_node = _evaluator_node(evaluator)
        _add_node(nodes, evaluator_node)
        _add_edge(edges, run_node.id, evaluator_node.id, "uses_evaluator")

    return _lineage_graph(run_node.id, nodes, edges)


def _lineage_graph(
    root_node_id: str,
    nodes: dict[str, LineageNode],
    edges: set[tuple[str, str, LineageRelation]],
) -> LineageGraph:
    ordered_nodes = tuple(
        sorted(nodes.values(), key=lambda item: (item.kind, item.id))
    )
    ordered_edges = tuple(
        LineageEdge(source_id=source, target_id=target, relation=relation)
        for source, target, relation in sorted(
            edges,
            key=lambda item: (item[2], item[0], item[1]),
        )
    )
    return LineageGraph(
        root_node_id=root_node_id,
        nodes=ordered_nodes,
        edges=ordered_edges,
    )


def _run_node(run: EvaluationRun) -> LineageNode:
    return LineageNode(
        id=f"run:{run.id}",
        kind="run",
        external_id=run.id,
        label=f"Evaluation Run {run.id}",
        content_sha256=run.manifest.manifest_sha256,
    )


def _dataset_node(dataset: DatasetVersion) -> LineageNode:
    return LineageNode(
        id=_hashed_node_id(
            "dataset",
            {
                "dataset_id": dataset.dataset_id,
                "version": dataset.version,
                "content_sha256": dataset.content_sha256,
            },
        ),
        kind="dataset",
        external_id=dataset.dataset_id,
        label=dataset.dataset_name or dataset.dataset_id,
        version=str(dataset.version),
        content_sha256=dataset.content_sha256,
    )


def _case_node(dataset: DatasetVersion, case: Case) -> LineageNode:
    case_hash = content_sha256(case)
    return LineageNode(
        id=_hashed_node_id(
            "case",
            {
                "dataset_id": dataset.dataset_id,
                "dataset_version": dataset.version,
                "case_id": case.id,
                "content_sha256": case_hash,
            },
        ),
        kind="case",
        external_id=case.id,
        label=case.name,
        content_sha256=case_hash,
    )


def _target_node(descriptor: TargetDescriptor) -> LineageNode:
    kind: LineageNodeKind = descriptor.ref.target_type.value
    return LineageNode(
        id=_hashed_node_id(
            kind,
            {
                "source_id": descriptor.ref.source_id,
                "external_id": descriptor.ref.external_target_id,
                "version": descriptor.ref.external_version_id,
                "content_sha256": descriptor.content_sha256,
            },
        ),
        kind=kind,
        external_id=descriptor.ref.external_target_id,
        label=descriptor.display_name,
        version=descriptor.ref.external_version_id,
        content_sha256=descriptor.content_sha256,
    )


def _skill_node(
    descriptor: TargetDescriptor,
    skill: SkillDescriptor,
) -> LineageNode:
    skill_hash = content_sha256(skill)
    return LineageNode(
        id=_hashed_node_id(
            "skill",
            {
                "source_id": descriptor.ref.source_id,
                "external_id": skill.external_skill_id,
                "version": skill.external_version_id,
                "content_sha256": skill_hash,
            },
        ),
        kind="skill",
        external_id=skill.external_skill_id,
        label=skill.name,
        version=skill.external_version_id,
        content_sha256=skill_hash,
    )


def _evaluator_node(evaluator: EvaluatorSpec) -> LineageNode:
    return LineageNode(
        id=_hashed_node_id(
            "evaluator",
            {
                "id": evaluator.id,
                "version": evaluator.version,
                "content_sha256": evaluator.content_sha256,
            },
        ),
        kind="evaluator",
        external_id=evaluator.id,
        label=evaluator.name,
        version=evaluator.version,
        content_sha256=evaluator.content_sha256,
    )


def _select_descriptor(
    descriptors: tuple[TargetDescriptor, ...],
    content_hash: str | None,
) -> TargetDescriptor:
    if content_hash is not None:
        selected_hash = require_sha256(content_hash, "Target content_sha256")
        descriptors = tuple(
            item for item in descriptors if item.content_sha256 == selected_hash
        )
    if not descriptors:
        raise LookupError("unknown TargetDescriptor version")
    if len(descriptors) > 1:
        raise ValueError("Target version has multiple content hashes")
    return descriptors[0]


def _select_node(
    candidates: tuple[LineageNode, ...],
    kind: str,
    identity: str,
    content_hash: str | None,
) -> LineageNode:
    if content_hash is not None:
        selected_hash = require_sha256(content_hash, f"{kind} content_sha256")
        candidates = tuple(
            node for node in candidates if node.content_sha256 == selected_hash
        )
    if not candidates:
        raise LookupError(f"unknown {kind}: {identity}")
    if len(candidates) > 1:
        raise ValueError(f"{kind} has multiple content hashes")
    return candidates[0]


def _hashed_node_id(kind: str, identity: object) -> str:
    return f"{kind}:{content_sha256(identity)}"


def _add_node(nodes: dict[str, LineageNode], node: LineageNode) -> None:
    existing = nodes.get(node.id)
    if existing is not None and existing != node:
        raise ValueError("lineage node identity collision")
    nodes[node.id] = node


def _add_edge(
    edges: set[tuple[str, str, LineageRelation]],
    source_id: str,
    target_id: str,
    relation: LineageRelation,
) -> None:
    edges.add((source_id, target_id, relation))


__all__ = [
    "LineageEdge",
    "LineageGraph",
    "LineageNode",
    "LineageNodeKind",
    "LineageQueries",
    "LineageRelation",
]
