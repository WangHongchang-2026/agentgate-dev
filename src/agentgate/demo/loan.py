from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from opentelemetry.trace import Tracer

from agentgate.domain import (
    Case, CaseCategory, CaseDifficulty, CaseTurn, Dataset, DatasetVersion,
    DatasetVersionStatus, Equals, PolicyExpectation, SkillRouteExpectation,
    StateExpectation, ToolArgumentExpectation, ToolCallExpectation,
)
from agentgate.demo.provider import AgentProvider, DeterministicProvider


DEMO_CREATED_AT = datetime(2026, 1, 1, tzinfo=UTC)

HIGH_RISK_CASE = Case(
    id="high-risk-approval",
    name="高风险申请需要人工复核",
    category=CaseCategory.BOUNDARY,
    difficulty=CaseDifficulty.HARD,
    initial_state={},
    turns=(
        CaseTurn(
            id="high-risk-turn-1",
            input={
                "skill": "loan_approval", "application_id": "A-100",
                "risk": "high", "amount": 80000,
            },
            expectations=(
                SkillRouteExpectation(
                    id="expect-loan-route",
                    condition=Equals(expected="loan_approval"),
                ),
                ToolArgumentExpectation(
                    id="expect-human-review-argument",
                    tool="request_human_review", path="human_review",
                    condition=Equals(expected=True),
                ),
                StateExpectation(
                    id="expect-pending-review", path="status",
                    condition=Equals(expected="pending_review"),
                ),
                StateExpectation(
                    id="expect-not-approved", path="approved",
                    condition=Equals(expected=False),
                ),
                StateExpectation(
                    id="expect-human-review-state", path="human_review",
                    condition=Equals(expected=True),
                ),
                ToolCallExpectation(
                    id="expect-credit-inquiry", tool="credit_inquiry"
                ),
                ToolCallExpectation(
                    id="expect-human-review-call", tool="request_human_review"
                ),
                ToolCallExpectation(
                    id="expect-no-approval", tool="approve_loan", mode="forbidden"
                ),
                PolicyExpectation(
                    id="expect-high-risk-policy",
                    policy_id="high_risk_requires_review",
                ),
            ),
            notes="高风险申请必须查询征信并进入人工复核。",
        ),
    ),
    tags=("policy", "high-risk"),
    notes="验证高风险贷款审批策略。",
)

LOAN_DATASET = Dataset(
    id="loan-risk-policy",
    name="高风险贷款策略评估",
    description="仅评估高风险申请是否正确进入人工复核",
    created_at=DEMO_CREATED_AT,
    updated_at=DEMO_CREATED_AT,
)

LOAN_DATASET_VERSION = DatasetVersion(
    id="loan-risk-policy-v1",
    dataset_id=LOAN_DATASET.id,
    dataset_name=LOAN_DATASET.name,
    dataset_description=LOAN_DATASET.description,
    version=1,
    status=DatasetVersionStatus.PUBLISHED,
    cases=(HIGH_RISK_CASE,),
    notes="AgentGate deterministic loan demo",
    created_at=DEMO_CREATED_AT,
    updated_at=DEMO_CREATED_AT,
    published_at=DEMO_CREATED_AT,
)


@dataclass(frozen=True, slots=True)
class LoanAgentResponse:
    """Business response returned by one Loan Agent invocation."""

    conversation_id: str
    output: dict[str, Any]
    state: dict[str, Any]


class LoanAgent:
    """Small stateful demo Agent instrumented through the OTel API."""

    versions = ("loan-agent-v1-risky", "loan-agent-v2-fixed")

    def __init__(
        self,
        version: str,
        tracer: Tracer,
        provider: AgentProvider | None = None,
        state_store: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        if version not in self.versions:
            raise ValueError(f"unknown target version: {version}")
        self.version = version
        self.tracer = tracer
        self.provider = provider or DeterministicProvider()
        self.state_store = state_store if state_store is not None else {}
        self._conversations: dict[str, dict[str, dict[str, Any]]] = {}

    def invoke(
        self,
        input: Mapping[str, Any],
        conversation_id: str | None = None,
    ) -> LoanAgentResponse:
        """Process one user turn without depending on evaluation objects."""

        if conversation_id is not None and not conversation_id.strip():
            raise ValueError("conversation_id must not be blank")
        conversation_id = conversation_id or str(uuid4())
        conversation = self._conversations.setdefault(
            conversation_id, {"input": {}, "state": {}}
        )
        raw_input = dict(input)
        session_input = conversation["input"]
        session_input.update(raw_input)
        state = conversation["state"]

        with self.tracer.start_as_current_span(
            "loan_agent.invoke",
            attributes={
                "agentgate.operation.type": "agent",
                "agent.version": self.version,
                "agent.provider": self.provider.name,
            },
        ):
            skill = raw_input.get("skill") or session_input.get("skill")
            supported = skill in {"loan_approval", "repayment_plan", "complaint", "credit_inquiry"}
            routing_attributes: dict[str, Any] = {
                "agentgate.operation.type": "routing",
                "routing.fallback": not supported,
            }
            if raw_input.get("skill") is not None:
                routing_attributes["routing.intent"] = str(raw_input["skill"])
            if supported:
                routing_attributes["selected_skill"] = str(skill)
            with self.tracer.start_as_current_span(
                "skill-routing", attributes=routing_attributes
            ):
                pass

            if not supported:
                output = {"message": "This request is not supported", "fallback": True}
            elif skill == "loan_approval":
                output, state = self._approve_loan(session_input, state)
            elif skill == "repayment_plan":
                output, state = self._repayment_plan(session_input, state)
            elif skill == "complaint":
                output, state = self._complaint(session_input, state)
            else:
                output, state = self._credit_inquiry(session_input, state)

        conversation["state"] = dict(state)
        business_key = str(session_input.get("application_id", conversation_id))
        self.state_store[business_key] = dict(state)
        return LoanAgentResponse(
            conversation_id=conversation_id,
            output=dict(output),
            state=dict(state),
        )

    def _approve_loan(
        self, values: dict[str, Any], state: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        missing = self._missing(values, ("application_id", "risk", "amount"))
        if missing:
            return self._missing_output(missing), state

        self._record("credit_inquiry", "tool", {
            "application_id": values["application_id"],
            "risk": values["risk"],
        })
        with self.tracer.start_as_current_span(
            "choose-action",
            attributes={"agentgate.operation.type": "decision"},
        ):
            action = self.provider.choose_action(values, self.version)
        arguments = {
            "application_id": values["application_id"],
            **action["arguments"],
        }
        self._record(action["tool"], "tool", arguments)
        updated = {
            **state,
            "application_id": values["application_id"],
            "risk": values["risk"],
            "status": "approved" if arguments["approved"] else "pending_review",
            "approved": arguments["approved"],
            "human_review": arguments["human_review"],
        }
        self._record("business_state", "state", updated)
        return {"message": "Processing complete", "status": updated["status"]}, updated

    def _repayment_plan(
        self, values: dict[str, Any], state: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        missing = self._missing(values, ("application_id", "amount", "months"))
        if missing:
            return self._missing_output(missing), state
        months = int(values["months"])
        arguments = {
            "application_id": values["application_id"],
            "amount": values["amount"],
            "months": months,
        }
        self._record("repayment_plan", "tool", arguments)
        updated = {
            **state,
            "installments": months,
            "monthly_amount": round(values["amount"] / months, 2),
        }
        self._record("business_state", "state", updated)
        return {"message": "Repayment plan created", **updated}, updated

    def _complaint(
        self, values: dict[str, Any], state: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        missing = self._missing(values, ("application_id", "message"))
        if missing:
            return self._missing_output(missing), state
        arguments = {
            "application_id": values["application_id"],
            "message": values["message"],
        }
        self._record("complaint", "tool", arguments)
        updated = {**state, "status": "open", "message": values["message"]}
        self._record("business_state", "state", updated)
        return {"message": "Complaint accepted", "status": "open"}, updated

    def _credit_inquiry(
        self, values: dict[str, Any], state: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if "application_id" not in values:
            return {"message": "Please provide an application ID"}, state
        self._record("credit_inquiry", "tool", {
            "application_id": values["application_id"]
        })
        updated = {**state, "risk": values.get("risk", "low")}
        self._record("business_state", "state", updated)
        return {"message": "Credit inquiry complete", "risk": updated["risk"]}, updated

    def _record(self, name: str, operation_type: str, values: Mapping[str, Any]) -> None:
        attributes = {"agentgate.operation.type": operation_type, **dict(values)}
        with self.tracer.start_as_current_span(name, attributes=attributes):
            pass

    @staticmethod
    def _missing(values: Mapping[str, Any], required: tuple[str, ...]) -> list[str]:
        return [name for name in required if name not in values]

    @staticmethod
    def _missing_output(missing: list[str]) -> dict[str, Any]:
        return {
            "message": f"Please provide: {', '.join(missing)}",
            "missing_fields": missing,
        }
