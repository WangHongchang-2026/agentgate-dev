"""OpenAI-compatible Chat Completions transport for LLM Judge models."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

import httpx

from agentgate.evaluator.judge import (
    JudgeModelInvalidResponse,
    JudgeModelTimeout,
    JudgeModelUnavailable,
    JudgeRequest,
    JudgeResponse,
)


OutputTokenField = Literal["max_completion_tokens", "max_tokens"]
RETRYABLE_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})
_OUTPUT_TOKEN_FIELDS = frozenset({"max_completion_tokens", "max_tokens"})


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a nonblank string")
    return value.strip()


def _normalize_base_url(base_url: str, allow_insecure_http: bool) -> str:
    value = _required_text(base_url, "base_url")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    if parsed.scheme == "http" and not allow_insecure_http:
        raise ValueError("base_url must use HTTPS unless insecure HTTP is enabled")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain a query or fragment")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class OpenAICompatibleModelClient:
    """Call a preconfigured OpenAI-compatible Chat Completions endpoint."""

    def __init__(
        self,
        *,
        provider_id: str,
        base_url: str,
        api_key: str | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        output_token_field: OutputTokenField = "max_completion_tokens",
        allow_insecure_http: bool = False,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.provider_id = _required_text(provider_id, "provider_id")
        if not isinstance(allow_insecure_http, bool):
            raise ValueError("allow_insecure_http must be a boolean")
        self.base_url = _normalize_base_url(base_url, allow_insecure_http)
        if api_key is not None:
            api_key = _required_text(api_key, "api_key")
        if (
            isinstance(max_attempts, bool)
            or not isinstance(max_attempts, int)
            or max_attempts < 1
        ):
            raise ValueError("max_attempts must be a positive integer")
        if (
            isinstance(backoff_seconds, bool)
            or not isinstance(backoff_seconds, (int, float))
            or not math.isfinite(float(backoff_seconds))
            or backoff_seconds < 0
        ):
            raise ValueError("backoff_seconds must be a non-negative number")
        if output_token_field not in _OUTPUT_TOKEN_FIELDS:
            raise ValueError(
                "output_token_field must be max_completion_tokens or max_tokens"
            )
        if http_client is not None and not isinstance(http_client, httpx.Client):
            raise TypeError("http_client must be an httpx.Client")

        self.max_attempts = max_attempts
        self.backoff_seconds = float(backoff_seconds)
        self.output_token_field = output_token_field
        self._api_key = api_key
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.Client()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(provider_id={self.provider_id!r}, "
            f"base_url={self.base_url!r})"
        )

    def __enter__(self) -> "OpenAICompatibleModelClient":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP client only when this adapter created it."""

        if self._owns_http_client:
            self._http_client.close()

    def complete(self, request: JudgeRequest) -> JudgeResponse:
        """Execute one bounded Judge completion request."""

        payload = self._request_payload(request)
        headers = {"Content-Type": "application/json"}
        if self._api_key is not None:
            headers["Authorization"] = f"Bearer {self._api_key}"

        started = time.monotonic()
        last_error: JudgeModelTimeout | JudgeModelUnavailable | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self._http_client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=request.timeout_seconds,
                )
            except httpx.TimeoutException:
                last_error = JudgeModelTimeout(
                    f"Judge provider exceeded {request.timeout_seconds:g} seconds"
                )
            except httpx.TransportError:
                last_error = JudgeModelUnavailable("Judge provider is unreachable")
            else:
                if response.status_code in RETRYABLE_STATUSES:
                    last_error = JudgeModelUnavailable(
                        f"Judge provider returned HTTP {response.status_code}"
                    )
                elif response.is_error:
                    raise JudgeModelUnavailable(
                        f"Judge provider returned HTTP {response.status_code}"
                    ) from None
                else:
                    try:
                        response_payload = response.json()
                    except ValueError:
                        raise JudgeModelInvalidResponse(
                            "Judge provider returned a non-JSON body"
                        ) from None
                    latency_ms = (time.monotonic() - started) * 1000
                    return self._parse_response(
                        response_payload,
                        request,
                        latency_ms,
                        attempt,
                    )

            if attempt < self.max_attempts and self.backoff_seconds:
                time.sleep(self.backoff_seconds * attempt)

        if last_error is None:
            raise JudgeModelUnavailable("Judge provider failed")
        raise last_error

    def _request_payload(self, request: JudgeRequest) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system_prompt is not None:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.user_prompt})
        payload: dict[str, Any] = {
            "messages": messages,
            "model": request.model_id,
            "temperature": request.temperature,
        }
        if request.seed is not None:
            payload["seed"] = request.seed
        if request.max_output_tokens is not None:
            payload[self.output_token_field] = request.max_output_tokens
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        return payload

    @staticmethod
    def _parse_response(
        payload: Any,
        request: JudgeRequest,
        latency_ms: float,
        attempt: int,
    ) -> JudgeResponse:
        if not isinstance(payload, Mapping):
            raise JudgeModelInvalidResponse(
                "Judge provider response must be a JSON object"
            )
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise JudgeModelInvalidResponse(
                "Judge provider returned no completion choice"
            )
        choice = choices[0]
        if not isinstance(choice, Mapping):
            raise JudgeModelInvalidResponse(
                "Judge provider returned a malformed completion choice"
            )
        message = choice.get("message")
        if not isinstance(message, Mapping):
            raise JudgeModelInvalidResponse(
                "Judge provider returned a completion without a message"
            )
        text = message.get("content")
        if not isinstance(text, str) or not text.strip():
            raise JudgeModelInvalidResponse(
                "Judge provider returned a completion without text content"
            )
        usage = payload.get("usage") or {}
        if not isinstance(usage, Mapping):
            raise JudgeModelInvalidResponse(
                "Judge provider returned malformed token usage"
            )
        resolved_model = payload.get("model") or request.model_id
        try:
            return JudgeResponse(
                text=text,
                resolved_model_id=resolved_model,
                request_id=payload.get("id"),
                input_tokens=usage.get("prompt_tokens"),
                output_tokens=usage.get("completion_tokens"),
                latency_ms=latency_ms,
                finish_reason=choice.get("finish_reason"),
                attempt_count=attempt,
            )
        except (TypeError, ValueError) as exc:
            raise JudgeModelInvalidResponse(
                "Judge provider returned malformed completion metadata"
            ) from exc


__all__ = [
    "OpenAICompatibleModelClient",
    "OutputTokenField",
    "RETRYABLE_STATUSES",
]
