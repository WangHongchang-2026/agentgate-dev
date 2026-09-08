"""Runtime boundary between Judge evaluators and model-provider integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from agentgate.domain import content_sha256


ResponseFormat = Literal["text", "json_object"]


class JudgeModelError(Exception):
    """Base class for normalized Judge model failures."""


class JudgeModelTimeout(JudgeModelError, TimeoutError):
    """The provider did not complete the request before its deadline."""


class JudgeModelInvalidResponse(JudgeModelError, ValueError):
    """The provider returned an unusable completion envelope."""


class JudgeModelUnavailable(JudgeModelError):
    """The provider could not complete the request."""


class CredentialUnavailable(JudgeModelError):
    """A configured credential reference could not be resolved."""


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must not be blank")


def _validate_optional_text(value: str | None, field_name: str) -> None:
    if value is not None:
        _require_text(value, field_name)


def _validate_optional_count(value: int | None, field_name: str) -> None:
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError(f"{field_name} must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class JudgeRequest:
    """One secret-free, provider-neutral Judge completion request."""

    model_id: str
    user_prompt: str
    system_prompt: str | None = None
    temperature: float = 0.0
    seed: int | None = None
    max_output_tokens: int | None = None
    response_format: ResponseFormat = "json_object"
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        _require_text(self.model_id, "model_id")
        _require_text(self.user_prompt, "user_prompt")
        _validate_optional_text(self.system_prompt, "system_prompt")
        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not 0 <= self.temperature <= 2
        ):
            raise ValueError("temperature must be between 0 and 2")
        if self.seed is not None and (
            isinstance(self.seed, bool) or not isinstance(self.seed, int)
        ):
            raise ValueError("seed must be an integer")
        if self.max_output_tokens is not None and (
            isinstance(self.max_output_tokens, bool)
            or not isinstance(self.max_output_tokens, int)
            or self.max_output_tokens < 1
        ):
            raise ValueError("max_output_tokens must be a positive integer")
        if self.response_format not in ("text", "json_object"):
            raise ValueError("response_format must be text or json_object")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive")


def request_fingerprint(request: JudgeRequest) -> str:
    """Hash the semantic request fields used to produce a completion."""

    return content_sha256(
        {
            "model_id": request.model_id,
            "system_prompt": request.system_prompt,
            "user_prompt": request.user_prompt,
            "temperature": request.temperature,
            "seed": request.seed,
            "max_output_tokens": request.max_output_tokens,
            "response_format": request.response_format,
        }
    )


@dataclass(frozen=True, slots=True)
class JudgeResponse:
    """Normalized completion content and accounting returned by a provider."""

    text: str
    resolved_model_id: str
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: float | None = None
    finish_reason: str | None = None
    attempt_count: int = 1

    def __post_init__(self) -> None:
        _require_text(self.text, "text")
        _require_text(self.resolved_model_id, "resolved_model_id")
        _validate_optional_text(self.request_id, "request_id")
        _validate_optional_count(self.input_tokens, "input_tokens")
        _validate_optional_count(self.output_tokens, "output_tokens")
        if self.latency_ms is not None and (
            isinstance(self.latency_ms, bool)
            or not isinstance(self.latency_ms, (int, float))
            or self.latency_ms < 0
        ):
            raise ValueError("latency_ms must be non-negative")
        _validate_optional_text(self.finish_reason, "finish_reason")
        if (
            isinstance(self.attempt_count, bool)
            or not isinstance(self.attempt_count, int)
            or self.attempt_count < 1
        ):
            raise ValueError("attempt_count must be at least 1")

    @property
    def truncated(self) -> bool:
        return self.finish_reason == "length"


@runtime_checkable
class JudgeModelClient(Protocol):
    """Provider-neutral completion interface consumed by Judge evaluators."""

    provider_id: str

    def complete(self, request: JudgeRequest) -> JudgeResponse: ...


__all__ = [
    "CredentialUnavailable",
    "JudgeModelClient",
    "JudgeModelError",
    "JudgeModelInvalidResponse",
    "JudgeModelTimeout",
    "JudgeModelUnavailable",
    "JudgeRequest",
    "JudgeResponse",
    "ResponseFormat",
    "request_fingerprint",
]
