"""Read-only discovery and exact-version resolution for evaluation targets."""

from __future__ import annotations

from agentgate.domain import (
    DomainModel,
    TargetDescriptor,
    TargetRef,
    TargetSkillDescriptor,
    TargetToolDescriptor,
    TargetType,
)


class TargetCatalogItem(DomainModel):
    platform_id: str
    target_type: TargetType
    external_target_id: str
    display_name: str
    description: str = ""


class TargetCatalog:
    """Small read-only catalog; platform adapters can supply the same descriptors later."""

    def __init__(self, descriptors: tuple[TargetDescriptor, ...]) -> None:
        self._descriptors = descriptors
        identities = [item.ref for item in descriptors]
        if len(identities) != len(set(identities)):
            raise ValueError("duplicate TargetRef in catalog")

    def list_targets(self, target_type: TargetType | None = None) -> tuple[TargetCatalogItem, ...]:
        grouped: dict[tuple[str, TargetType, str], TargetDescriptor] = {}
        for descriptor in self._descriptors:
            if target_type is not None and descriptor.ref.target_type != target_type:
                continue
            key = (
                descriptor.ref.platform_id,
                descriptor.ref.target_type,
                descriptor.ref.external_target_id,
            )
            grouped.setdefault(key, descriptor)
        return tuple(
            TargetCatalogItem(
                platform_id=key[0],
                target_type=key[1],
                external_target_id=key[2],
                display_name=value.display_name,
                description=value.description,
            )
            for key, value in sorted(grouped.items(), key=lambda pair: tuple(str(v) for v in pair[0]))
        )

    def list_versions(
        self,
        platform_id: str,
        target_type: TargetType,
        external_target_id: str,
    ) -> tuple[TargetDescriptor, ...]:
        return tuple(
            item
            for item in self._descriptors
            if item.ref.platform_id == platform_id
            and item.ref.target_type == target_type
            and item.ref.external_target_id == external_target_id
        )

    def resolve(self, ref: TargetRef) -> TargetDescriptor:
        item = next((descriptor for descriptor in self._descriptors if descriptor.ref == ref), None)
        if item is None:
            raise ValueError(f"unknown target version: {ref.external_target_id}@{ref.external_version_id}")
        return item


def _object_schema(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def build_fake_target_catalog() -> TargetCatalog:
    get_order = TargetToolDescriptor(
        name="get_order",
        description="按订单号查询订单状态、金额和客户身份。",
        arguments_schema=_object_schema(
            {
                "order_id": {
                    "type": "string",
                    "description": "从用户输入中提取的订单号，例如 ORD-2026-001",
                    "pattern": "^ORD-[0-9]{4}-[0-9]{3,}$",
                }
            },
            ["order_id"],
        ),
    )
    create_refund = TargetToolDescriptor(
        name="create_refund",
        description="为符合条件的订单创建退款申请。",
        arguments_schema=_object_schema(
            {
                "order_id": {"type": "string"},
                "reason": {"type": "string"},
                "amount": {"type": "number", "minimum": 0},
            },
            ["order_id", "reason", "amount"],
        ),
    )
    agent = TargetDescriptor(
        ref=TargetRef(
            platform_id="fake",
            target_type=TargetType.AGENT,
            external_target_id="customer-service-agent",
            external_version_id="2.1.0",
        ),
        display_name="客户服务 Agent",
        description="处理订单查询与退款申请，并在信息不足时向用户追问。",
        prompt_or_capability_summary=(
            "识别订单查询或退款意图。订单号格式正确时，订单查询必须调用 get_order；"
            "退款必须先调用 get_order，且只有用户已提供订单号、退款原因和金额时才调用 "
            "create_refund；缺少任一信息时不得调用 create_refund，应先追问。"
        ),
        skills=(
            TargetSkillDescriptor(
                name="order_query",
                description="查询订单状态和详情。",
                prompt_or_capability_summary=(
                    "订单号格式正确时必须调用 get_order，并将订单号原样传入 order_id；"
                    "缺少或格式错误时不得调用 get_order，应先追问。"
                ),
                tools=("get_order",),
            ),
            TargetSkillDescriptor(
                name="refund_request",
                description="核验并创建退款申请。",
                prompt_or_capability_summary=(
                    "先使用 get_order 查询订单；用户已提供合法订单号、退款原因和金额时，"
                    "再调用 create_refund，并原样传入 order_id、reason 和 amount；"
                    "缺少任一字段时不得调用 create_refund，应先追问。"
                ),
                tools=("get_order", "create_refund"),
            ),
        ),
        tools=(get_order, create_refund),
        input_schema=_object_schema(
            {
                "message": {"type": "string"},
                "customer_id": {"type": "string"},
            },
            ["message"],
        ),
        output_schema=_object_schema(
            {
                "message": {"type": "string"},
                "order_status": {"type": ["string", "null"]},
                "refund_id": {"type": ["string", "null"]},
            },
            ["message"],
        ),
    )
    skill = TargetDescriptor(
        ref=TargetRef(
            platform_id="fake",
            target_type=TargetType.SKILL,
            external_target_id="order-query",
            external_version_id="deployment-20260903",
        ),
        display_name="订单查询 Skill",
        description="使用订单号查询订单；覆盖正常、缺失、格式错误和不存在的订单。",
        prompt_or_capability_summary="只处理订单查询，不执行退款；缺少订单号时要求补充。",
        skills=(
            TargetSkillDescriptor(
                name="order_query",
                description="查询订单状态和详情。",
                prompt_or_capability_summary=(
                    "订单号格式正确时必须调用 get_order，并把输入中的订单号原样传给 order_id；"
                    "缺少或格式错误时不得调用 get_order，应要求用户补充有效订单号；"
                    "订单不存在时仍需调用 get_order，并明确告知未查询到订单。"
                ),
                tools=("get_order",),
            ),
        ),
        tools=(get_order,),
        input_schema=_object_schema({"message": {"type": "string"}}, ["message"]),
        output_schema=_object_schema(
            {
                "message": {"type": "string", "description": "面向用户的订单查询答复"},
                "order_status": {
                    "type": ["string", "null"],
                    "description": "订单状态；订单不存在或尚未查询时为 null",
                },
            },
            ["message"],
        ),
        reproducibility_limited=True,
    )
    return TargetCatalog((agent, skill))
