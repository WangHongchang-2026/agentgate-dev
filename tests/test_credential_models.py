from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agentgate.domain.credential import ApiKeyMetadata, ApiKeyScope


def test_api_key_metadata_is_secret_free_and_serializable() -> None:
    metadata = ApiKeyMetadata(
        id="credential-1",
        name="Shared judge key",
        provider_id="company-llm",
        scope=ApiKeyScope.SHARED,
    )

    assert metadata.model_dump(mode="json") == {
        "id": "credential-1",
        "name": "Shared judge key",
        "provider_id": "company-llm",
        "scope": "shared",
        "created_at": metadata.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": metadata.updated_at.isoformat().replace("+00:00", "Z"),
    }
    assert "key" not in metadata.model_dump()


@pytest.mark.parametrize("field", ("id", "name", "provider_id"))
def test_api_key_metadata_rejects_blank_identity(field: str) -> None:
    values = {
        "id": "credential-1",
        "name": "Private agent key",
        "provider_id": "company-llm",
        "scope": ApiKeyScope.PRIVATE,
    }
    values[field] = "   "

    with pytest.raises(ValidationError, match=f"ApiKeyMetadata {field}"):
        ApiKeyMetadata(**values)


def test_api_key_metadata_normalizes_timestamps_and_rejects_invalid_order() -> None:
    offset = timezone(timedelta(hours=8))
    metadata = ApiKeyMetadata(
        name="Private agent key",
        provider_id="company-llm",
        scope=ApiKeyScope.PRIVATE,
        created_at=datetime(2026, 9, 9, 8, tzinfo=offset),
        updated_at=datetime(2026, 9, 9, 9, tzinfo=offset),
    )

    assert metadata.created_at == datetime(2026, 9, 9, tzinfo=UTC)
    assert metadata.updated_at == datetime(2026, 9, 9, 1, tzinfo=UTC)

    with pytest.raises(ValidationError, match="must not precede"):
        ApiKeyMetadata(
            name="Private agent key",
            provider_id="company-llm",
            scope=ApiKeyScope.PRIVATE,
            created_at=datetime(2026, 9, 9, 1, tzinfo=UTC),
            updated_at=datetime(2026, 9, 9, tzinfo=UTC),
        )


def test_api_key_metadata_rejects_naive_timestamps_and_secret_fields() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        ApiKeyMetadata(
            name="Private agent key",
            provider_id="company-llm",
            scope=ApiKeyScope.PRIVATE,
            created_at=datetime(2026, 9, 9),
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ApiKeyMetadata(
            name="Private agent key",
            provider_id="company-llm",
            scope=ApiKeyScope.PRIVATE,
            api_key="plaintext-secret",
        )


def test_api_key_metadata_is_immutable() -> None:
    metadata = ApiKeyMetadata(
        name="Shared judge key",
        provider_id="company-llm",
        scope=ApiKeyScope.SHARED,
    )

    with pytest.raises(ValidationError, match="Instance is frozen"):
        metadata.name = "Changed"  # type: ignore[misc]
