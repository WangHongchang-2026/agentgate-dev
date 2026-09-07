"""Synthetic evaluation-case generation primitives."""

from .blueprint import case_from_blueprint, parse_blueprint_response
from .dedup import case_functional_fingerprint
from .models import (
    CandidateIssue,
    CandidateValidation,
    CategoryCounts,
    DifficultyCounts,
    GeneratedBlueprintBatch,
    GeneratedBatch,
    GeneratedCaseBlueprint,
    GeneratedCaseDraft,
    GeneratedCandidate,
    GeneratedToolCallBlueprint,
    GeneratedTurnBlueprint,
    GenerationModelProfile,
    GenerationRequest,
    GenerationResult,
    GenerationSlot,
    ModelGenerationRequest,
    ModelGenerationResponse,
    ReferenceSource,
    TurnCounts,
    TurnMode,
)
from .parser import parse_generated_response
from .protocol import GenerationModel
from .recipe import RECIPE_VERSION, build_generation_slots, build_model_request

__all__ = [name for name in globals() if not name.startswith("_")]
