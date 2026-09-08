from __future__ import annotations

import sqlite3

import pytest
from pydantic import ValidationError

from agentgate.application import RunManagement, TargetCatalog
from agentgate.application.evaluator_management import (
    build_default_evaluator_management,
)
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
from agentgate.storage.sqlite import SQLiteRepository


def demo_run(repository: SQLiteRepository, version: str = "loan-agent-v2-fixed"):
    ensure_demo_dataset(repository)
    ensure_demo_target_descriptors(TargetCatalog(repository))
    evaluators = build_default_evaluator_management(repository)
    return RunManagement(repository, evaluators).create_run(
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
        run.manifest.evaluator_specs
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
    evaluators = build_default_evaluator_management(repository)
    run = RunManagement(repository, evaluators).create_run(
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


def test_reverse_lineage_expands_related_runs_from_each_asset(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "reverse-graphs.db")
    baseline = demo_run(repository, "loan-agent-v1-risky")
    candidate = demo_run(repository, "loan-agent-v2-fixed")
    queries = LineageQueries(repository)
    dataset = candidate.manifest.dataset
    case = dataset.cases[0]
    evaluator = candidate.manifest.evaluator_specs[0]

    dataset_graph = queries.get_dataset_lineage(
        dataset.dataset_id, dataset.version
    )
    case_graph = queries.get_case_lineage(
        dataset.dataset_id, dataset.version, case.id
    )
    target_graph = queries.get_target_lineage(candidate.manifest.target.ref)
    skill_graph = queries.get_skill_lineage(
        "agentgate-demo", "repayment_plan", "repayment-plan-v1"
    )
    evaluator_graph = queries.get_evaluator_lineage(
        evaluator.id, evaluator.version
    )

    assert dataset_graph.root_node_id.startswith("dataset:")
    assert case_graph.root_node_id.startswith("case:")
    assert target_graph.root_node_id.startswith("agent:")
    assert skill_graph.root_node_id.startswith("skill:")
    assert evaluator_graph.root_node_id.startswith("evaluator:")
    assert _run_ids(dataset_graph) == {baseline.id, candidate.id}
    assert _run_ids(case_graph) == {baseline.id, candidate.id}
    assert _run_ids(target_graph) == {candidate.id}
    assert _run_ids(skill_graph) == {baseline.id, candidate.id}
    assert _run_ids(evaluator_graph) == {baseline.id, candidate.id}


def test_dataset_lineage_without_runs_contains_only_its_root(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "empty-reverse-graph.db")
    ensure_demo_dataset(repository)

    graph = LineageQueries(repository).get_dataset_lineage(
        LOAN_DATASET.id, 1
    )

    assert len(graph.nodes) == 1
    assert graph.nodes[0].kind == "dataset"
    assert graph.edges == ()


def test_reverse_lineage_rejects_unknown_assets(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "unknown-reverse-graph.db")
    queries = LineageQueries(repository)

    with pytest.raises(LookupError, match="unknown published DatasetVersion"):
        queries.get_dataset_lineage("missing", 1)
    ensure_demo_dataset(repository)
    with pytest.raises(LookupError, match="unknown Case"):
        queries.get_case_lineage(LOAN_DATASET.id, 1, "missing")
    with pytest.raises(LookupError, match="unknown Skill version"):
        queries.get_skill_lineage("source", "missing", "v1")
    with pytest.raises(LookupError, match="unknown Evaluator version"):
        queries.get_evaluator_lineage("missing", "v1")


def test_target_lineage_requires_hash_for_ambiguous_external_version(tmp_path) -> None:
    repository = SQLiteRepository(tmp_path / "ambiguous-target.db")
    run = demo_run(repository, "loan-agent-v2-fixed")
    catalog = TargetCatalog(repository)
    original = get_demo_target_descriptor("loan-agent-v2-fixed")
    mutated_payload = original.model_dump(
        mode="json", exclude={"content_sha256", "prompt_sha256"}
    )
    mutated_payload["prompt"] = "Mutated in place by the external platform."
    mutated = TargetDescriptor.model_validate(mutated_payload)
    catalog.register_descriptor(mutated)
    queries = LineageQueries(repository)

    with pytest.raises(ValueError, match="multiple content hashes"):
        queries.get_target_lineage(original.ref)

    graph = queries.get_target_lineage(
        original.ref, content_hash=original.content_sha256
    )

    assert graph.root_node_id.startswith("agent:")
    assert _run_ids(graph) == {run.id}


def _run_ids(graph: LineageGraph) -> set[str]:
    return {
        node.external_id
        for node in graph.nodes
        if node.kind == "run"
    }
