from __future__ import annotations

import json

import httpx
import pytest

from agentgate.evaluator.judge import (
    JudgeModelInvalidResponse,
    JudgeModelTimeout,
    JudgeModelUnavailable,
    JudgeRequest,
)
from agentgate.integrations.model_providers.openai_compatible import (
    OpenAICompatibleModelClient,
)


def request() -> JudgeRequest:
    return JudgeRequest(
        model_id="judge-model",
        system_prompt="Judge carefully.",
        user_prompt="Evaluate this.",
        temperature=0.2,
        seed=7,
        max_output_tokens=500,
        response_format="json_object",
        timeout_seconds=3,
    )


def completion_response(**overrides):
    payload = {
        "id": "request-1",
        "model": "resolved-model",
        "choices": [
            {
                "message": {"content": '{"verdict":"pass"}'},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
    }
    payload.update(overrides)
    return payload


def client_with_handler(handler, **overrides):
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleModelClient(
        provider_id="company-llm",
        base_url="https://models.example/v1/",
        api_key="top-secret",
        http_client=http_client,
        **overrides,
    )
    return client, http_client


def test_sends_chat_completion_and_parses_provenance() -> None:
    captured = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        captured["request"] = http_request
        return httpx.Response(200, json=completion_response())

    client, http_client = client_with_handler(handler)

    response = client.complete(request())

    sent = captured["request"]
    assert sent.url == "https://models.example/v1/chat/completions"
    assert sent.headers["authorization"] == "Bearer top-secret"
    payload = json.loads(sent.content)
    assert payload == {
        "messages": [
            {"role": "system", "content": "Judge carefully."},
            {"role": "user", "content": "Evaluate this."},
        ],
        "model": "judge-model",
        "temperature": 0.2,
        "seed": 7,
        "max_completion_tokens": 500,
        "response_format": {"type": "json_object"},
    }
    assert response.text == '{"verdict":"pass"}'
    assert response.resolved_model_id == "resolved-model"
    assert response.request_id == "request-1"
    assert response.input_tokens == 12
    assert response.output_tokens == 4
    assert response.finish_reason == "stop"
    assert response.attempt_count == 1
    assert response.latency_ms is not None

    client.close()
    assert http_client.is_closed is False
    http_client.close()


def test_supports_legacy_token_field_and_unauthenticated_private_endpoint() -> None:
    captured = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        captured["request"] = http_request
        return httpx.Response(200, json=completion_response())

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = OpenAICompatibleModelClient(
        provider_id="local",
        base_url="http://127.0.0.1:8000/v1",
        allow_insecure_http=True,
        output_token_field="max_tokens",
        http_client=http_client,
    )

    client.complete(request())

    sent = captured["request"]
    assert "authorization" not in sent.headers
    payload = json.loads(sent.content)
    assert payload["max_tokens"] == 500
    assert "max_completion_tokens" not in payload
    http_client.close()


def test_retries_retryable_status_then_returns_success() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": {"message": "secret body"}})
        return httpx.Response(200, json=completion_response())

    client, http_client = client_with_handler(
        handler,
        max_attempts=2,
        backoff_seconds=0,
    )

    response = client.complete(request())

    assert calls == 2
    assert response.attempt_count == 2
    http_client.close()


def test_exhausted_timeout_is_normalized() -> None:
    calls = 0

    def handler(http_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("secret timeout", request=http_request)

    client, http_client = client_with_handler(
        handler,
        max_attempts=2,
        backoff_seconds=0,
    )

    with pytest.raises(JudgeModelTimeout, match="3 seconds"):
        client.complete(request())

    assert calls == 2
    http_client.close()


def test_exhausted_retryable_http_status_is_unavailable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="secret response body")

    client, http_client = client_with_handler(
        handler,
        max_attempts=1,
        backoff_seconds=0,
    )

    with pytest.raises(JudgeModelUnavailable, match="HTTP 503") as raised:
        client.complete(request())

    assert "secret response body" not in str(raised.value)
    http_client.close()


def test_does_not_retry_nonretryable_http_error() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, text="top-secret")

    client, http_client = client_with_handler(
        handler,
        max_attempts=3,
        backoff_seconds=0,
    )

    with pytest.raises(JudgeModelUnavailable, match="HTTP 401") as raised:
        client.complete(request())

    assert calls == 1
    assert "top-secret" not in str(raised.value)
    http_client.close()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{}]}),
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": ""}}],
                "usage": {},
            },
        ),
        httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "result"}}],
                "usage": "bad",
            },
        ),
    ],
)
def test_rejects_malformed_responses_without_retry(
    response: httpx.Response,
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return response

    client, http_client = client_with_handler(
        handler,
        max_attempts=3,
        backoff_seconds=0,
    )

    with pytest.raises(JudgeModelInvalidResponse):
        client.complete(request())

    assert calls == 1
    http_client.close()


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"provider_id": " "}, "provider_id"),
        ({"base_url": "models.example/v1"}, "absolute HTTP"),
        ({"base_url": "http://models.example/v1"}, "must use HTTPS"),
        ({"base_url": "https://user:pass@models.example/v1"}, "credentials"),
        ({"base_url": "https://models.example/v1?key=value"}, "query or fragment"),
        ({"max_attempts": 0}, "max_attempts"),
        ({"backoff_seconds": -1}, "backoff_seconds"),
        ({"output_token_field": "tokens"}, "output_token_field"),
    ],
)
def test_rejects_invalid_configuration(arguments, message) -> None:
    defaults = {
        "provider_id": "provider",
        "base_url": "https://models.example/v1",
    }
    defaults.update(arguments)

    with pytest.raises((TypeError, ValueError), match=message):
        OpenAICompatibleModelClient(**defaults)


def test_repr_never_contains_api_key() -> None:
    client = OpenAICompatibleModelClient(
        provider_id="provider",
        base_url="https://models.example/v1",
        api_key="top-secret",
    )

    rendered = repr(client)

    assert "top-secret" not in rendered
    assert "provider" in rendered
    client.close()
