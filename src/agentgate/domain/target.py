"""External Target identity, metadata descriptors, and execution snapshots."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, ValidationInfo, field_validator, model_validator

from .base import DomainModel, FrozenJsonObject, content_sha256


_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "bearer_token",
    "client_secret",
    "password",
    "secret_key",
}


def utcnow() -> datetime:
    """Return the current timezone-aware UTC timestamp."""

    return datetime.now(UTC)


def _require_non_blank(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must not be blank")
    return value


def _normalize_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _verify_sha256(value: str, field_name: str) -> str:
    if not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _set_or_verify_prompt_hash(instance: Any) -> None:
    if instance.prompt is None:
        return
    expected = hashlib.sha256(instance.prompt.encode("utf-8")).hexdigest()
    if instance.prompt_sha256 and instance.prompt_sha256 != expected:
        raise ValueError("prompt_sha256 does not match prompt content")
    if not instance.prompt_sha256:
        object.__setattr__(instance, "prompt_sha256", expected)


def _secret_path(value: Any, prefix: str = "") -> str | None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else key
            if key.lower().replace("-", "_") in _SECRET_KEYS:
                return path
            found = _secret_path(item, path)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found = _secret_path(item, f"{prefix}[{index}]")
            if found:
                return found
    return None


def _reject_secrets(value: FrozenJsonObject, field_name: str) -> FrozenJsonObject:
    path = _secret_path(value)
    if path:
        raise ValueError(f"{field_name} contains credential-like field: {path}")
    return value


class TargetType(StrEnum):
    """Externally owned object type supported as an evaluation Target."""

    AGENT = "agent"
    SKILL = "skill"


class TargetRef(DomainModel):
    """Exact external identity of one Agent or Skill version."""

    source_id: str
    target_type: TargetType
    external_target_id: str
    external_version_id: str

    @field_validator("source_id", "external_target_id", "external_version_id")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_blank(value, f"TargetRef {info.field_name}")


class ToolDescriptor(DomainModel):
    """Vendor-neutral declaration of one Tool visible to a Target."""

    name: str
    description: str | None = None
    input_schema: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    output_schema: FrozenJsonObject = Field(default_factory=FrozenJsonObject)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _require_non_blank(value, "Tool name")


class SkillDescriptor(DomainModel):
    """Vendor-neutral declaration of one versioned Skill within an Agent."""

    external_skill_id: str
    external_version_id: str
    name: str
    description: str | None = None
    prompt: str | None = None
    prompt_sha256: str | None = None
    tools: tuple[ToolDescriptor, ...] = ()
    input_schema: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    output_schema: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    metadata: FrozenJsonObject = Field(default_factory=FrozenJsonObject)

    @field_validator("external_skill_id", "external_version_id", "name")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_blank(value, f"Skill {info.field_name}")

    @field_validator("prompt_sha256")
    @classmethod
    def validate_prompt_hash(cls, value: str | None) -> str | None:
        return _verify_sha256(value, "prompt_sha256") if value is not None else None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: FrozenJsonObject) -> FrozenJsonObject:
        return _reject_secrets(value, "Skill metadata")

    @model_validator(mode="after")
    def validate_descriptor(self) -> "SkillDescriptor":
        tool_names = tuple(tool.name for tool in self.tools)
        if len(set(tool_names)) != len(tool_names):
            raise ValueError("Tool names must be unique within a Skill")
        _set_or_verify_prompt_hash(self)
        return self


class TargetDescriptor(DomainModel):
    """Normalized declaration fetched for one external Target version."""

    ref: TargetRef
    display_name: str
    description: str | None = None
    prompt: str | None = None
    prompt_sha256: str | None = None
    skills: tuple[SkillDescriptor, ...] = ()
    tools: tuple[ToolDescriptor, ...] = ()
    input_schema: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    output_schema: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    metadata: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    fetched_at: datetime = Field(default_factory=utcnow)
    content_sha256: str = ""

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str) -> str:
        return _require_non_blank(value, "Target display_name")

    @field_validator("prompt_sha256")
    @classmethod
    def validate_prompt_hash(cls, value: str | None) -> str | None:
        return _verify_sha256(value, "prompt_sha256") if value is not None else None

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        return _verify_sha256(value, "content_sha256") if value else value

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: FrozenJsonObject) -> FrozenJsonObject:
        return _reject_secrets(value, "Target metadata")

    @field_validator("fetched_at")
    @classmethod
    def normalize_fetched_at(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "fetched_at")

    @model_validator(mode="after")
    def validate_descriptor(self) -> "TargetDescriptor":
        if self.ref.target_type == TargetType.SKILL and self.skills:
            raise ValueError("Skill TargetDescriptor cannot contain nested Skills")

        skill_ids = tuple(
            (skill.external_skill_id, skill.external_version_id)
            for skill in self.skills
        )
        if len(set(skill_ids)) != len(skill_ids):
            raise ValueError("Skill identities must be unique within a TargetDescriptor")

        tool_names = tuple(tool.name for tool in self.tools)
        if len(set(tool_names)) != len(tool_names):
            raise ValueError("Tool names must be unique within a TargetDescriptor")

        _set_or_verify_prompt_hash(self)
        expected = content_sha256(
            self.model_dump(mode="json", exclude={"fetched_at", "content_sha256"})
        )
        if self.content_sha256 and self.content_sha256 != expected:
            raise ValueError("TargetDescriptor content hash mismatch")
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", expected)
        return self


class TargetSnapshot(DomainModel):
    """Immutable Target and adapter configuration captured for one Run."""

    ref: TargetRef
    display_name: str
    adapter_type: str
    adapter_version: str
    descriptor_sha256: str
    invocation_config: FrozenJsonObject = Field(default_factory=FrozenJsonObject)
    credential_ref: str | None = None
    captured_at: datetime = Field(default_factory=utcnow)
    content_sha256: str = ""

    @field_validator("display_name", "adapter_type", "adapter_version")
    @classmethod
    def validate_identity(cls, value: str, info: ValidationInfo) -> str:
        return _require_non_blank(value, f"TargetSnapshot {info.field_name}")

    @field_validator("descriptor_sha256")
    @classmethod
    def validate_descriptor_hash(cls, value: str) -> str:
        return _verify_sha256(value, "descriptor_sha256")

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        return _verify_sha256(value, "content_sha256") if value else value

    @field_validator("credential_ref")
    @classmethod
    def validate_credential_ref(cls, value: str | None) -> str | None:
        if value is not None:
            return _require_non_blank(value, "credential_ref")
        return value

    @field_validator("invocation_config")
    @classmethod
    def validate_invocation_config(
        cls, value: FrozenJsonObject
    ) -> FrozenJsonObject:
        return _reject_secrets(value, "invocation_config")

    @field_validator("captured_at")
    @classmethod
    def normalize_captured_at(cls, value: datetime) -> datetime:
        return _normalize_utc(value, "captured_at")

    @model_validator(mode="after")
    def set_or_verify_hash(self) -> "TargetSnapshot":
        expected = content_sha256(
            self.model_dump(
                mode="json",
                exclude={"display_name", "captured_at", "content_sha256"},
            )
        )
        if self.content_sha256 and self.content_sha256 != expected:
            raise ValueError("TargetSnapshot content hash mismatch")
        if not self.content_sha256:
            object.__setattr__(self, "content_sha256", expected)
        return self
