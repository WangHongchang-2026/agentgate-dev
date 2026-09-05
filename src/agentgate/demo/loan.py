from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agentgate.domain import (
    Case, CaseCategory, CaseDifficulty, CaseTurn, Dataset, DatasetVersion,
    DatasetVersionStatus, Equals, PolicyExpectation, SkillRouteExpectation,
    StateExpectation, ToolArgumentExpectation, ToolCallExpectation,
    Trace, TraceSpan
)
from agentgate.demo.provider import AgentProvider, DeterministicProvider
from agentgate.storage.base import AgentGateRepository


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


class LoanAgent:
    versions = ("loan-agent-v1-risky", "loan-agent-v2-fixed")

    def __init__(self, repository: AgentGateRepository, provider: AgentProvider | None = None) -> None:
        self.repository = repository
        self.provider = provider or DeterministicProvider()

    @staticmethod
    def _span(
        trace_id: str, sequence: int, turn_id: str, name: str,
        operation_type: str, **attributes: Any,
    ) -> TraceSpan:
        return TraceSpan(
            trace_id=trace_id,
            span_id=uuid4().hex[:16],
            sequence=sequence,
            name=name,
            operation_type=operation_type,
            status="ok",
            attributes={"turn_id": turn_id, **attributes},
        )

    def execute(self, run_id: str, case: Case, version: str) -> Trace:
        if version not in self.versions:
            raise ValueError(f"unknown target version: {version}")

        trace_id = uuid4().hex
        spans: list[TraceSpan] = []
        turn_outcomes: dict[str, dict[str, Any]] = {}
        state = case.initial_state.to_dict()
        session_input: dict[str, Any] = {}
        final_output: dict[str, Any] = {}

        for turn in case.turns:
            raw_input = turn.input.to_dict()
            session_input.update(raw_input)
            skill = raw_input.get("skill") or session_input.get("skill")
            supported = skill in {"loan_approval", "repayment_plan", "complaint", "credit_inquiry"}
            spans.append(self._span(
                trace_id, len(spans), turn.id, "skill-routing", "routing",
                intent=raw_input.get("skill"),
                selected_skill=skill if supported else None,
                fallback=not supported,
            ))
            spans.append(self._span(
                trace_id, len(spans), turn.id, "loan_agent", "agent",
                version=version, skill=skill,
            ))

            if not supported:
                final_output = {"message": "暂不支持该请求", "fallback": True}
            elif skill == "loan_approval":
                required = ("application_id", "risk", "amount")
                missing = [item for item in required if item not in session_input]
                if missing:
                    final_output = {
                        "message": f"请补充：{', '.join(missing)}",
                        "missing_fields": missing,
                    }
                else:
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "credit_inquiry", "tool",
                        application_id=session_input["application_id"],
                        risk=session_input["risk"],
                    ))
                    action = self.provider.choose_action(session_input, version)
                    args = {
                        "application_id": session_input["application_id"],
                        **action["arguments"],
                    }
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, action["tool"], "tool", **args
                    ))
                    state = {
                        **state,
                        "application_id": session_input["application_id"],
                        "risk": session_input["risk"],
                        "status": "approved" if args["approved"] else "pending_review",
                        "approved": args["approved"],
                        "human_review": args["human_review"],
                    }
                    final_output = {
                        "message": "处理完成",
                        "status": state["status"],
                    }
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "business_state", "state", **state
                    ))
            elif skill == "repayment_plan":
                required = ("application_id", "amount", "months")
                missing = [item for item in required if item not in session_input]
                if missing:
                    final_output = {"message": f"请补充：{', '.join(missing)}"}
                else:
                    months = int(session_input["months"])
                    args = {
                        "application_id": session_input["application_id"],
                        "amount": session_input["amount"],
                        "months": months,
                    }
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "repayment_plan", "tool", **args
                    ))
                    state = {
                        **state,
                        "installments": months,
                        "monthly_amount": round(session_input["amount"] / months, 2),
                    }
                    final_output = {"message": "还款计划已生成", **state}
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "business_state", "state", **state
                    ))
            elif skill == "complaint":
                required = ("application_id", "message")
                missing = [item for item in required if item not in session_input]
                if missing:
                    final_output = {"message": f"请补充：{', '.join(missing)}"}
                else:
                    args = {
                        "application_id": session_input["application_id"],
                        "message": session_input["message"],
                    }
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "complaint", "tool", **args
                    ))
                    state = {**state, "status": "open", "message": session_input["message"]}
                    final_output = {"message": "投诉已受理", "status": "open"}
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "business_state", "state", **state
                    ))
            else:
                if "application_id" not in session_input:
                    final_output = {"message": "请提供申请编号"}
                else:
                    args = {"application_id": session_input["application_id"]}
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "credit_inquiry", "tool", **args
                    ))
                    state = {**state, "risk": session_input.get("risk", "low")}
                    final_output = {"message": "征信查询完成", "risk": state["risk"]}
                    spans.append(self._span(
                        trace_id, len(spans), turn.id, "business_state", "state", **state
                    ))

            turn_outcomes[turn.id] = {
                "input": turn.input,
                "output": final_output,
                "state": state,
            }

        business_key = str(session_input.get("application_id", case.id))
        self.repository.put_business_state("loan", business_key, state)
        return Trace(
            trace_id=trace_id,
            run_id=run_id,
            case_id=case.id,
            spans=tuple(spans),
            turn_outcomes=turn_outcomes,
            final_output=final_output,
            final_state=state,
        )
