# 测评集自动生成：当前实现详细方案

> 文档性质：当前代码实现说明，不代表未来完整产品范围
> 需求来源：`REQ-010 自动生成用例`
> 当前 Recipe：`dataset-case-generation/v14`

## 1. 功能目标

基于某个确定版本的 Agent 或 Skill 能力信息，通过大模型生成候选测评用例。候选必须先经过系统校验和人工审核，只有用户接受的候选才写入测评集草稿；系统不会自动发布测评集，也不会自动启动评测。

当前实现采用“模型生成简化 Blueprint，后端确定性编译 Case”的方式，避免让模型直接生成包含 Condition、Path 和系统 ID 的完整领域对象。

```text
TargetDescriptor + 生成配置 + 可选参考用例
                    ↓
           确定性生成 Case Plan
                    ↓
         百炼生成简化 Case Blueprint
                    ↓
    后端编译 Skill、工具、参数和输出期望
                    ↓
       领域校验 + Target 校验 + 去重
                    ↓
              前端人工审核
                    ↓
          批量写入 Dataset Draft
                    ↓
              用户验证并发布
```

## 2. 模块边界

| 层级 | 当前代码 | 职责 |
|---|---|---|
| Domain | `domain/target.py`、`domain/case.py` | Target、Case、Expectation 和生成来源的不可变数据契约 |
| Generation Core | `case/generation/` | 生成请求、Prompt Recipe、Blueprint、编译、校验和去重 |
| Application | `application/dataset_generation.py` | 编排 Target、参考用例、模型调用、审核和草稿写入 |
| Target Catalog | `application/target_catalog.py` | 只读列出对象、版本并解析确定版本的 `TargetDescriptor` |
| Model Integration | `integrations/model_providers/` | 百炼 OpenAI-compatible 调用、凭据、限流和错误归一化 |
| HTTP | `server/dataset_generation_api.py` | 请求 DTO、路由、状态码和错误响应 |
| Dataset | `case/service.py`、`storage/` | 草稿并发控制、批量写入、幂等回执和持久化 |
| Web | `DatasetGenerationDialog.vue` | 配置生成、候选审核、编辑、接收和错误展示 |

依赖方向保持为：HTTP/UI → Application → Domain/Protocol；模型厂商协议只存在于 Integration 层。自动生成模块不调用 Agent，也不从 Run 的执行配置反推 Agent 能力。

## 3. Target 输入契约

自动生成首先通过完整 `TargetRef` 解析一个确定版本的 `TargetDescriptor`。

### 3.1 TargetRef

```json
{
  "platform_id": "fake",
  "target_type": "agent",
  "external_target_id": "customer-service-agent",
  "external_version_id": "2.1.0"
}
```

四个字段共同标识一个外部对象的确定版本；展示名称不是对象身份，执行过程中也不会静默替换为 `latest`。

### 3.2 TargetDescriptor

| 字段 | 当前用途 |
|---|---|
| `ref` | 固定平台、对象类型、对象和版本 |
| `display_name`、`description` | 前端选择和场景理解 |
| `prompt_or_capability_summary` | 生成正常、拒绝、缺失信息和边界场景 |
| `skills` | 限制 `expected_skill`，描述 Skill 与工具归属 |
| `tools` | 限制可用工具及其名称 |
| `tools[].arguments_schema` | 约束工具调用参数并编译参数期望 |
| `input_schema` | 直接约束每轮 Blueprint 输入结构 |
| `output_schema` | 自动生成输出结构期望 |
| `reproducibility_limited` | 标记对象版本是否可稳定复现 |
| `descriptor_sha256` | 固化本次生成使用的能力描述内容 |

当前仓库只实现了字段完整的 Fake Agent 和 Fake Skill。真实外部平台需要在 `integrations/targets/` 增加只读 Adapter，并归一化为相同的 `TargetDescriptor`。

## 4. 生成请求

核心请求字段：

| 字段 | 约束 | 说明 |
|---|---|---|
| `draft_id` | 必填 | 当前目标草稿 |
| `draft_content_sha256` | 必填 | 生成开始时的草稿内容 Hash |
| `target_ref` | 必填 | 确定版本的 Agent/Skill |
| `count` | 1–20 | 候选数量 |
| `turn_mode` | `single` / `multi` / `mixed` | 单轮、多轮或混合 |
| `turn_counts` | mixed 时必填 | 单轮和多轮数量，二者都必须大于 0 |
| `max_turns_per_case` | 2–5 | 每个多轮用例的最大轮数 |
| `category_counts` | 合计等于 count | 正例、负例、边界数量 |
| `difficulty_counts` | 合计等于 count | 简单、中等、困难数量 |
| `reference_source` | 可选 | 参考测评集的已发布版本 |
| `reference_case_ids` | 最多 20 个 | 指定参考 Case；必须属于参考版本 |
| `instructions` | 最多 4000 字符 | 用户补充业务要求 |
| `model_profile_id` | 必填 | 当前固定为百炼默认 Profile |

系统根据分类、难度和轮次配置确定性构建 `case_plan`。模型返回的第 N 条候选必须对应第 N 个 Slot；最终分类和难度以 Slot 为准，不信任模型自行分配。

未指定参考 Case ID 时，系统按照分类、难度分组，以 Case ID 稳定排序并轮询选择，最多取 20 条。

## 5. Prompt 与结构化输出

### 5.1 当前模型配置

| 配置 | 当前值 |
|---|---|
| Provider | OpenAI-compatible |
| 服务 | 阿里百炼 |
| 模型 | `qwen3.7-plus` |
| Thinking | 关闭 |
| Temperature | `0.4` |
| Timeout | 60 秒 |
| 单 Profile 并发 | 2 |
| 瞬态失败重试 | 最多 1 次 |
| 输出模式 | strict JSON Schema |

### 5.2 Prompt 原则

模型只负责设计业务场景，不负责生成 AgentGate 的完整 Expectation。主要规则包括：

- Blueprint 数量和顺序必须与 `case_plan` 一致；
- 输入必须满足 `target.input_schema`；
- 只允许引用 Target 声明的 Skill、工具和工具参数；
- 意图唯一匹配 Skill 时填写 `expected_skill`，参数缺失不等于路由意图不存在；
- 正例覆盖正常成功路径；负例最终不应转为成功执行；边界覆盖格式、临界值或纠错恢复；
- 信息不足不自动代表禁调；仅当能力说明或业务规则明确禁止时填写 `forbidden_tools`，并可用稳定字段名表示追问语义；
- 不生成系统 ID、版本、时间、Hash、Condition 或 Path；
- 禁止使用 `Case_0`、`测试1` 等占位名称；
- 不生成安全攻击、越狱或提示词注入用例。

### 5.3 动态 Response Schema

Response Schema 由 Blueprint DTO 和当前 `TargetDescriptor` 合成：

- `input` 使用 Target 的 `input_schema`；本地 `$ref` 会重写到响应 Schema 的独立命名空间；
- `expected_skill` 收窄为已声明 Skill 枚举或 `null`；
- `forbidden_tools` 收窄为已声明工具枚举；
- `required_tool_calls` 按每个工具生成 `oneOf`；
- 每个工具的 `arguments` 使用它的 `arguments_schema`，并保留本地 `$ref` 语义；
- `cases.minItems` 和 `cases.maxItems` 都设置为本次请求数量。
- 每个计划槽位使用独立 Schema，固定 `slot_index`、分类、难度及单/多轮数量上限。

因此输入字段、工具名称和工具参数不再仅依赖 Prompt 提醒，而是在模型输出阶段受到 JSON Schema 约束。

## 6. Blueprint 数据结构

模型返回的结构只包含生成所需的最小业务信息：

```json
{
  "cases": [
    {
      "slot_index": 0,
      "name": "查询合法订单",
      "category": "positive",
      "difficulty": "easy",
      "tags": [],
      "notes": "验证正常订单查询路径",
      "turns": [
        {
          "input": {
            "message": "查询订单 ORD-2026-100"
          },
          "expected_skill": "order_query",
          "required_tool_calls": [
            {
              "tool": "get_order",
              "arguments": {
                "order_id": "ORD-2026-100"
              },
              "occurrence": "last"
            }
          ],
          "forbidden_tools": [],
          "output_contains": [],
          "notes": "订单号有效，应查询订单"
        }
      ]
    }
  ]
}
```

模型不生成 Case ID、Turn ID、Expectation ID、字段 Path、Condition、Provenance、版本或时间。

## 7. Blueprint 到 Case 的确定性编译

| Blueprint | 编译结果 |
|---|---|
| `expected_skill` | `CaseTurn.expected_skill` |
| `required_tool_calls[].tool` | `CaseTurn.required_tools` |
| `forbidden_tools` | `CaseTurn.forbidden_tools` |
| 工具参数叶子字段 | `ToolArgumentExpectation + Equals` |
| `output_contains[]` | `OutputExpectation + MatchesPattern` |
| Target `output_schema` | `OutputExpectation + MatchesJsonSchema` |
| Blueprint 业务字段 | `Case` / `CaseTurn` |

例如：

```json
{
  "tool": "get_order",
  "arguments": {"order_id": "ORD-2026-100"}
}
```

会编译为：

```json
{
  "kind": "tool_argument",
  "tool": "get_order",
  "path": "order_id",
  "occurrence": "last",
  "condition": {
    "kind": "equals",
    "expected": "ORD-2026-100"
  }
}
```

补充规则：

- 嵌套对象参数递归转换为点分 Path；
- 同一工具只保留一次 `required_tools`；
- 输出 Schema 存在时，每轮自动加入结构期望，避免期望区域完全为空；
- `output_contains` 默认绑定输出对象的 `message` 字段；没有该字段时匹配整个输出；
- 如果本轮引用的工具共同只属于一个 Skill，后端自动补齐该 `expected_skill`；
- Skill、工具名称仅在删除空白后能够唯一匹配声明值时做安全归一化。

## 8. 校验与质量门禁

### 8.1 Blueprint 校验

- 响应必须是只包含 `cases` 的 JSON 对象；
- Blueprint 字段严格、禁止额外字段；
- 用例至少一轮、最多五轮；
- Skill 和工具必须存在；
- 必调与禁调工具不能冲突；
- 工具参数整体满足对应 `arguments_schema`；
- 每个用例至少包含 Skill、工具调用、禁调工具或稳定输出关键词之一；
- 拒绝 `Case_0`、`case-12`、`测试 3` 等占位名称；
- 单条无效不会丢弃同批其他合法候选。

### 8.2 Case 与 Target 校验

- 每轮输入满足 `input_schema`；
- 单轮模式恰好一轮，多轮模式至少两轮；
- 不超过请求指定的最大轮数；
- 工具参数 Path 和输出 Path 必须真实存在；
- 候选满足现有 Case 领域约束和 Dataset 发布规则；
- 禁止主题同时检查用户说明和模型结果。

### 8.3 配额和去重

- 检查模型返回数量；
- 检查分类、难度、单轮/多轮配额；
- 与当前 Draft 以及同批候选做 Functional Fingerprint 精确去重；
- Fingerprint 忽略系统 ID、名称、备注、来源和时间，保留真正影响评测语义的字段；
- 当前不使用 Embedding 或 LLM 自动删除“相似但不相同”的用例。

### 8.4 大小限制

| 对象 | 限制 |
|---|---:|
| 发给模型的脱敏载荷 | 1 MiB |
| Provider 响应 | 2 MiB |
| 单个候选 Case | 256 KiB |
| 单批候选 | 最多 20 条 |
| 解析响应保护上限 | 最多 100 条 |

## 9. 候选审核和写入

候选仅存在于当前 HTTP 响应和前端状态中，不直接持久化。用户可以：

1. 查看有效数、无效数和字段级错误；
2. 逐条查看并编辑完整 Case；
3. 调用候选校验接口重新校验编辑结果；
4. 勾选部分合法候选；
5. 批量写入当前 Dataset Draft；
6. 返回测评集页面继续编辑、验证和发布。

批量接收具备以下保护：

- 生成响应携带 HMAC 签名的 `acceptance_token`；
- Token 固定 Draft ID/Hash、TargetRef、Descriptor Hash、Recipe、模型 Profile、生成槽位和最大轮数；
- Token 有效期两小时；
- 编辑校验及接收前都按签名槽位复验分类、难度和轮数，再执行完整校验和去重；
- `Idempotency-Key` 保证网络重试不会重复插入；
- Draft Hash 变化返回 409，不覆盖并发修改；
- 一批候选原子写入，要么全部成功，要么全部失败。

写入时由系统附加 `GeneratedCaseProvenance`，记录 TargetRef、Descriptor Hash、Recipe、模型 Profile、Provider、请求模型和生成时间。用户不能自行提交系统来源字段。

## 10. HTTP API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/targets?target_type=agent\|skill` | 查询可生成的 Agent/Skill |
| GET | `/api/targets/{platform_id}/{target_type}/{external_target_id}/versions` | 查询确定版本 |
| GET | `/api/dataset-generation/model-profiles` | 查询模型及凭据可用状态 |
| PUT | `/api/dataset-generation/model-profiles/{profile_id}/credential` | 验证并配置运行时 API Key |
| DELETE | `/api/dataset-generation/model-profiles/{profile_id}/credential` | 清除运行时 API Key |
| POST | `/api/datasets/{dataset_id}/drafts/generate-candidates` | 生成候选 |
| POST | `/api/datasets/{dataset_id}/drafts/generated-candidates/validate` | 重新校验编辑后的候选 |
| POST | `/api/datasets/{dataset_id}/drafts/cases/batch` | 批量接收候选到草稿 |

主要错误映射：

| 状态码 | 场景 |
|---:|---|
| 422 | 请求、候选或生成主题不合法 |
| 404 | Draft、Target、模型 Profile 或参考 Case 不存在 |
| 409 | Draft、Descriptor、Recipe 或幂等冲突 |
| 429 | Provider 限流或本地生成并发已满 |
| 502 | 凭据缺失、鉴权失败、Provider 拒绝或不可用 |
| 504 | Provider 超时 |

错误响应包含稳定 `code`、中文 `message`、`retryable`、可选 `request_id` 和字段级 `issues`。

## 11. 前端流程

当前入口位于测评集草稿页面的“AI 生成用例”按钮：

```text
选择 Agent/Skill 类型
→ 选择对象和具体版本
→ 选择生成模型
→ 必要时输入并验证 API Key
→ 配置数量、轮次、分类和难度
→ 可选参考已发布测评集及 Case
→ 填写可选业务要求
→ 生成候选
→ 查看、编辑和重新校验
→ 勾选合法候选并加入草稿
```

生成按钮只有在以下条件满足时可用：存在当前 Draft、Target 版本已选择、模型凭据可用、分类与难度合计正确，mixed 模式同时包含单轮和多轮，参考测评集选择有效。

## 12. 凭据与数据安全

- 页面提交的 API Key 使用 `SecretStr` 接收；
- 保存前先用一次最小 Provider 请求验证；
- Key 只保存在后端进程内存，不写数据库、不进入 Case、不返回前端；
- 后端重启或用户清除后失效；
- TargetDescriptor、参考 Case 和用户说明在调用模型前统一脱敏；
- 响应只记录脱敏数量，不记录秘密原文；
- Provider 日志只包含模型、请求 ID、耗时、Token 数量和错误代码；
- Target Catalog 是只读边界，不创建、修改、删除或发布外部 Agent/Skill。

## 13. 当前实现状态

已经实现：

- Fake Agent/Skill 的只读 Target Catalog；
- 确定版本选择和 Descriptor Hash；
- 百炼 OpenAI-compatible Provider；
- 前端运行时 API Key 配置；
- 单轮、多轮和混合生成；
- 分类、难度和数量控制；
- 可选参考已发布测评集；
- Blueprint strict JSON Schema；
- Blueprint 到 Case 的确定性编译；
- Skill、工具、工具参数、输入和输出结构校验；
- Skill 与其声明工具的一致性校验，以及外部/失效 Schema 引用门禁；
- 字段级错误、精确去重、候选编辑与复验；
- 部分接收、原子批量写入、并发控制和幂等；
- 生成来源持久化；
- 生成后沿用现有 Dataset 验证和发布流程。

## 14. 当前已知限制

1. 真实外部 Agent/Skill Catalog Adapter 尚未实现，目前对象来自 Fake Catalog。
2. 候选生成是同步请求，尚无后台任务、进度查询、取消和断点恢复。
3. 候选在接收前不持久化，刷新页面会丢失未接收候选。
4. 一批候选由一次模型请求生成；尚未按单个 Slot 分批重试失败候选。
5. 去重只做确定性精确去重，不做语义相似度去重。
6. 输出期望当前主要来自 `output_schema` 和稳定关键词；不会猜测未知工具返回值或最终业务答案。
7. 当前 Blueprint 不生成 State Expectation 和 Policy Rule；这些需要 Target 提供正式 `state_schema` 和规则目录后再接入。
8. 分类与业务语义仍主要依赖 Prompt，代码只能校验结构和确定性约束，候选仍需人工审核。
9. API Key 仅存在进程内存，服务重启后必须重新配置。
10. 当前只配置一个百炼模型 Profile，尚未提供多 Provider 管理页面。

## 15. 当前验证情况

- 自动生成核心及 API 测试覆盖 Prompt Recipe、动态 Schema、Blueprint 编译、输入/工具参数校验、乱序或部分重复标识归一化、字段级错误、参考用例、脱敏、并发冲突、幂等和发布闭环；
- 最近一次后端全量回归：`329 passed, 1 skipped`；
- 前端已通过 TypeScript 类型检查、Vitest 和生产构建；
- Playwright 全链路覆盖 Dataset 创建、发布、运行、版本、Excel/JSON 导入导出及 AI 生成入口；
- 已使用真实百炼模型发现并修复空期望、工具名空白、输入 AnyValue 包装、输入字段偏离 Schema 等问题；
- 已将官方 Agent 评测示例中的天气工具轨迹、客服动作和 SQL 查询契约转为回归测试，覆盖工具选择、参数断言与 `$ref` Schema；
- 最终真实 Agent/Skill 重跑应在后端重启后重新配置运行时 API Key 再执行。

## 16. 后续接入顺序

```text
真实外部平台只读 TargetCatalogAdapter
→ TargetDescriptor 完整性门禁
→ 真实 Agent/Skill 生成回归
→ 单 Slot 失败重试和后台任务
→ 生成批次及审核指标持久化
→ 基于真实失败 Trace 生成回归候选
```

首个真实 Adapter 接入前，应先取得一个真实 Sandbox 对象的脱敏响应样例，确认版本、Prompt/能力摘要、Skill、工具参数 Schema、输入 Schema 和输出 Schema 的实际可获得性；缺失字段必须由适配层明确补充或返回 `target_capability_unavailable`，不能交给生成模型猜测。
