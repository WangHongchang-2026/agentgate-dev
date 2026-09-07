"""External target identity and execution contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import Field, model_validator

from .base import DomainModel, FrozenJsonObject, FrozenJsonValue, content_sha256
from .trace import Trace


def utcnow() -> datetime:
    return datetime.now(UTC)


def _check_schema(field_name: str, schema: FrozenJsonObject) -> None:
    raw = schema.to_dict()
    try:
        Draft202012Validator.check_schema(raw)
    except SchemaError as exc:
        raise ValueError(f"{field_name} must be a valid JSON Schema: {exc.message}") from exc
    anchors = {
        value
        for node in _schema_objects(raw)
        for key in ("$anchor", "$dynamicAnchor")
        if isinstance((value := node.get(key)), str)
    }
    for node in _schema_objects(raw):
        for key in ("$ref", "$dynamicRef"):
            ref = node.get(key)
            if not isinstance(ref, str):
                continue
            if ref == "#":
                continue
            if ref.startswith("#/"):
                if _resolve_json_pointer(raw, ref[1:]) is None:
                    raise ValueError(f"{field_name} contains an unresolved local reference: {ref}")
                continue
            if ref.startswith("#") and ref[1:] in anchors:
                continue
            raise ValueError(f"{field_name} contains an unsupported external reference: {ref}")


def _schema_objects(value: object):
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)


def _resolve_json_pointer(document: object, pointer: str) -> object | None:
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        return None
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None
    return current


class TargetType(StrEnum):
    AGENT = "agent"
    SKILL = "skill"


class TargetRef(DomainModel):
    platform_id: str
    target_type: TargetType
    external_target_id: str
    external_version_id: str

    @model_validator(mode="after")
    def validate_non_empty(self) -> TargetRef:
        for field in ("platform_id", "external_target_id", "external_version_id"):
            if not getattr(self, field):
                raise ValueError(f"{field} must be non-empty")
        return self


class TargetToolDescriptor(DomainModel):
    name: str
    description: str = ""
    arguments_schema: FrozenJsonObject = Field(default_factory=FrozenJsonObject)

    @model_validator(mode="after")
    def validate_name(self) -> TargetToolDescriptor:
        if not self.name.strip():
            raise ValueError("tool name must be non-empty")
        _check_schema("arguments_schema", self.arguments_schema)
        return self


class TargetSkillDescriptor(DomainModel):
    name: str
    description: str = ""
    prompt_or_capability_summary: str = ""
    tools: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_name(self) -> TargetSkillDescriptor:
        if not self.name.strip():
            raise ValueError("skill name must be non-empty")
        return self


class TargetDescriptor(DomainModel):
    ref: TargetRef
    display_name: str
    description: str = ""
    prompt_or_capability_summary: str = ""
    skills: tuple[TargetSkillDescriptor, ...] = ()
    tools: tuple[TargetToolDescriptor, ...] = ()
    input_schema: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    output_schema: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    reproducibility_limited: bool = False
    descriptor_sha256: str = ""

    @model_validator(mode="after")
    def validate_descriptor(self) -> TargetDescriptor:
        if not self.display_name.strip():
            raise ValueError("display_name must be non-empty")
        _check_schema("input_schema", self.input_schema)
        _check_schema("output_schema", self.output_schema)
        tool_names = [item.name for item in self.tools]
        if len(tool_names) != len(set(tool_names)):
            raise ValueError("target tool names must be unique")
        skill_names = [item.name for item in self.skills]
        if len(skill_names) != len(set(skill_names)):
            raise ValueError("target skill names must be unique")
        unknown = sorted({tool for skill in self.skills for tool in skill.tools} - set(tool_names))
        if unknown:
            raise ValueError(f"skills reference unknown tools: {', '.join(unknown)}")
        payload = self.model_dump(mode="json", exclude={"descriptor_sha256"})
        expected = content_sha256(payload)
        if self.descriptor_sha256 and self.descriptor_sha256 != expected:
            raise ValueError("TargetDescriptor content hash mismatch")
        if not self.descriptor_sha256:
            object.__setattr__(self, "descriptor_sha256", expected)
        return self


class TargetSnapshot(DomainModel):
    ref: TargetRef
    display_name: str
    adapter_type: str
    adapter_version: str
    descriptor_sha256: str = ""
    invocation_config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    credential_ref: str | None = None
    captured_at: datetime = Field(default_factory=utcnow)
    content_sha256: str = ""

    @model_validator(mode="after")
    def set_or_verify_hash(self) -> TargetSnapshot:
        payload = self.model_dump(mode="json", exclude={"content_sha256"})
        expected = content_sha256(payload)
        if self.content_sha256 and self.content_sha256 != expected:
            raise ValueError("TargetSnapshot content hash mismatch")
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", expected)
        return self


class TargetExecutionRequest(DomainModel):
    invocation_id: str
    idempotency_key: str
    run_id: str
    case_id: str
    turn_id: str | None = None
    target: TargetSnapshot
    input: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    state: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    timeout_seconds: float = 30.0
    traceparent: str
    baggage: str | None = None


class TargetExecutionResult(DomainModel):
    invocation_id: str
    external_execution_id: str | None = None
    output: FrozenJsonValue = None
    final_state: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    inline_trace: Trace | None = None
    trace_id: str | None = None
    completed_at: datetime = Field(default_factory=utcnow)
