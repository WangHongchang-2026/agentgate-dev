import base64

import pytest

from agentgate.integrations.credentials.environment import (
    API_KEY_ENCRYPTION_KEY_ENV,
    load_api_key_encryptor,
)


MASTER_KEY = bytes(range(32))
ENCODED_KEY = base64.urlsafe_b64encode(MASTER_KEY).decode("ascii")


@pytest.mark.parametrize("encoded", (ENCODED_KEY, ENCODED_KEY.rstrip("=")))
def test_load_api_key_encryptor_accepts_padded_or_unpadded_urlsafe_base64(
    encoded: str,
) -> None:
    encryptor = load_api_key_encryptor({API_KEY_ENCRYPTION_KEY_ENV: encoded})

    encrypted = encryptor.encrypt("provider-key-value")

    assert encryptor.decrypt(encrypted) == "provider-key-value"


def test_load_api_key_encryptor_requires_configuration() -> None:
    with pytest.raises(ValueError) as raised:
        load_api_key_encryptor({})

    assert str(raised.value) == f"{API_KEY_ENCRYPTION_KEY_ENV} is required"


@pytest.mark.parametrize(
    "encoded",
    (
        "",
        "   ",
        "not+urlsafe/base64",
        base64.urlsafe_b64encode(bytes(31)).decode("ascii"),
        base64.urlsafe_b64encode(bytes(33)).decode("ascii"),
    ),
)
def test_load_api_key_encryptor_rejects_invalid_configuration(
    encoded: str,
) -> None:
    with pytest.raises(ValueError) as raised:
        load_api_key_encryptor({API_KEY_ENCRYPTION_KEY_ENV: encoded})

    message = str(raised.value)
    assert message == (
        f"{API_KEY_ENCRYPTION_KEY_ENV} must be URL-safe Base64 "
        "for exactly 32 bytes"
    )
    if encoded:
        assert encoded not in message
