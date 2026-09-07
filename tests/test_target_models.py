"""Domain contract tests for target types (acceptance #1-4)."""

import pytest
from pydantic import ValidationError

from agentgate.demo.loan import LOAN_DATASET_VERSION
from agentgate.domain import (
    GateSpec,
    MetricPlan,
    RunSnapshot,
    TargetDescriptor,
    TargetRef,
    TargetSnapshot,
    TargetToolDescriptor,
    TargetType,
)
from agentgate.domain.base import freeze_json
from agentgate.evaluator import EVALUATORS


def test_target_type_accepts_agent_and_skill():
    assert TargetType("agent") == TargetType.AGENT
    assert TargetType("skill") == TargetType.SKILL


def test_target_type_rejects_unknown():
    with pytest.raises(ValueError):
        TargetType("invalid")


def test_target_ref_requires_all_fields():
    with pytest.raises(ValidationError):
        TargetRef(
            platform_id="demo", target_type=TargetType.AGENT,
            external_target_id="loan", external_version_id="",
        )


def test_target_ref_requires_non_empty_fields():
    with pytest.raises(ValidationError):
        TargetRef(
            platform_id="", target_type=TargetType.AGENT,
            external_target_id="loan", external_version_id="v1",
        )


@pytest.mark.parametrize("field", ["input_schema", "output_schema"])
def test_target_descriptor_rejects_invalid_json_schema(field):
    values = {
        "ref": TargetRef(
            platform_id="demo", target_type=TargetType.AGENT,
            external_target_id="agent", external_version_id="v1",
        ),
        "display_name": "Agent",
        field: {"type": "unknown-json-schema-type"},
    }
    with pytest.raises(ValidationError, match=field):
        TargetDescriptor(**values)


def test_target_tool_descriptor_rejects_invalid_arguments_schema():
    with pytest.raises(ValidationError, match="arguments_schema"):
        TargetToolDescriptor(
            name="lookup",
            arguments_schema={"required": "must-be-an-array"},
        )


@pytest.mark.parametrize("ref", [
    "https://schemas.example/tool.json",
    "file:///tmp/tool.json",
    "other-schema.json#/$defs/Input",
])
def test_target_descriptor_rejects_external_schema_references(ref):
    with pytest.raises(ValidationError, match="unsupported external reference"):
        TargetToolDescriptor(name="lookup", arguments_schema={"$ref": ref})


def test_target_descriptor_rejects_unresolved_local_schema_reference():
    with pytest.raises(ValidationError, match="unresolved local reference"):
        TargetToolDescriptor(
            name="lookup",
            arguments_schema={"$ref": "#/$defs/Missing"},
        )


def _snapshot(version="v1", adapter_type="python_fn", config=None):
    return TargetSnapshot(
        ref=TargetRef(
            platform_id="demo", target_type=TargetType.AGENT,
            external_target_id="loan", external_version_id=version,
        ),
        display_name="loan",
        adapter_type=adapter_type,
        adapter_version="1",
        invocation_config=freeze_json(config or {}),
    )


def test_target_snapshot_is_deeply_immutable():
    snap = _snapshot()
    with pytest.raises(ValidationError):
        snap.ref.external_version_id = "tampered"


def test_target_snapshot_content_hash_covers_all_fields():
    snap = _snapshot(version="v1")
    assert snap.content_sha256 != ""
    snap2 = _snapshot(version="v2")
    assert snap.content_sha256 != snap2.content_sha256


def test_target_snapshot_hash_changes_with_adapter_version():
    snap1 = _snapshot(adapter_type="python_fn")
    snap2 = _snapshot(adapter_type="http")
    assert snap1.content_sha256 != snap2.content_sha256


def test_target_snapshot_hash_changes_with_invocation_config():
    snap1 = _snapshot(config={"endpoint": "http://a"})
    snap2 = _snapshot(config={"endpoint": "http://b"})
    assert snap1.content_sha256 != snap2.content_sha256


def test_target_snapshot_rejects_plaintext_credential_field():
    with pytest.raises(ValidationError):
        TargetSnapshot(
            ref=TargetRef(
                platform_id="demo", target_type=TargetType.AGENT,
                external_target_id="loan", external_version_id="v1",
            ),
            display_name="loan",
            adapter_type="python_fn",
            adapter_version="1",
            credential="secret-value",
        )


def test_run_snapshot_hash_changes_with_target_version():
    def run_snap(version):
        return RunSnapshot(
            dataset=LOAN_DATASET_VERSION,
            target=_snapshot(version=version),
            evaluator_specs=EVALUATORS,
            primary_evaluator_ids=tuple(item.id for item in EVALUATORS),
            metric_plan=MetricPlan(),
            gate_spec=GateSpec(),
        )
    assert run_snap("v1").snapshot_sha256 != run_snap("v2").snapshot_sha256


def test_run_snapshot_hash_changes_with_adapter_type():
    def run_snap(adapter_type):
        return RunSnapshot(
            dataset=LOAN_DATASET_VERSION,
            target=_snapshot(adapter_type=adapter_type),
            evaluator_specs=EVALUATORS,
            primary_evaluator_ids=tuple(item.id for item in EVALUATORS),
            metric_plan=MetricPlan(),
            gate_spec=GateSpec(),
        )
    assert run_snap("python_fn").snapshot_sha256 != run_snap("http").snapshot_sha256
