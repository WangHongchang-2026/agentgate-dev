"""Bounded OpenAI-compatible adapter used by dataset generation."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx

from agentgate.case.generation.models import (
    GenerationModelProfile,
    ModelGenerationRequest,
    ModelGenerationResponse,
)
from agentgate.domain.base import thaw_json

MAX_PROVIDER_RESPONSE_BYTES = 2 * 1024 * 1024
_TRANSIENT_CODES = {"provider_timeout", "provider_unavailable", "provider_rate_limited"}
logger = logging.getLogger(__name__)


class GenerationProviderError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        request_id: str | None = None,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.request_id = request_id
        super().__init__(message)


def bailian_default_profile() -> GenerationModelProfile:
    return GenerationModelProfile(
        id="dataset-generator-default",
        display_name="阿里百炼 Qwen3.7 Plus",
        provider="openai-compatible",
        model="qwen3.7-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        credential_ref="DASHSCOPE_API_KEY",
        temperature=0.4,
        timeout_seconds=60,
        max_concurrent_requests=2,
    )


class OpenAICompatibleGenerationModel:
    def __init__(
        self,
        credential_lookup: Callable[[str], str | None] = os.getenv,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._credential_lookup = credential_lookup
        self._client_factory = client_factory
        self._sleep = sleep
        self._semaphores: dict[str, threading.BoundedSemaphore] = {}
        self._lock = threading.Lock()

    def credential_available(self, profile: GenerationModelProfile) -> bool:
        return bool(self._credential_lookup(profile.credential_ref))

    def validate_credential(
        self, profile: GenerationModelProfile, api_key: str
    ) -> str | None:
        """Validate a credential with a minimal provider request before storing it."""
        body = {
            "model": profile.model,
            "enable_thinking": False,
            "messages": [{"role": "user", "content": "Reply with OK."}],
            "temperature": 0,
            "max_tokens": 1,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        url = f"{profile.base_url.rstrip('/')}/chat/completions"
        try:
            with self._client_factory(timeout=profile.timeout_seconds) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise GenerationProviderError(
                "provider_timeout", "模型凭据验证超时", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise GenerationProviderError(
                "provider_unavailable", "模型服务连接失败", retryable=True
            ) from exc
        request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        self._raise_response_error(response, request_id, action="验证")
        return request_id

    def _semaphore(self, profile: GenerationModelProfile) -> threading.BoundedSemaphore:
        with self._lock:
            return self._semaphores.setdefault(
                profile.id, threading.BoundedSemaphore(profile.max_concurrent_requests)
            )

    def generate(self, request: ModelGenerationRequest) -> ModelGenerationResponse:
        profile = request.profile
        api_key = self._credential_lookup(profile.credential_ref)
        if not api_key:
            raise GenerationProviderError(
                "provider_credential_unavailable",
                f"模型凭据 {profile.credential_ref} 未配置",
                retryable=False,
            )
        semaphore = self._semaphore(profile)
        if not semaphore.acquire(blocking=False):
            raise GenerationProviderError(
                "generation_capacity_exceeded",
                "生成服务当前并发已满，请稍后重试",
                retryable=True,
            )
        try:
            started = time.monotonic()
            for attempt in range(2):
                try:
                    response = self._send(request, api_key)
                    logger.info(
                        "dataset generation provider completed",
                        extra={
                            "provider": profile.provider,
                            "model": profile.model,
                            "request_id": response.request_id,
                            "attempt": attempt + 1,
                            "elapsed_ms": round((time.monotonic() - started) * 1000),
                            "prompt_tokens": response.prompt_tokens,
                            "completion_tokens": response.completion_tokens,
                        },
                    )
                    return response
                except GenerationProviderError as exc:
                    if attempt == 0 and exc.retryable and exc.code in _TRANSIENT_CODES:
                        self._sleep(0.2)
                        continue
                    logger.warning(
                        "dataset generation provider failed",
                        extra={
                            "provider": profile.provider,
                            "model": profile.model,
                            "request_id": exc.request_id,
                            "error_code": exc.code,
                            "attempt": attempt + 1,
                            "elapsed_ms": round((time.monotonic() - started) * 1000),
                        },
                    )
                    raise
            raise AssertionError("unreachable provider retry state")
        finally:
            semaphore.release()

    def _send(self, request: ModelGenerationRequest, api_key: str) -> ModelGenerationResponse:
        profile = request.profile
        body = {
            "model": profile.model,
            "enable_thinking": False,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        thaw_json(request.user_payload), ensure_ascii=False, separators=(",", ":")
                    ),
                },
            ],
            "temperature": profile.temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "agentgate_generated_cases",
                    "strict": True,
                    "schema": thaw_json(request.response_schema),
                },
            },
        }
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        url = f"{profile.base_url.rstrip('/')}/chat/completions"
        try:
            with self._client_factory(timeout=profile.timeout_seconds) as client:
                response = client.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise GenerationProviderError(
                "provider_timeout", "模型服务调用超时", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise GenerationProviderError(
                "provider_unavailable", "模型服务连接失败", retryable=True
            ) from exc
        request_id = response.headers.get("x-request-id") or response.headers.get("request-id")
        self._raise_response_error(response, request_id, action="生成")
        if len(response.content) > MAX_PROVIDER_RESPONSE_BYTES:
            raise GenerationProviderError(
                "provider_response_too_large",
                "模型响应超过大小限制",
                retryable=False,
                request_id=request_id,
            )
        try:
            payload: dict[str, Any] = response.json()
            choice = payload["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message content is not text")
            usage = payload.get("usage") or {}
            return ModelGenerationResponse(
                content=content,
                request_id=request_id or payload.get("id"),
                response_model=payload.get("model"),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise GenerationProviderError(
                "provider_invalid_response",
                "模型服务返回了无法解析的响应",
                retryable=False,
                request_id=request_id,
            ) from exc

    @staticmethod
    def _raise_response_error(
        response: httpx.Response,
        request_id: str | None,
        *,
        action: str,
    ) -> None:
        if response.status_code == 429:
            raise GenerationProviderError(
                "provider_rate_limited", "模型服务限流", retryable=True, request_id=request_id
            )
        if response.status_code in (401, 403):
            raise GenerationProviderError(
                "provider_authentication_failed",
                "模型服务鉴权失败",
                retryable=False,
                request_id=request_id,
            )
        if response.status_code >= 500:
            raise GenerationProviderError(
                "provider_unavailable",
                "模型服务暂时不可用",
                retryable=True,
                request_id=request_id,
            )
        if response.status_code >= 400:
            raise GenerationProviderError(
                "provider_request_rejected",
                f"模型服务拒绝了{action}请求",
                retryable=False,
                request_id=request_id,
            )
