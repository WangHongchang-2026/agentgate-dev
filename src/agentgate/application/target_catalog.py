"""Immutable Target descriptor registration and exact resolution."""

from __future__ import annotations

from agentgate.domain import TargetDescriptor, TargetRef
from agentgate.domain.base import require_sha256
from agentgate.storage.repository import AgentGateRepository


class TargetCatalog:
    """Coordinate immutable TargetDescriptor persistence and lookup."""

    def __init__(self, repository: AgentGateRepository) -> None:
        self.repository = repository

    def register_descriptor(
        self, descriptor: TargetDescriptor
    ) -> TargetDescriptor:
        self.repository.save_target_descriptor(descriptor)
        return descriptor

    def resolve_descriptor(
        self,
        ref: TargetRef,
        descriptor_sha256: str,
    ) -> TargetDescriptor:
        descriptor_hash = require_sha256(
            descriptor_sha256, "Target descriptor_sha256"
        )
        descriptor = self.repository.get_target_descriptor(descriptor_hash)
        if descriptor is None:
            raise LookupError(f"unknown TargetDescriptor: {descriptor_hash}")
        if descriptor.ref != ref:
            raise ValueError("TargetDescriptor reference does not match TargetSnapshot")
        return descriptor

    def list_descriptors(
        self, ref: TargetRef | None = None
    ) -> tuple[TargetDescriptor, ...]:
        return tuple(self.repository.list_target_descriptors(ref))


__all__ = ["TargetCatalog"]
