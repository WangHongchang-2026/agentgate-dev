import json

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError

from agentgate.application.target_catalog import build_fake_target_catalog
from agentgate.case.generation import (
    CategoryCounts,
    DifficultyCounts,
    GenerationRequest,
    TurnCounts,
    TurnMode,
    build_generation_slots,
    case_functional_fingerprint,
    parse_blueprint_response,
    parse_generated_response,
)
from agentgate.case.generation.policy import instruction_issues, validate_case_for_target
from agentgate.case.generation.recipe import RECIPE_VERSION, SYSTEM_PROMPT, provider_response_schema
from agentgate.domain import (
    Case,
    CaseTurn,
    Dimension,
    Outcome,
    OutputExpectation,
    RuleEvaluatorSpec,
    TargetDescriptor,
    TargetRef,
    TargetSkillDescriptor,
    TargetToolDescriptor,
    TargetType,
    ToolArgumentExpectation,
    Trace,
    TraceTurn,
)
from agentgate.evaluator.runner import evaluate_case
from agentgate.trace.redaction import redact


def _target_ref(target_type=TargetType.AGENT):
    return TargetRef(
        platform_id="fake",
        target_type=target_type,
        external_target_id=(
            "customer-service-agent" if target_type == TargetType.AGENT else "order-query"
        ),
        external_version_id=("2.1.0" if target_type == TargetType.AGENT else "deployment-20260903"),
    )


def _request(**changes):
    payload = {
        "draft_id": "draft",
        "draft_content_sha256": "abc",
        "target_ref": _target_ref(),
        "count": 2,
        "turn_mode": "mixed",
        "turn_counts": {"single": 1, "multi": 1},
        "category_counts": {"positive": 1, "negative": 1, "boundary": 0},
        "difficulty_counts": {"easy": 1, "medium": 1, "hard": 0},
    }
    payload.update(changes)
    return GenerationRequest.model_validate(payload)


def test_fake_catalog_covers_agent_skill_and_exact_versions():
    catalog = build_fake_target_catalog()
    assert {item.target_type for item in catalog.list_targets()} == {
        TargetType.AGENT, TargetType.SKILL,
    }
    agent = catalog.resolve(_target_ref())
    assert {item.name for item in agent.skills} == {"order_query", "refund_request"}
    assert {item.name for item in agent.tools} == {"get_order", "create_refund"}
    refund_tool = next(item for item in agent.tools if item.name == "create_refund")
    assert refund_tool.arguments_schema["required"] == ("order_id", "reason", "amount")
    skill = catalog.resolve(_target_ref(TargetType.SKILL))
    assert skill.reproducibility_limited is True
    assert skill.descriptor_sha256


def test_prompt_recipe_uses_evidence_based_conditional_expectations():
    assert RECIPE_VERSION == "dataset-case-generation/v14"
    assert "简化的 Case Blueprint" in SYSTEM_PROMPT
    assert "generation_spec.case_plan" in SYSTEM_PROMPT
    assert "required_tool_calls" in SYSTEM_PROMPT
    assert "不生成期望条件、Path" in SYSTEM_PROMPT
    assert "不得使用 type/value 包装" in SYSTEM_PROMPT
    assert "工具描述和能力说明" in SYSTEM_PROMPT
    assert "用例分类本身不能决定工具是否调用或禁止调用" in SYSTEM_PROMPT
    assert "每轮应明确当前工具是调用还是禁止调用" not in SYSTEM_PROMPT


def test_generation_request_requires_all_distributions_to_sum_to_count():
    with pytest.raises(ValidationError, match="category_counts must sum"):
        _request(category_counts={"positive": 1, "negative": 0, "boundary": 0})
    with pytest.raises(ValidationError, match="mixed turn_counts must sum"):
        _request(turn_counts={"single": 1, "multi": 0})


def test_generation_request_allows_single_mode_without_explicit_turn_counts():
    request = _request(
        count=1,
        turn_mode="single",
        turn_counts=None,
        category_counts={"positive": 1},
        difficulty_counts={"easy": 1},
    )
    assert request.turn_mode == TurnMode.SINGLE


def test_generation_slots_expand_requested_quotas_deterministically():
    slots = build_generation_slots(_request())

    assert [item.index for item in slots] == [0, 1]
    assert sorted(item.category.value for item in slots) == ["negative", "positive"]
    assert sorted(item.difficulty.value for item in slots) == ["easy", "medium"]
    assert [item.turn_mode for item in slots] == ["single", "multi"]


def test_provider_schema_does_not_expose_domain_expectation_unions():
    schema = provider_response_schema(2)
    assert "GeneratedStateExpectation" not in schema["$defs"]
    assert "GeneratedToolArgumentExpectation" not in schema["$defs"]
    assert "GeneratedOutputExpectation" not in schema["$defs"]


def test_provider_schema_closes_skill_tool_and_expectation_choices_to_target():
    descriptor = build_fake_target_catalog().resolve(_target_ref())
    schema = provider_response_schema(2, descriptor)
    turn = schema["$defs"]["GeneratedTurnBlueprint"]["properties"]

    assert turn["input"] == descriptor.input_schema.to_dict()
    assert turn["expected_skill"]["anyOf"][0]["enum"] == [
        "order_query", "refund_request",
    ]
    assert turn["forbidden_tools"]["items"]["enum"] == ["get_order", "create_refund"]
    calls = turn["required_tool_calls"]["items"]["oneOf"]
    assert [item["properties"]["tool"]["const"] for item in calls] == [
        "get_order", "create_refund",
    ]
    assert calls[1]["properties"]["arguments"]["required"] == [
        "order_id", "reason", "amount",
    ]


def test_provider_schema_enforces_each_generation_slot_before_model_output():
    descriptor = build_fake_target_catalog().resolve(_target_ref())
    request = _request()
    slots = build_generation_slots(request)
    schema = provider_response_schema(
        request.count,
        descriptor,
        slots=slots,
        max_turns_per_case=request.max_turns_per_case,
    )
    branches = schema["properties"]["cases"]["items"]["oneOf"]

    assert branches[0]["properties"]["slot_index"] == {"const": 0}
    assert branches[0]["properties"]["turns"]["minItems"] == 1
    assert branches[0]["properties"]["turns"]["maxItems"] == 1
    assert branches[1]["properties"]["slot_index"] == {"const": 1}
    assert branches[1]["properties"]["turns"]["minItems"] == 2
    assert branches[1]["properties"]["turns"]["maxItems"] == 3

    invalid = {
        "cases": [
            {
                "slot_index": 0,
                "name": "单轮订单查询",
                "category": slots[0].category.value,
                "difficulty": slots[0].difficulty.value,
                "turns": [{"input": {"message": "查询订单 ORD-2026-100"}}],
            },
            {
                "slot_index": 1,
                "name": "错误的单轮候选",
                "category": slots[1].category.value,
                "difficulty": slots[1].difficulty.value,
                "turns": [{"input": {"message": "我想退款"}}],
            },
        ]
    }
    with pytest.raises(JsonSchemaValidationError):
        Draft202012Validator(schema).validate(invalid)


def test_blueprint_compiles_tool_arguments_and_output_schema_to_expectations():
    descriptor = build_fake_target_catalog().resolve(_target_ref())
    content = json.dumps({"cases": [{
        "name": "查询订单",
        "category": "positive",
        "difficulty": "easy",
        "turns": [{
            "input": {"message": "查询订单 ORD-2026-100"},
            "expected_skill": "order_query",
            "required_tool_calls": [{
                "tool": "get_order",
                "arguments": {"order_id": "ORD-2026-100"},
            }],
            "output_contains": ["订单"],
        }],
    }]})

    candidates, generated_count, issues = parse_blueprint_response(content, descriptor)

    assert generated_count == 1
    assert issues == ()
    assert candidates[0].valid
    turn = candidates[0].case.turns[0]
    assert turn.required_tools == ("get_order",)
    assert [expectation.kind for expectation in turn.expectations] == [
        "tool_argument", "output", "output",
    ]
    assert turn.expectations[0].path == "order_id"
    assert turn.expectations[-1].condition.kind == "matches_json_schema"
    keyword = turn.expectations[1]
    assert keyword.condition.kind == "matches_pattern"
    assert keyword.condition.pattern == r"(?s:.*订单.*)"


def test_generated_output_keyword_is_an_explicit_regex_consumed_by_evaluator():
    descriptor = build_fake_target_catalog().resolve(_target_ref())
    content = json.dumps({"cases": [{
        "slot_index": 0,
        "name": "订单号格式错误",
        "category": "negative",
        "difficulty": "easy",
        "turns": [{
            "input": {"message": "查询订单 ORD-ERR"},
            "expected_skill": "order_query",
            "output_contains": ["订单号格式错误"],
        }],
    }]})
    candidate = parse_blueprint_response(content, descriptor)[0][0]
    case = candidate.case
    turn = case.turns[0]
    pattern_expectation = next(
        item for item in turn.expectations
        if isinstance(item, OutputExpectation)
        and item.condition.kind == "matches_pattern"
    )
    trace = Trace(
        run_id="run",
        case_id=case.id,
        spans=(),
        turns=(TraceTurn(
            turn_id=turn.id,
            input=turn.input,
            output_present=True,
            output={"message": "订单号格式错误，请重新输入"},
            completed=True,
        ),),
    )
    spec = RuleEvaluatorSpec(
        id="final-output",
        name="最终输出",
        evaluator_type="final_output",
        dimension=Dimension.ANSWER,
        metric="output",
    )

    result = evaluate_case(case, trace, (spec,))[0]

    assert pattern_expectation.condition.pattern == r"(?s:.*订单号格式错误.*)"
    assert result.outcome == Outcome.PASS


def test_blueprint_reports_missing_required_tool_argument_at_exact_path():
    descriptor = build_fake_target_catalog().resolve(_target_ref())
    content = json.dumps({"cases": [{
        "name": "缺少退款金额",
        "category": "negative",
        "difficulty": "medium",
        "turns": [{
            "input": {"message": "退款订单 ORD-2026-100"},
            "required_tool_calls": [{
                "tool": "create_refund",
                "arguments": {"order_id": "ORD-2026-100", "reason": "不需要了"},
            }],
        }],
    }]})

    candidate = parse_blueprint_response(content, descriptor)[0][0]

    assert not candidate.valid
    assert candidate.issues[0].path == "turns[0].required_tool_calls[0].arguments"
    assert candidate.issues[0].code == "tool_arguments_schema_mismatch"


def test_blueprint_rejects_candidate_without_actionable_evaluation_signal():
    descriptor = build_fake_target_catalog().resolve(_target_ref())
    content = json.dumps({"cases": [{
        "name": "只有问题",
        "category": "positive",
        "difficulty": "easy",
        "turns": [{"input": {"message": "你好"}}],
    }]})

    candidate = parse_blueprint_response(content, descriptor)[0][0]

    assert not candidate.valid
    assert candidate.issues[0].code == "insufficient_evaluation_signal"


def test_blueprint_infers_unique_skill_from_required_tool_ownership():
    descriptor = build_fake_target_catalog().resolve(_target_ref())
    content = json.dumps({"cases": [{
        "name": "退款信息不足",
        "category": "negative",
        "difficulty": "easy",
        "turns": [{
            "input": {"message": "订单 ORD-2026-100 需要退款"},
            "required_tool_calls": [{
                "tool": "create_refund",
                "arguments": {
                    "order_id": "ORD-2026-100", "reason": "不需要了", "amount": 10,
                },
            }],
        }],
    }]})

    candidate = parse_blueprint_response(content, descriptor)[0][0]

    assert candidate.valid
    assert candidate.case.turns[0].expected_skill == "refund_request"


def test_blueprint_does_not_infer_skill_from_forbidden_tools():
    descriptor = build_fake_target_catalog().resolve(_target_ref())
    content = json.dumps({"cases": [{
        "name": "天气咨询不得调用订单工具",
        "category": "negative",
        "difficulty": "easy",
        "turns": [{
            "input": {"message": "明天北京天气如何"},
            "forbidden_tools": ["get_order", "create_refund"],
            "output_contains": ["无法查询天气"],
        }],
    }]})

    candidate = parse_blueprint_response(content, descriptor)[0][0]

    assert candidate.valid
    assert candidate.case.turns[0].expected_skill is None


@pytest.mark.parametrize("name", ["Case_0", "case-12", "测试 3"])
def test_blueprint_rejects_placeholder_case_names(name):
    descriptor = build_fake_target_catalog().resolve(_target_ref())
    content = json.dumps({"cases": [{
        "name": name,
        "category": "positive",
        "difficulty": "easy",
        "turns": [{
            "input": {"message": "查询订单 ORD-2026-100"},
            "expected_skill": "order_query",
        }],
    }]})

    candidate = parse_blueprint_response(content, descriptor)[0][0]

    assert not candidate.valid
    assert candidate.issues[0].code == "placeholder_case_name"


def test_parser_accepts_candidate_with_no_expectations():
    content = json.dumps({"cases": [{
        "name": "查询订单",
        "category": "positive",
        "difficulty": "easy",
        "turns": [{"input": {"message": "查询订单 A100"}}],
    }]})
    candidates, generated_count, issues = parse_generated_response(content)
    assert generated_count == 1
    assert issues == ()
    assert candidates[0].valid
    assert candidates[0].case.turns[0].expectations == ()


def test_generation_validation_allows_expectations_to_be_absent_when_evidence_is_insufficient():
    descriptor = build_fake_target_catalog().resolve(_target_ref(TargetType.SKILL))
    content = json.dumps({"cases": [{
        "name": "只有输入，无法评测",
        "category": "positive",
        "difficulty": "easy",
        "turns": [{"input": {"message": "查询订单 A100"}}],
    }]})
    candidate = parse_generated_response(content)[0][0]

    assert validate_case_for_target(candidate.case, descriptor) == ()


def test_generation_validation_does_not_require_unknown_runtime_argument_values():
    descriptor = build_fake_target_catalog().resolve(_target_ref(TargetType.SKILL))
    content = json.dumps({"cases": [{
        "name": "调用工具但没有参数断言",
        "category": "positive",
        "difficulty": "easy",
        "turns": [{
            "input": {"message": "查询订单 A100"},
            "expected_skill": "order_query",
            "required_tools": ["get_order"],
        }],
    }]})
    candidate = parse_generated_response(content)[0][0]

    assert validate_case_for_target(candidate.case, descriptor) == ()


def test_parser_normalizes_blank_expected_skill_to_absent():
    content = json.dumps({"cases": [{
        "name": "无关意图",
        "turns": [{"input": {"message": "你好"}, "expected_skill": "  "}],
    }]})

    candidate = parse_generated_response(content)[0][0]

    assert candidate.case.turns[0].expected_skill is None


def test_parser_keeps_valid_candidates_when_another_is_invalid():
    content = json.dumps({"cases": [
        {"name": "valid", "turns": [{"input": {"message": "hello"}}]},
        {"name": "invalid", "turns": []},
    ]})
    candidates, generated_count, _ = parse_generated_response(content)
    assert generated_count == 2
    assert candidates[0].valid
    assert not candidates[1].valid
    assert candidates[1].issues[0].path.startswith("cases[1].turns")


def test_parser_rejects_oversized_model_response_before_json_parsing():
    candidates, generated_count, issues = parse_generated_response("x" * (2 * 1024 * 1024 + 1))
    assert candidates == ()
    assert generated_count == 0
    assert issues[0].code == "response_too_large"


def test_functional_fingerprint_ignores_system_ids_names_notes_and_ordered_sets():
    first = Case(
        id="case-a", name="First", notes="one", tags=("b", "a"),
        turns=(CaseTurn(
            id="turn-a", input={"message": "hello"}, notes="turn one",
            required_tools=("get_order", "get_order"), policy_rules=("b", "a"),
        ),),
    )
    second = Case(
        id="case-b", name="Second", notes="two", tags=("a", "b"),
        turns=(CaseTurn(
            id="turn-b", input={"message": "hello"}, notes="turn two",
            required_tools=("get_order",), policy_rules=("a", "b"),
        ),),
    )
    assert case_functional_fingerprint(first) == case_functional_fingerprint(second)


def test_target_validation_rejects_unknown_skill_tool_and_dollar_json_path():
    descriptor = build_fake_target_catalog().resolve(_target_ref())
    content = json.dumps({"cases": [{
        "name": "bad",
        "turns": [{
            "input": {"message": "hello"},
            "expected_skill": "made_up",
            "required_tools": ["made_up"],
            "expectations": [{
                "kind": "tool_argument",
                "tool": "get_order",
                "path": "$.order_id",
                "condition": {"kind": "equals", "expected": "A100"},
            }],
        }],
    }]})
    candidate = parse_generated_response(content)[0][0]
    issues = validate_case_for_target(candidate.case, descriptor)
    assert {item.code for item in issues} >= {
        "unknown_skill", "unknown_tool", "unknown_tool_path",
    }


def test_industry_weather_trajectory_compiles_to_tool_and_argument_checks():
    """LangSmith's documented weather trajectory, expressed in our Blueprint DSL."""
    descriptor = TargetDescriptor(
        ref=TargetRef(
            platform_id="example",
            target_type=TargetType.AGENT,
            external_target_id="weather-agent",
            external_version_id="weather-v1",
        ),
        display_name="Weather assistant",
        description="Answers weather questions using the declared weather tool.",
        skills=(TargetSkillDescriptor(
            name="weather_lookup",
            description="Look up weather for a requested city.",
            tools=("get_weather",),
        ),),
        tools=(TargetToolDescriptor(
            name="get_weather",
            description="Get current weather for a city.",
            arguments_schema={
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
        ),),
        input_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    )
    content = json.dumps({"cases": [{
        "name": "查询旧金山天气",
        "category": "positive",
        "difficulty": "easy",
        "turns": [{
            "input": {"message": "What's the weather in SF?"},
            "expected_skill": "weather_lookup",
            "required_tool_calls": [{
                "tool": "get_weather", "arguments": {"city": "SF"},
            }],
            "output_contains": ["SF"],
        }],
    }]})

    candidate = parse_blueprint_response(content, descriptor)[0][0]

    assert candidate.valid
    turn = candidate.case.turns[0]
    assert turn.required_tools == ("get_weather",)
    assert any(
        isinstance(item, ToolArgumentExpectation)
        and item.tool == "get_weather"
        and item.path == "city"
        for item in turn.expectations
    )
    assert any(isinstance(item, OutputExpectation) for item in turn.expectations)


def test_industry_style_local_ref_tool_schema_supports_nested_argument_paths():
    """OpenAPI/MCP-style schemas commonly reuse local definitions through $ref."""
    descriptor = TargetDescriptor(
        ref=TargetRef(
            platform_id="example",
            target_type=TargetType.AGENT,
            external_target_id="support-agent",
            external_version_id="support-v1",
        ),
        display_name="Support assistant",
        tools=(TargetToolDescriptor(
            name="lookup_order",
            arguments_schema={
                "$defs": {
                    "LookupArguments": {
                        "type": "object",
                        "properties": {
                            "order": {
                                "type": "object",
                                "properties": {"id": {"type": "string"}},
                                "required": ["id"],
                            }
                        },
                        "required": ["order"],
                    }
                },
                "$ref": "#/$defs/LookupArguments",
            },
        ),),
    )
    case = Case(name="查询订单", turns=(CaseTurn(
        input={"message": "查订单 A-100"},
        required_tools=("lookup_order",),
        expectations=(ToolArgumentExpectation(
            tool="lookup_order",
            path="order.id",
            condition={"kind": "equals", "expected": "A-100"},
        ),),
    ),))

    assert validate_case_for_target(case, descriptor) == ()


def test_provider_schema_preserves_local_refs_from_target_contracts():
    descriptor = TargetDescriptor(
        ref=TargetRef(
            platform_id="example",
            target_type=TargetType.AGENT,
            external_target_id="sql-agent",
            external_version_id="sql-v1",
        ),
        display_name="SQL assistant",
        tools=(TargetToolDescriptor(
            name="sql_db_query",
            description="Execute a read-only SQL query.",
            arguments_schema={
                "$defs": {
                    "Query": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                        "additionalProperties": False,
                    }
                },
                "$ref": "#/$defs/Query",
            },
        ),),
        input_schema={
            "$defs": {
                "Input": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                    "additionalProperties": False,
                }
            },
            "$ref": "#/$defs/Input",
        },
    )
    schema = provider_response_schema(1, descriptor)
    instance = {"cases": [{
        "name": "查询销量最高的音乐类型",
        "category": "positive",
        "difficulty": "medium",
        "turns": [{
            "input": {"message": "Which music genre has the most purchases?"},
            "required_tool_calls": [{
                "tool": "sql_db_query",
                "arguments": {
                    "query": "SELECT Genre.Name FROM Genre ORDER BY Name LIMIT 1"
                },
            }],
        }],
    }]}

    Draft202012Validator(schema).validate(instance)


def test_output_keyword_uses_message_path_through_local_ref():
    descriptor = TargetDescriptor(
        ref=TargetRef(
            platform_id="example",
            target_type=TargetType.AGENT,
            external_target_id="answer-agent",
            external_version_id="v1",
        ),
        display_name="Answer assistant",
        output_schema={
            "$defs": {
                "Answer": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                }
            },
            "$ref": "#/$defs/Answer",
        },
    )
    content = json.dumps({"cases": [{
        "name": "无法处理的请求",
        "category": "negative",
        "difficulty": "easy",
        "turns": [{
            "input": {"message": "perform an unsupported action"},
            "output_contains": ["unsupported"],
        }],
    }]})

    candidate = parse_blueprint_response(content, descriptor)[0][0]

    assert candidate.valid
    output = next(
        item for item in candidate.case.turns[0].expectations
        if isinstance(item, OutputExpectation)
        and item.condition.kind == "matches_pattern"
    )
    assert output.path == "message"


def test_generated_case_rejects_empty_turn_input_without_target_input_schema():
    descriptor = TargetDescriptor(
        ref=TargetRef(
            platform_id="example",
            target_type=TargetType.AGENT,
            external_target_id="generic-agent",
            external_version_id="v1",
        ),
        display_name="Generic assistant",
    )
    content = json.dumps({"cases": [{
        "name": "空输入",
        "category": "negative",
        "difficulty": "easy",
        "turns": [{"input": {}, "output_contains": ["请输入问题"]}],
    }]})

    candidate = parse_blueprint_response(content, descriptor)[0][0]

    assert not candidate.valid
    assert any(
        issue.code in {"empty_turn_input", "invalid_blueprint"}
        and issue.path.endswith("input")
        for issue in candidate.issues
    )


def test_declared_skill_tool_mapping_rejects_cross_skill_tool_calls():
    descriptor = build_fake_target_catalog().resolve(_target_ref())
    content = json.dumps({"cases": [{
        "name": "路由与动作不一致",
        "category": "positive",
        "difficulty": "easy",
        "turns": [{
            "input": {"message": "查询订单 ORD-2026-100"},
            "expected_skill": "order_query",
            "required_tool_calls": [{
                "tool": "create_refund",
                "arguments": {
                    "order_id": "ORD-2026-100",
                    "reason": "不需要了",
                    "amount": 10,
                },
            }],
        }],
    }]})

    candidate = parse_blueprint_response(content, descriptor)[0][0]

    assert not candidate.valid
    assert any(issue.code == "skill_tool_mismatch" for issue in candidate.issues)


def test_redaction_removes_keys_and_inline_bailian_keys():
    result = redact({
        "api_key": "sk-secret-value",
        "notes": "Authorization: Bearer abc.def and sk-1234567890",
        "safe": "hello",
    })
    serialized = json.dumps(result.value)
    assert "abc.def" not in serialized
    assert "sk-1234567890" not in serialized
    assert result.value["safe"] == "hello"
    assert result.redacted_count == 3


def test_safety_topics_are_rejected_before_model_call():
    assert instruction_issues("请生成 prompt injection 用例")[0].code == "forbidden_topic"
    assert instruction_issues("覆盖订单不存在") == ()
