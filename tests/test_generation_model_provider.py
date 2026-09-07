import json

import httpx
import pytest

from agentgate.case.generation.models import ModelGenerationRequest
from agentgate.integrations.model_providers.openai_compatible import (
    GenerationProviderError,
    OpenAICompatibleGenerationModel,
    bailian_default_profile,
)
from agentgate.integrations.model_providers.credentials import RuntimeCredentialStore


def _request():
    return ModelGenerationRequest(
        system_prompt="system",
        user_payload={"target": {"name": "fake"}},
        response_schema={
            "type": "object",
            "properties": {"cases": {"type": "array", "items": {"type": "object"}}},
            "required": ["cases"],
            "additionalProperties": False,
        },
        profile=bailian_default_profile(),
    )


def test_openai_compatible_provider_sends_strict_schema_without_max_tokens():
    captured = {}

    def handler(request: httpx.Request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            headers={"x-request-id": "req-1"},
            json={
                "id": "completion-1",
                "model": "qwen3.7-plus",
                "choices": [{"message": {"content": '{"cases":[]}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3},
            },
        )

    transport = httpx.MockTransport(handler)
    model = OpenAICompatibleGenerationModel(
        credential_lookup=lambda _: "secret",
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs),
    )
    response = model.generate(_request())
    assert response.request_id == "req-1"
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert "max_tokens" not in captured
    assert captured["enable_thinking"] is False
    assert captured["model"] == "qwen3.7-plus"


def test_provider_validates_credential_without_exposing_it():
    captured = {}

    def handler(request: httpx.Request):
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"x-request-id": "validate-1"}, json={})

    transport = httpx.MockTransport(handler)
    model = OpenAICompatibleGenerationModel(
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs),
    )
    request_id = model.validate_credential(bailian_default_profile(), "secret-api-key")

    assert request_id == "validate-1"
    assert captured["authorization"] == "Bearer secret-api-key"
    assert captured["body"]["max_tokens"] == 1
    assert "secret-api-key" not in json.dumps(captured["body"])


def test_runtime_credential_store_prefers_memory_and_can_restore_environment_fallback():
    store = RuntimeCredentialStore(fallback=lambda _: "environment-key")
    assert store.get("DASHSCOPE_API_KEY") == "environment-key"
    store.set("DASHSCOPE_API_KEY", "runtime-key")
    assert store.get("DASHSCOPE_API_KEY") == "runtime-key"
    assert store.has_runtime_value("DASHSCOPE_API_KEY") is True
    store.delete("DASHSCOPE_API_KEY")
    assert store.get("DASHSCOPE_API_KEY") == "environment-key"
    assert store.has_runtime_value("DASHSCOPE_API_KEY") is False


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(401, "provider_authentication_failed", False), (429, "provider_rate_limited", True)],
)
def test_provider_maps_bounded_errors(status, code, retryable):
    transport = httpx.MockTransport(lambda _: httpx.Response(status, text="sensitive upstream"))
    model = OpenAICompatibleGenerationModel(
        credential_lookup=lambda _: "secret",
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs),
    )
    with pytest.raises(GenerationProviderError) as exc:
        model.generate(_request())
    assert exc.value.code == code
    assert exc.value.retryable is retryable
    assert "sensitive upstream" not in str(exc.value)


def test_provider_requires_credential_before_http_call():
    model = OpenAICompatibleGenerationModel(credential_lookup=lambda _: None)
    with pytest.raises(GenerationProviderError) as exc:
        model.generate(_request())
    assert exc.value.code == "provider_credential_unavailable"


def test_provider_retries_one_transient_failure_without_logging_payload(caplog):
    calls = 0

    def handler(_: httpx.Request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, text="private upstream payload")
        return httpx.Response(
            200,
            json={
                "model": "qwen3.7-plus",
                "choices": [{"message": {"content": '{"cases":[]}'}}],
            },
        )

    transport = httpx.MockTransport(handler)
    model = OpenAICompatibleGenerationModel(
        credential_lookup=lambda _: "secret-key",
        client_factory=lambda **kwargs: httpx.Client(transport=transport, **kwargs),
        sleep=lambda _: None,
    )
    response = model.generate(_request())

    assert calls == 2
    assert response.content == '{"cases":[]}'
    assert "secret-key" not in caplog.text
    assert "private upstream payload" not in caplog.text
