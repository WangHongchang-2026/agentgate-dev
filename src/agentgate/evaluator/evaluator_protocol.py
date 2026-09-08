"""Runtime contracts implemented by evaluator mechanisms."""

from __future__ import annotations

from typing import ClassVar, Protocol, TypeAlias

from agentgate.domain import Case, CaseTurn, EvaluatorKind, EvaluatorSpec, Trace

from .models import Evaluation, ResultResolver


class _EvaluatorIdentityProtocol(Protocol):
    """Versioned identity shared by evaluator execution mechanisms."""

    kind: ClassVar[EvaluatorKind]
    implementation_id: ClassVar[str]
    implementation_version: ClassVar[str]


class TurnEvaluatorProtocol(_EvaluatorIdentityProtocol, Protocol):
    """Execution boundary for evaluators that inspect one Case turn at a time."""

    def applies_to(self, spec: EvaluatorSpec, turn: CaseTurn) -> bool: ...

    def evaluate(
        self,
        spec: EvaluatorSpec,
        turn: CaseTurn,
        trace: Trace,
        resolve: ResultResolver,
    ) -> Evaluation: ...


class CaseEvaluatorProtocol(_EvaluatorIdentityProtocol, Protocol):
    """Execution boundary for evaluators that inspect one complete Case."""

    def evaluate_case(
        self,
        spec: EvaluatorSpec,
        case: Case,
        trace: Trace,
        resolve: ResultResolver,
    ) -> Evaluation: ...


EvaluatorProtocol: TypeAlias = TurnEvaluatorProtocol | CaseEvaluatorProtocol


__all__ = ["CaseEvaluatorProtocol", "EvaluatorProtocol", "TurnEvaluatorProtocol"]
