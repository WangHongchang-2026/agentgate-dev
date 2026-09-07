"""Model-provider boundary for dataset generation."""

from __future__ import annotations

from typing import Protocol

from .models import ModelGenerationRequest, ModelGenerationResponse


class GenerationModel(Protocol):
    def generate(self, request: ModelGenerationRequest) -> ModelGenerationResponse: ...
