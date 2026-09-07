"""Playwright server with deterministic generation; never used by production."""

from __future__ import annotations

import json

from agentgate.case.generation.fake import FakeGenerationModel
from agentgate.server.application import create_app


def _response(request) -> str:
    plan = request.user_payload.to_dict()["generation_spec"]["case_plan"]
    cases = []
    for index, slot in enumerate(plan):
        order_id = f"ORD-2026-{index + 1:03d}"
        final_turn = {
            "input": {"message": f"查询订单 {order_id}"},
            "expected_skill": "order_query",
            "required_tool_calls": [{
                "tool": "get_order",
                "arguments": {"order_id": order_id},
            }],
        }
        turns = [final_turn]
        if slot["turn_mode"] == "multi":
            turns = [{
                "input": {"message": "我想查询一个订单"},
                "expected_skill": "order_query",
                "forbidden_tools": ["get_order"],
                "output_contains": ["订单号"],
            }, final_turn]
        cases.append({
            "slot_index": index,
            "name": f"端到端订单查询场景 {index + 1}",
            "category": slot["category"],
            "difficulty": slot["difficulty"],
            "turns": turns,
        })
    return json.dumps({"cases": cases}, ensure_ascii=False)


app = create_app(generation_model=FakeGenerationModel(_response))
