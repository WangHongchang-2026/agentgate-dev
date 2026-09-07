"""Deterministic model provider for tests and local contract checks."""

from __future__ import annotations

from collections.abc import Callable

from .models import ModelGenerationRequest, ModelGenerationResponse


class FakeGenerationModel:
    def __init__(self, response: str | Callable[[ModelGenerationRequest], str]) -> None:
        self.response = response
        self.requests: list[ModelGenerationRequest] = []

    def credential_available(self, _profile) -> bool:
        return True

    def generate(self, request: ModelGenerationRequest) -> ModelGenerationResponse:
        self.requests.append(request)
        content = self.response(request) if callable(self.response) else self.response
        return ModelGenerationResponse(
            content=content,
            request_id="fake-request-1",
            response_model="fake-model-v1",
        )
