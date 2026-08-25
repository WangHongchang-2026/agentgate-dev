"""Public AgentGate domain data models."""

from .base import DomainModel, FrozenJsonObject, canonical_json, content_sha256, freeze_json
from .case import (
    Case, CaseCategory, CaseDifficulty, CaseProvenance, CaseTurn, Dataset,
    DatasetPurpose, DatasetVersion, DatasetVersionStatus,
)
from .evaluation import (
    ChildRef, Dimension, EvaluatorSpec, HybridEvaluatorSpec, JudgeConfig, JudgeEvidence,
    Kind, LlmJudgeEvaluatorSpec, MethodRef, PromptSnapshot, RubricSnapshot,
    RuleEvaluatorSpec, Severity,
)
from .expectation import (
    Condition, Equals, Expectation, MatchesJsonSchema, MatchesPattern, MustBeMissing,
    OneOf, OutputExpectation, StateExpectation, ToolArgumentExpectation, WithinRange,
    WithinTolerance,
)
from .gate import GateDecision, GateSpec
from .metric import MetricPlan, MetricSummary
from .report import RunReport
from .result import (
    CheckResult, EvaluationErrorEvidence, Evidence, FailureObservation, FailureStage,
    Outcome, Result,
)
from .run import Run, RunSnapshot, RunStatus, TargetSnapshot
from .trace import SpanKind, Trace, TraceSpan, TraceTurn

__all__ = [name for name in globals() if not name.startswith("_")]
