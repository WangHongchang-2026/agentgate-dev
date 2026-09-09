import pytest

from agentgate.integrations.credentials.encryption import (
    ApiKeyEncryptionError,
    ApiKeyEncryptor,
)


MASTER_KEY = bytes(range(32))


def test_api_key_encryption_round_trip_preserves_exact_plaintext() -> None:
    encryptor = ApiKeyEncryptor(MASTER_KEY)

    encrypted = encryptor.encrypt("  provider-key-value  ")

    assert encrypted.startswith("v1.")
    assert "provider-key-value" not in encrypted
    assert encryptor.decrypt(encrypted) == "  provider-key-value  "


def test_api_key_encryption_uses_a_fresh_nonce() -> None:
    encryptor = ApiKeyEncryptor(MASTER_KEY)

    first = encryptor.encrypt("provider-key-value")
    second = encryptor.encrypt("provider-key-value")

    assert first != second
    assert encryptor.decrypt(first) == encryptor.decrypt(second)


@pytest.mark.parametrize("master_key", (b"", b"short", bytes(31), bytes(33), "x" * 32))
def test_api_key_encryptor_requires_a_32_byte_master_key(master_key: object) -> None:
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        ApiKeyEncryptor(master_key)  # type: ignore[arg-type]


@pytest.mark.parametrize("plaintext", ("", "   ", None))
def test_api_key_encryption_rejects_blank_plaintext(plaintext: object) -> None:
    with pytest.raises(ValueError, match="nonblank string"):
        ApiKeyEncryptor(MASTER_KEY).encrypt(plaintext)  # type: ignore[arg-type]


def test_api_key_decryption_has_one_safe_failure_for_invalid_material() -> None:
    encryptor = ApiKeyEncryptor(MASTER_KEY)
    encrypted = encryptor.encrypt("provider-key-value")
    replacement = "A" if encrypted[-1] != "A" else "B"
    invalid_values = (
        "",
        "v2.not-supported",
        "v1.not-valid-base64!",
        "v1.AA",
        encrypted[:-1] + replacement,
    )

    for value in invalid_values:
        with pytest.raises(ApiKeyEncryptionError) as raised:
            encryptor.decrypt(value)
        assert str(raised.value) == "encrypted API Key cannot be decrypted"
        if value:
            assert value not in str(raised.value)


def test_api_key_decryption_rejects_a_different_master_key_without_leaking_data() -> None:
    encrypted = ApiKeyEncryptor(MASTER_KEY).encrypt("top-secret-provider-key")

    with pytest.raises(ApiKeyEncryptionError) as raised:
        ApiKeyEncryptor(bytes(reversed(MASTER_KEY))).decrypt(encrypted)

    assert "top-secret-provider-key" not in str(raised.value)
    assert encrypted not in str(raised.value)


def test_api_key_encryptor_repr_redacts_key_material() -> None:
    encryptor = ApiKeyEncryptor(MASTER_KEY)

    assert repr(encryptor) == "ApiKeyEncryptor(<redacted>)"
    assert MASTER_KEY.hex() not in repr(encryptor)
