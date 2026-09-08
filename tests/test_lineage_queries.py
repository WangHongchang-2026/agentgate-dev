from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from agentgate.application import RunManagement, TargetCatalog
from agentgate.application.lineage_queries import (
    LineageEdge,
    LineageGraph,
    LineageNode,
    LineageQueries,
)
from agentgate.demo.bootstrap import (
    ensure_demo_dataset,
    ensure_demo_target_descriptors,
)
from agentgate.demo.loan import LOAN_DATASET
from agentgate.demo.targets import (
    build_demo_target_snapshot,
    get_demo_target_descriptor,
)
from agentgate.domain import (
    TargetDescriptor,
    TargetRef,
    TargetSnapshot,
    TargetType,
)
from agentgate.evaluator import EVALUATORS
from agentgate.storage.sqlite import SQLiteRepository


def demo_run(repository: SQLiteRepository, version: str = "loan-agent-v2-fixed"):
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))
    return RunManagement(repository, EVALUATORS).create_run(
        build_demo_target_snapshot(get_demo_target_descriptor(version)),
        dataset_id=LOAN_DATASET.id,
    )


def test_run_lineage_contains_exact_manifest_and_descriptor_assets(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "run-lineage.db")
    run = demo_run(repository)

    graph = LineageQueries(repository).get_run_lineage(run.id)

    assert graph.root_node_id == f"run:{run.id}"
    assert len(graph.nodes) == 15
    assert len(graph.edges) == 14
    assert [node.kind for node in graph.nodes] == sorted(
        node.kind for node in graph.nodes
    )
    assert {node.kind for node in graph.nodes} == {
        "run",
        "dataset",
        "case",
        "agent",
        "skill",
        "evaluator",
    }
    assert {
        node.external_id: node.version
        for node in graph.nodes
        if node.kind == "skill"
    }["loan_approval"] == "loan-approval-v2-fixed"
    assert sum(edge.relation == "uses_evaluator" for edge in graph.edges) == len(
        EVALUATORS
    )
    assert sum(edge.relation == "includes_skill" for edge in graph.edges) == 4


def test_skill_target_lineage_has_no_nested_skill_relationship(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "skill-lineage.db")
    ensure_demo_dataset(repository)
    ref = TargetRef(
        source_id="customer-platform",
        target_type=TargetType.SKILL,
        external_target_id="loan_approval",
        external_version_id="v3",
    )
    descriptor = TargetDescriptor(ref=ref, display_name="Loan Approval")
    TargetCatalog(repository).register_descriptor(descriptor)
    target = TargetSnapshot(
        ref=ref,
        display_name=descriptor.display_name,
        adapter_type="http_agent",
        adapter_version="1",
        descriptor_sha256=descriptor.content_sha256,
    )
    run = RunManagement(repository, EVALUATORS).create_run(
        target,
        dataset_id=LOAN_DATASET.id,
    )

    graph = LineageQueries(repository).get_run_lineage(run.id)

    assert sum(node.kind == "skill" for node in graph.nodes) == 1
    assert sum(edge.relation == "evaluates_skill" for edge in graph.edges) == 1
    assert all(edge.relation != "evaluates_agent" for edge in graph.edges)
    assert all(edge.relation != "includes_skill" for edge in graph.edges)


def test_run_lineage_rejects_unknown_run_or_descriptor(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "invalid-lineage.db")
    queries = LineageQueries(repository)

    with pytest.raises(LookupError, match="unknown EvaluationRun"):
        queries.get_run_lineage("missing")

    run = demo_run(repository)
    with sqlite3.connect(repository.path) as db:
        db.execute(
            "DELETE FROM target_descriptors WHERE content_sha256=?",
            (run.manifest.target.descriptor_sha256,),
        )
    with pytest.raises(LookupError, match="unknown TargetDescriptor"):
        queries.get_run_lineage(run.id)


def test_lineage_graph_rejects_duplicate_or_unknown_relationships() -> None:
    root = LineageNode(
        id="run:one",
        kind="run",
        external_id="one",
        label="Run one",
        content_sha256="a" * 64,
    )
    edge = LineageEdge(
        source_id=root.id,
        target_id="dataset:missing",
        relation="uses_dataset",
    )

    with pytest.raises(ValidationError, match="node IDs must be unique"):
        LineageGraph(root_node_id=root.id, nodes=(root, root))
    with pytest.raises(ValidationError, match="unknown node"):
        LineageGraph(root_node_id=root.id, nodes=(root,), edges=(edge,))
