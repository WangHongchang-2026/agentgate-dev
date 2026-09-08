from datetime import UTC, datetime

import pytest

from agentgate.application.target_catalog import TargetCatalog
from agentgate.domain import TargetDescriptor, TargetRef, TargetType
from agentgate.storage.sqlite import SQLiteRepository


def target_ref(target_id: str = "loan-agent") -> TargetRef:
    return TargetRef(
        source_id="customer-platform",
        target_type=TargetType.AGENT,
        external_target_id=target_id,
        external_version_id="v1",
    )


def descriptor() -> TargetDescriptor:
    return TargetDescriptor(
        ref=target_ref(),
        display_name="Loan Agent",
        fetched_at=datetime(2026, 9, 8, tzinfo=UTC),
    )


def test_catalog_registers_lists_and_resolves_exact_descriptor(tmp_path) -> None:
    catalog = TargetCatalog(SQLiteRepository(tmp_path / "catalog.db"))
    value = descriptor()

    assert catalog.register_descriptor(value) == value
    assert catalog.list_descriptors() == (value,)
    assert catalog.list_descriptors(value.ref) == (value,)
    assert catalog.resolve_descriptor(value.ref, value.content_sha256) == value


def test_catalog_rejects_unknown_descriptor_hash(tmp_path) -> None:
    catalog = TargetCatalog(SQLiteRepository(tmp_path / "catalog-missing.db"))

    with pytest.raises(LookupError, match="unknown TargetDescriptor"):
        catalog.resolve_descriptor(target_ref(), "a" * 64)


def test_catalog_rejects_descriptor_reference_mismatch(tmp_path) -> None:
    catalog = TargetCatalog(SQLiteRepository(tmp_path / "catalog-mismatch.db"))
    value = descriptor()
    catalog.register_descriptor(value)

    with pytest.raises(ValueError, match="does not match TargetSnapshot"):
        catalog.resolve_descriptor(target_ref("another-agent"), value.content_sha256)


def test_catalog_rejects_invalid_descriptor_hash(tmp_path) -> None:
    catalog = TargetCatalog(SQLiteRepository(tmp_path / "catalog-invalid.db"))

    with pytest.raises(ValueError, match="lowercase SHA-256 digest"):
        catalog.resolve_descriptor(target_ref(), "invalid")
