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

    for case in run.manifest.dataset.cases:
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

    ordered_nodes = tuple(sorted(nodes.values(), key=lambda item: (item.kind, item.id)))
    ordered_edges = tuple(
        LineageEdge(source_id=source, target_id=target, relation=relation)
        for source, target, relation in sorted(
            edges,
            key=lambda item: (item[2], item[0], item[1]),
        )
    )
    return LineageGraph(
        root_node_id=run_node.id,
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
            "target",
            {
                "ref": descriptor.ref.model_dump(mode="json"),
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
                "skill": skill.model_dump(mode="json"),
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
