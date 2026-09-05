"""Evaluator execution interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from agentgate.domain import CaseTurn, EvaluatorSpec, EvaluatorKind, Trace

from .models import Evaluation, ResultResolver


class Evaluator(ABC):
    kind: ClassVar[EvaluatorKind]
    implementation_id: ClassVar[str]

    def applies_to(self, spec: EvaluatorSpec, turn: CaseTurn) -> bool:
        return True

    @abstractmethod
    def evaluate(
        self, spec: EvaluatorSpec, turn: CaseTurn, trace: Trace, resolve: ResultResolver
    ) -> Evaluation:
        raise NotImplementedError
