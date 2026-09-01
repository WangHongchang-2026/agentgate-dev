# AgentGate Skill 测评产品方案

## 1. 方案结论

AgentGate 的 Skill 测评采用四层模型：

1. **静态质量**：Skill 是否写得规范、清楚、安全，声明与实际能力是否一致；
2. **触发质量**：该调用时能否被 Agent 找到，不该调用时是否能够克制；
3. **直接执行质量**：Skill 被加载后，工具、参数、格式和内容是否正确；
4. **对比与回归**：使用 Skill 是否产生真实增益，新版本是否发生退化。

其中，触发质量属于 Skill 的质量属性和 Skill 测评报告，但必须通过真实 Agent 的
路由过程执行；底层复用 AgentGate 现有 Agent Run、Routing Trace 和路由评估器。

```text
选择 Skill + SkillVersion
            │
            ▼
┌──────────────────────┐
│ 1. 静态质量检查       │
│ 规范、描述、边界、冲突 │
└──────────┬───────────┘
           │ 通过
           ▼
┌──────────────────────┐
│ 2. 触发质量测评       │
│ Agent 自主选择 Skill  │
│ 正例、负例、混淆例    │
└──────────┬───────────┘
           │ 通过
           ▼
┌──────────────────────┐
│ 3. Skill 直接测评     │
│ 指定 Skill 执行任务   │
│ 工具、参数、格式、内容 │
└──────────┬───────────┘
           │ 通过
           ▼
┌──────────────────────┐
│ 4. 对比与回归         │
│ With/Without、版本对比 │
└──────────┬───────────┘
           ▼
      Skill 发布结论
```

Skill 的最终质量由两项核心动态结论共同决定：

> **找得准不准，以及找到后做得好不好。**

---

## 2. 方案目标与边界

| 测评层 | 核心问题 | 被测对象 | 是否运行 Agent | 是否直接指定 Skill |
|---|---|---|---:|---:|
| 静态质量 | Skill 是否写得合理 | Skill 文件、描述、Schema、工具声明 | 否 | 是 |
| 触发质量 | Agent 是否在正确场景选择该 Skill | Skill 名称、描述、边界和区分度 | 是 | 否 |
| 直接执行质量 | Skill 被加载后能否正确完成任务 | Skill 指令、工具和输出 | 是 | 是 |
| 对比与回归 | Skill 是否带来增益、版本是否退化 | SkillVersion | 是 | 按实验组决定 |

客户原始要求的以下四项属于“直接执行质量”：

- 工具调用正确性；
- 参数准确性；
- 输出格式合规性；
- 内容质量。

为了完整判断“这个 Skill 写得好不好”，P1 同时增加独立的触发质量门禁。触发指标
不与上述四项混为一个不可解释的分数。

---

## 3. 静态质量检查

静态检查不执行测试用例，直接分析 Skill 定义及相关契约。

### 3.1 输入

- Skill 名称、描述和指令正文；
- Skill 输入输出 Schema；
- Skill 可调用工具及参数定义；
- Agent Prompt 中与 Skill 有关的路由说明；
- 同一 Agent 或 Catalog 下的其他 Skill；
- 脚本、依赖、权限和外部资源声明。

### 3.2 检查项

| 评估项 | 检查内容 | 评估方式 |
|---|---|---|
| 结构完整性 | 名称、描述、指令和声明文件是否完整 | 确定性规则 |
| 描述清晰度 | 是否说明用途、输入、输出和适用场景 | 规则 + LLM Judge |
| 触发边界 | 是否明确“适用于”和“不适用于” | 规则 + LLM Judge |
| 声明一致性 | 描述、指令、工具和 Schema 是否一致 | 交叉检查 |
| 能力覆盖 | 声明能力是否有指令、工具或脚本支持 | 规则 + 语义匹配 |
| Skill 内部冲突 | 不同指令是否互相矛盾 | 语义分析 |
| Skill 间冲突 | 是否与其他 Skill 高度重叠或难以区分 | Embedding + LLM |
| Prompt-Skill 错配 | Agent Prompt 的路由要求是否与 Skill 一致 | 规则 + 语义判断 |
| 安全与权限 | 密钥、危险脚本、过度权限和提示注入风险 | 静态扫描 |

静态检查可以发现潜在问题，但不能证明 Skill 运行时一定正确。例如，“描述过宽”可以
被标记为触发风险，是否真的误触发仍需通过动态触发测评验证。

### 3.3 Finding 输出

每个静态问题至少包含：

```text
finding_id
finding_type
severity
affected_skills
confidence
evidence_location
impact
recommendation
review_status
```

---

## 4. 触发质量测评

### 4.1 测评目标

触发测评判断目标 Skill 是否能够：

- 在用户明确指定时被正确加载；
- 在用户未提 Skill 名称、只表达业务意图时被识别；
- 在完整业务上下文中被正确选择；
- 在不适用场景下不被调用；
- 在存在相似 Skill 时不发生混淆。

### 4.2 运行方式

触发测评不能预先指定要调用目标 Skill，否则只能证明 Skill 可获取，不能证明触发
准确性。运行时应向 Agent 提供包含目标 Skill 和干扰 Skill 的候选集合：

```text
用户问题
   ↓
Agent 获取候选 Skill 列表
   ↓
Agent 自主选择 Skill 或不选择
   ↓
记录 available_skills / selected_skill
   ↓
与 expected_skill 对比
```

触发运行属于 Skill 产品报告，但技术实现复用 Agent 路由链路：

```text
Agent Routing Run
       │
       ├── Agent 报告：整个 Agent 的 Skill 路由能力
       │
       └── Skill 报告：目标 Skill 的触发质量
```

同一次运行只能生成一份原始事实和 Trace，两处报告引用同一结果，不能重复执行或重复
计分。

### 4.3 触发测评集

| 用例类型 | 含义 | 示例 | `expected_skill` |
|---|---|---|---|
| 显式正例 | 用户直接说出 Skill 名称 | “使用贷款审批 Skill 审核客户” | 贷款审批 |
| 隐式正例 | 用户只描述业务意图 | “这个客户是否满足放贷条件？” | 贷款审批 |
| 上下文正例 | 意图出现在完整业务上下文中 | 提交客户材料并要求审批结论 | 贷款审批 |
| 近邻负例 | 主题相关但职责不属于目标 Skill | “当前贷款利率是多少？” | `null` 或其他 Skill |
| 混淆例 | 多个相似 Skill 都可能被选择 | “查询这笔贷款的审批进度” | 贷款进度查询 |

负例不能只有天气、翻译等完全无关问题。近邻负例和混淆例才能真正检验 Skill 描述的
边界是否清晰。

建议初始比例：

| 类型 | 建议比例 |
|---|---:|
| 显式正例 | 10% |
| 隐式正例 | 25% |
| 上下文正例 | 20% |
| 近邻负例 | 30% |
| 混淆例 | 15% |

### 4.4 触发指标

| 实际情况 | 判定 |
|---|---|
| 应选择目标 Skill，实际选择目标 Skill | TP：正确触发 |
| 应选择目标 Skill，实际未选择 | FN：漏触发 |
| 不应选择目标 Skill，实际选择目标 Skill | FP：误触发 |
| 不应选择目标 Skill，实际未选择 | TN：正确抑制 |
| 应选择 Skill A，实际选择 Skill B | Skill 混淆 |

| 指标 | 定义 |
|---|---|
| 触发召回率 | `TP / (TP + FN)` |
| 触发精确率 | `TP / (TP + FP)` |
| 误触发率 | `FP / (FP + TN)` |
| 漏触发率 | `FN / (TP + FN)` |
| Skill 混淆率 | 相似 Skill 选择错误的用例比例 |
| 无 Skill 抑制率 | `expected_skill = null` 时正确不选择的比例 |

P1 建议默认门槛：

| 指标 | 默认阈值 |
|---|---:|
| 触发召回率 | ≥ 90% |
| 触发精确率 | ≥ 90% |
| 误触发率 | ≤ 5% |
| Skill 混淆率 | ≤ 10% |

误触发率属于独立门禁，不能通过内容质量等其他高分抵消。

---

## 5. Skill 直接执行测评

### 5.1 测评目标

在明确指定 SkillVersion 的情况下直接加载和执行 Skill，验证 Skill 被选中后是否能够
正确完成任务：

```text
选择 SkillVersion
       ↓
直接加载 Skill
       ↓
执行测试任务
       ↓
评估工具、参数、格式和内容
```

直接测评中成功解析、加载并调用 Skill 可以证明 Skill 可用，但不能证明 Agent 能够在
真实候选集合中正确触发它。

### 5.2 直接测评集

| 用例类型 | 定义 | 示例 |
|---|---|---|
| 正例 | 合法且属于 Skill 能力范围 | 审批一份字段完整的贷款申请 |
| 负例 | 已加载 Skill，但输入缺失、非法、越权或不支持 | 缺少身份证号时安全拒绝 |
| 边界例 | 合法但位于最小值、最大值、零值或业务阈值 | 收入刚好达到审批阈值 |

直接测评的负例不是“Agent 不应该触发该 Skill”，而是 Skill 已加载后是否能正确处理
错误输入，包括结构化报错、拒绝或安全降级，并且不产生非预期副作用。

### 5.3 客户四项评估

| 客户评估项 | 具体评估内容 | 主要证据 |
|---|---|---|
| 工具调用正确性 | 是否调用必需工具、是否调用禁止工具、工具是否选对 | Tool Call Trace |
| 参数准确性 | 参数名、值、类型、必填项和业务约束是否正确 | Tool Arguments Trace |
| 输出格式合规性 | JSON Schema、字段、类型、枚举和结构是否合规 | Final Output/Artifact |
| 内容质量 | 结论是否正确、完整、有依据并符合业务要求 | Final Output + Rule/LLM Judge |

调用次数和调用顺序只在业务流程明确要求“必须调用一次”或“必须先查后写”时作为可选
约束，不作为四项评估的默认必填内容。

### 5.4 直接执行门槛

| 指标 | P1 默认阈值 |
|---|---:|
| 工具调用正确率 | ≥ 95% |
| 参数准确率 | ≥ 95% |
| 输出格式合规率 | 100% |
| 内容质量 | ≥ 80% |
| 评估器错误 | 0 |
| Blocking 用例 | 全部通过 |

不适用项返回 `NOT_APPLICABLE`，不参与平均分；评估器自身异常返回 `ERROR`，不得被
转换为 Skill 运行失败或 0 分。

---

## 6. 测评集与数据模型

### 6.1 复用原则

Agent 测评和 Skill 测评复用相同的 Dataset、DatasetVersion、Case、CaseTurn 和
Expectation 模型，但默认维护为不同的 Dataset 资产和版本链。

```text
公共业务场景
├── 输入
├── 初始状态
└── 预期业务结果
        │
        ├── Agent 测评集
        │   ├── Skill 路由预期
        │   ├── Agent 多轮行为
        │   └── Agent 最终任务结果
        │
        ├── Skill 触发测评集
        │   ├── expected_skill
        │   ├── 候选 Skill 集合
        │   └── 正例、负例和混淆例
        │
        └── Skill 直接测评集
            ├── 预期工具
            ├── 预期参数
            ├── 输出 Schema
            └── 内容质量 Rubric
```

同一份已发布 DatasetVersion 只有在预期语义完全一致时才允许跨 Target 直接使用。
默认做法是从现有 Agent Dataset 复制公共 Case 到新的 Skill Dataset 草稿，由用户
确认并补充 Skill 专属预期。

### 6.2 公共字段

| 字段 | 用途 |
|---|---|
| `case_id` | 用例标识 |
| `input` | 用户输入 |
| `initial_state` | 变量和初始状态 |
| `category` | 用例分类 |
| `difficulty` | 难度 |
| `tags`、`notes` | 分组统计和说明 |
| `expected_output` | 预期输出 |
| `assertions` | 可观察行为断言 |

### 6.3 触发预期字段

| 字段 | 用途 |
|---|---|
| `expected_skill` | 期望选择的 Skill；负例可为 `null` |
| `acceptable_skills` | 可以获得部分路由信用的候选 Skill |
| `candidate_skill_set` | 本次用例的候选 Skill 集合 |
| `trigger_case_type` | explicit、implicit、contextual、negative、confusion |

### 6.4 直接执行预期字段

| 字段 | 用途 |
|---|---|
| `required_tools` | 必须调用的工具 |
| `forbidden_tools` | 禁止调用的工具 |
| `ToolArgumentExpectation` | 工具参数约束 |
| `OutputExpectation` | 输出值或业务规则 |
| `MatchesJsonSchema` | 输出格式约束 |
| `content_rubric` | 内容质量评分标准 |

### 6.5 Skill 关联方式

具体 Skill 不重复写入每条 Case，也不进入 DatasetVersion 的内容哈希。前端选择 Skill，
后端通过外部关联保存：

```text
DatasetTargetAssociation
├── dataset_id
├── platform_id
├── target_type = skill
└── external_target_id
```

关联记录绑定稳定的 Skill 身份；运行时选择具体 SkillVersion，并由 RunSnapshot 固定
本次实际版本。这样同一套用例可以用于多个 SkillVersion 的回归比较。

### 6.6 Agent Case 复用流程

```text
选择 Agent DatasetVersion
        ↓
选择需要复用的 Case
        ↓
选择目标 Skill
        ↓
系统生成转换预览
├── 保留公共输入、状态、分类和标签
├── 按目标类型保留或清除 expected_skill
├── 标记 Agent 专属多轮预期
├── 校验目标 Skill 是否具有预期工具
└── 标记不兼容的输出预期
        ↓
用户确认或修改
        ↓
写入新的 Skill Dataset 草稿并发布
```

复制必须创建新的 Case ID，不修改来源 DatasetVersion。来源通过独立的
`DatasetCaseDerivation` 记录，保证历史版本不可变和可追溯。

---

## 7. 评估器设计

Skill 测评继续复用 Agent 测评现有的 Dimension、EvaluatorSpec、Result、CheckResult、
Evidence、MetricSummary 和 GateDecision，不创建平行的 Skill 结果体系。

| Skill 指标 | 复用或新增评估器 | Dimension |
|---|---|---|
| 触发准确性 | 复用 `SkillRoutingEvaluator` | `ROUTING` |
| 必需工具 | 复用 `RequiredToolEvaluator` | `TOOL_USE` |
| 禁止工具 | 复用 `ForbiddenToolEvaluator` | `TOOL_USE` |
| 参数准确性 | 复用 `ToolArgumentsEvaluator` | `TOOL_USE` |
| 输出格式 | 复用 `FinalOutputEvaluator` + JSON Schema Operator | `ANSWER` |
| 内容质量 | 复用 `FinalOutputEvaluator` + Rule/LLM Judge | `ANSWER` |
| 静态质量 | 新增 Skill Static Evaluator | 独立 Finding |
| Skill 冲突 | 新增 Similarity/Conflict Evaluator | 独立 Finding |
| Skill Lift | 新增 Skill Lift Aggregator | 实验聚合 |

输出格式与内容质量可以复用 `ANSWER` Dimension，但必须拥有不同的 `evaluator_id`、
`metric_key`、阈值和评分原因，报告层分别展示。

---

## 8. Trace 最小契约

### 8.1 触发 Trace

| 字段 | 用途 |
|---|---|
| `available_skills` | Agent 当时可见的候选 Skill |
| `expected_skill` | 测评集定义的期望 Skill |
| `selected_skill` | Agent 实际选择结果 |
| `skill_version` | 被测版本 |
| `selection_stage` | Skill 在哪个阶段被选择 |
| `routing_reason` | 可选的路由解释 |
| `skill_resolved` | 是否成功解析 Skill |
| `skill_loaded` | 是否成功加载 Skill |
| `routing_latency` | 路由耗时 |

必须区分“发现、选择、加载和执行”四个状态，不能使用一个布尔值笼统表示触发成功。

### 8.2 直接执行 Trace

```text
Skill Span
├── skill.id
├── skill.version
├── invocation.id
├── action
└── status

Tool Span
├── tool.name
├── tool.arguments
├── tool.result / result_ref
├── invocation.id
├── turn.id
└── status

Final Outcome
├── output.value
├── output.mime_type
├── output.schema_ref
├── artifact_refs
├── errors
├── latency / token_usage
└── final_state
```

Trace 完整性状态：

| 状态 | 行为 |
|---|---|
| `complete` | 允许进入评估 |
| `incomplete` | 等待补齐；超时后生成执行错误 |
| `conflicted` | 遥测冲突，不生成正常分数 |

---

## 9. 对比与回归

### 9.1 With/Without Skill 配对实验

在固定 Host Agent、模型、Prompt、工具环境和测试输入的前提下，只改变目标 Skill 是否
启用：

```text
同一个 Case
├── With Skill：启用目标 Skill
└── Without Skill：禁用目标 Skill
                         ↓
               比较共同的任务结果
```

```text
Skill Lift = With Skill 任务成功分 - Without Skill 任务成功分
```

没有 Skill 时，专属工具不存在，因此不能给 Without Skill 的工具调用或参数准确性打
0 分。工具不存在的指标应为 `NOT_APPLICABLE`；Lift 主要比较双方共同适用的任务成功、
内容质量、延迟、Token 和成本。

### 9.2 SkillVersion 回归

相同 DatasetVersion、EvaluatorVersion、模型和运行环境下，对 SkillVersion A/B 进行
比较，展示：

- 触发召回、误触发和混淆变化；
- 四项直接执行指标变化；
- 新增、修复和持续存在的 Badcase；
- 延迟、Token 和成本变化；
- 是否触发发布回归门禁。

---

## 10. 评分与发布门禁

不采用一个总平均分决定 Skill 是否合格。静态、触发和执行问题具有不同含义，应使用
分层门禁：

| 门禁 | 通过条件 | 失败结论 |
|---|---|---|
| Gate 1：静态质量 | 无阻断问题，描述和契约一致 | Skill 定义不合格 |
| Gate 2：触发质量 | 召回、精确率、误触发率达标 | Skill 描述或边界不清晰 |
| Gate 3：执行质量 | 客户四项分别达到阈值 | Skill 执行能力不合格 |
| Gate 4：回归质量 | 新版本无阻断性退化 | 新版本不可发布 |

典型判定：

```text
总体结论：不通过

静态质量：通过
触发质量：不通过
  - 触发召回率：96%
  - 误触发率：22%
  - 主要混淆对象：贷款产品咨询 Skill

直接执行质量：通过
  - 工具调用正确性：98%
  - 参数准确性：95%
  - 输出格式合规性：100%
  - 内容质量：91%

结论：
Skill 执行能力合格，但描述范围过宽，在利率查询和还款咨询场景中明显误触发，
暂不允许发布。
```

---

## 11. 测评结果报告

Skill 报告建议包含六个区域：

1. **基本信息**：Skill、版本、Dataset、Evaluator、Agent、模型、Gate 和运行参数；
2. **总体结论**：各层门禁状态以及是否允许发布；
3. **静态质量**：Finding、风险矩阵、Skill 冲突和整改建议；
4. **触发质量**：召回率、精确率、误触发率、混淆 Skill 和路由 Badcase；
5. **直接执行质量**：客户四项得分、失败用例和 Trace 证据；
6. **对比与回归**：With/Without Lift、版本差异、延迟和成本变化。

Badcase 需要展示失败因果链，例如：

```text
Skill 描述覆盖了“所有贷款问题”
    ↓
利率查询被错误路由到贷款审批 Skill
    ↓
调用了审批工具
    ↓
产生不相关的审批输出
```

或：

```text
参数 include_pending 错误
    ↓
工具没有计算待处理交易
    ↓
输出缺少 pending_impact
    ↓
最终可用额度错误
```

---

## 12. 前端产品结构

```text
Skill 测评
├── 测评概览
├── 静态分析
├── 触发测评
├── 直接测评
└── 版本对比
```

### 12.1 触发测评页面

配置区：

- 目标 Skill 和 SkillVersion；
- 触发测评集；
- 候选 Skill 范围；
- Agent 和模型；
- 每条用例运行次数；
- 触发指标阈值。

结果区：

- 召回率、精确率和误触发率；
- TP、TN、FP、FN 分布；
- 易混淆 Skill；
- 误触发和漏触发 Badcase；
- 路由 Trace 和证据。

### 12.2 直接测评页面

- 目标 Skill 和 SkillVersion；
- Skill 专项测评集；
- 四项评估器和门禁配置；
- 四项得分及用例分布；
- Badcase、Tool Trace 和最终输出证据。

---

## 13. 与现有 Agent 测评的关系

| 能力 | Agent 测评 | Skill 测评 | 实施策略 |
|---|---:|---:|---|
| Dataset/Case 模型 | 使用 | 使用 | 复用 |
| Run 调度 | 使用 | 使用 | 复用 |
| Trace 采集 | 使用 | 使用 | 扩展 Skill 稳定字段 |
| Routing Evaluator | 使用 | 触发测评使用 | 复用同一结果 |
| Tool Evaluator | 使用 | 直接测评使用 | 复用 |
| Answer Evaluator | 使用 | 直接测评使用 | 复用 |
| 结果聚合 | Agent 维度 | SkillVersion 维度 | 分开聚合 |
| 发布门禁 | Agent 是否合格 | Skill 是否合格 | 分开配置 |

触发失败可能同时包含两种归因：

- 如果某个 Skill 在多个 Agent/模型上持续误触发，优先归因于 Skill 描述或边界；
- 如果多个 Skill 只在某个 Agent/模型上同时路由失败，优先归因于 Agent 路由能力。

报告应保存 Agent、模型、候选 Skill 集合和 SkillVersion 快照，支持进一步定位，而不是
把所有触发失败都简单归责于 Skill。

---

## 14. AgentGate 改造项

### 14.1 可复用能力

- Dataset、DatasetVersion、Case 和 CaseTurn；
- `required_tools`、`forbidden_tools`、`ToolArgumentExpectation` 和
  `OutputExpectation`；
- Agent Run、Routing Trace、Rule Evaluator 和 LLM Judge；
- Result、CheckResult、Evidence、Metric 和 Gate；
- RunSnapshot、持久化、结果查询和 Trace 查看能力。

### 14.2 P1 必须新增或完成

1. 增加 `TargetType=agent|skill`、SkillRef、SkillVersion 快照和直接调用适配器；
2. 增加 DatasetTargetAssociation 和前端 Skill/SkillVersion 选择；
3. 支持 Skill 触发测评类型以及候选 Skill 集合配置；
4. 在触发用例中支持 `expected_skill=null`、可接受 Skill 和混淆用例；
5. 扩展 Routing Trace，记录候选、选择、解析和加载状态；
6. 复用 SkillRoutingEvaluator，增加触发召回、精确率、误触发率和混淆率聚合；
7. 完成 RequiredTool、ForbiddenTool、ToolArguments、JSON Schema 和内容质量评估；
8. 为格式和内容质量配置独立 Evaluator ID、Metric Key 和展示标签；
9. 增加静态 Finding、描述边界检查和基础 Skill 冲突分析；
10. 增加 Skill 专项报告、分层门禁、Badcase 和证据链；
11. 支持从 Agent Case 复制生成 Skill Dataset 草稿和来源追溯；
12. 提供 Demo Skill，打通静态、触发、直接执行和报告闭环。

---

## 15. 分期计划

| 阶段 | 交付内容 |
|---|---|
| P1 核心闭环 | Skill Target、基础静态检查、触发测评、直接测评四项指标、Trace、Badcase、分层门禁、专项报告和 Demo Skill |
| P2 对比回归 | 语义冲突增强、测评集自动生成、With/Without Skill Lift、SkillVersion A/B、pass@k、历史趋势和回归门禁 |
| P3 平台化 | 深度安全扫描、多 Agent/多模型矩阵、线上触发监控、企业策略包、Skill 认证和自动优化建议 |

P1 实施顺序：

```text
Target/Skill 契约
      ↓
Skill Dataset 与关联关系
      ↓
触发 Run、Routing Trace 与触发指标
      ↓
直接执行适配器与 Tool/Output Trace
      ↓
客户四项评估器
      ↓
静态检查与基础冲突分析
      ↓
分层 Gate、报告与 Badcase
      ↓
Demo 和端到端验收
```

---

## 16. P1 验收标准

1. 前端能够选择 Skill、SkillVersion、测评类型和对应 DatasetVersion；
2. 触发测评时不直接指定目标 Skill 给 Agent，而是提供目标与干扰 Skill 候选集合；
3. 正例能够记录期望 Skill 和实际 Skill，负例支持 `expected_skill=null`；
4. 能正确计算触发召回率、精确率、误触发率和 Skill 混淆率；
5. 误触发超过阈值时，即使直接执行四项合格也不能通过发布门禁；
6. 直接测评能够固定 SkillVersion 并验证工具、参数、格式和内容；
7. 工具选错时定位到 Tool Span，工具正确但参数错误时只判参数项失败；
8. 输出缺字段时格式项失败，格式正确但业务结论错误时内容项失败；
9. 不适用项返回 `NOT_APPLICABLE`，评估器异常返回 `ERROR`；
10. 静态检查能够发现描述过宽、描述与工具不一致和基础 Skill 重叠；
11. 同一次路由运行能够被 Agent 报告和 Skill 报告引用，但不重复计分；
12. 历史 Run 固定保存 Skill、Agent、模型、候选集合、Dataset、Evaluator 和 Gate 版本；
13. Trace 不完整或冲突时不生成误导性的正常分数；
14. 报告能够从失败指标追溯到用例、路由选择、工具参数和最终输出证据。

---

## 17. 最终产品定义

> AgentGate Skill 测评用于评价 Skill 是否能够在正确场景被准确发现，以及被发现后是否
> 能够按照工具、参数、格式和业务要求正确完成任务。

一个 Skill 只有在静态质量、触发质量和直接执行质量均达到门槛时，才能判定为可发布；
With/Without Lift 和版本回归用于进一步解释 Skill 的业务价值与演进质量。

---

## 18. 业界参考

- [NVIDIA SkillEvaluator](https://docs.nvidia.com/skills/skillevaluator)：将 Skill 评估分为
  静态验证、语义去重和真实 Agent 动态评估；Tier 3 包含 Discoverability、Correctness、
  Effectiveness、Efficiency 等维度；
- [NVIDIA SkillEvaluator Eval Datasets](https://docs.nvidia.com/skills/skillevaluator/eval-datasets)：
  使用显式、隐式、上下文和负例测试，并通过 `expected_skill`、`acceptable_skills` 等
  字段验证路由；
- [AWS Sample Agent Skill Eval](https://github.com/aws-samples/sample-agent-skill-eval)：
  将 Trigger Precision 作为 Skill Reliability，通过相关与无关请求验证 Skill 是否在
  正确时机激活。

以上方案仍属于快速演进中的行业实践，而非已经统一的强制标准。本方案吸收其共同
原则，并结合 AgentGate 当前 Agent 测评资产和客户四项要求进行落地。
