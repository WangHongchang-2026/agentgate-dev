# 测评集自动生成原理图（当前实现）

> 当前代码分支：`codex/dataset-auto-generation`
> 当前 Recipe：`dataset-case-generation/v14`

```mermaid
flowchart TB
    U[用户在测评集草稿页<br/>点击「AI 生成用例」]

    subgraph CONFIG[① 生成配置]
        C1[选择 Agent 或 Skill<br/>并锁定具体版本]
        C2[设置数量、轮次、分类、难度]
        C3[可选：参考已发布用例<br/>与补充业务要求]
    end

    subgraph INPUT[② 能力信息读取（只读）]
        TC[Target Catalog<br/>当前为 Fake Agent / Fake Skill]
        TD[TargetDescriptor<br/>能力说明 · Skill · 工具<br/>工具参数 Schema · 输入/输出 Schema]
        DS[Dataset Service<br/>读取可选参考版本和 Case]
    end

    subgraph CORE[③ AgentGate 生成核心]
        PRE[请求预检<br/>草稿 Hash · 配额 · 安全主题<br/>版本身份 · Descriptor Hash]
        PLAN[确定性 Case Plan<br/>预先固定 slot_index<br/>分类 · 难度 · 轮次数]
        PROMPT[构造 System Prompt<br/>+ 脱敏后的生成素材<br/>+ 动态 strict JSON Schema]
    end

    subgraph MODEL[④ 外部大模型]
        ADAPTER[Model Provider Adapter<br/>凭据 · 并发 · 超时 · 重试]
        QWEN[阿里百炼 Qwen<br/>只生成简化 Case Blueprint]
        BP[Blueprint<br/>名称 · 每轮输入 · expected_skill<br/>必调/禁调工具 · 参数 · 输出关键词]
    end

    subgraph COMPILE[⑤ 确定性编译与质量门禁]
        COMPILER[Blueprint → Canonical Case<br/>系统生成 Case/Turn/Expectation ID<br/>工具参数叶子 → Path + Equals<br/>output_schema → 结构期望]
        CHECK[逐条校验<br/>Schema · Skill/工具存在性<br/>参数/Path · 轮次 · 配额 · 安全]
        DEDUP[精确去重<br/>对比当前 Draft 与本批候选]
    end

    subgraph REVIEW[⑥ 人工审核与入库]
        LIST[候选列表<br/>合法候选 + 字段级错误]
        EDIT[用户查看、自由编辑、重新校验<br/>复验正式 Case 与 Target 规则]
        ACCEPT[批量接收<br/>Token/来源槽位 · Draft Hash 校验<br/>幂等 · 原子写入]
        DRAFT[(Dataset Draft<br/>保存 Case 与生成来源)]
        PUBLISH[用户继续验证并手动发布]
    end

    ERR[无效候选<br/>保留 issues，不写入草稿]

    U --> C1
    U --> C2
    U --> C3
    C1 --> TC --> TD --> PRE
    C3 --> DS --> PRE
    C2 --> PRE
    PRE --> PLAN --> PROMPT --> ADAPTER --> QWEN --> BP
    BP --> COMPILER --> CHECK --> DEDUP --> LIST
    CHECK -- 校验失败 --> ERR
    DEDUP -- 重复 --> ERR
    LIST --> EDIT
    EDIT -- 重新校验 --> CHECK
    EDIT -- 接收合法候选 --> ACCEPT --> DRAFT --> PUBLISH

    classDef user fill:#E8F1FF,stroke:#2563EB,color:#172554,stroke-width:1.5px;
    classDef source fill:#F3E8FF,stroke:#7C3AED,color:#3B0764,stroke-width:1.5px;
    classDef core fill:#E6FFFA,stroke:#0F766E,color:#134E4A,stroke-width:1.5px;
    classDef model fill:#FFF7ED,stroke:#EA580C,color:#7C2D12,stroke-width:1.5px;
    classDef review fill:#F0FDF4,stroke:#16A34A,color:#14532D,stroke-width:1.5px;
    classDef error fill:#FEF2F2,stroke:#DC2626,color:#7F1D1D,stroke-width:1.5px;

    class U,C1,C2,C3 user;
    class TC,TD,DS source;
    class PRE,PLAN,PROMPT,COMPILER,CHECK,DEDUP core;
    class ADAPTER,QWEN,BP model;
    class LIST,EDIT,ACCEPT,DRAFT,PUBLISH review;
    class ERR error;
```

## 一句话理解

**Target 提供能力边界，模型设计业务场景，后端把场景编译成可执行、可机器判定的 Case，用户审核后才进入测评集草稿。**

## 当前边界

- 模型不会直接生成完整领域 Case，也不负责生成 ID、Condition 和 Path。
- 候选不会自动入库、自动发布或自动启动评测。
- 单条候选失败不会影响同批其他合法候选。
- 当前 Target Catalog 使用 Fake Agent/Skill；真实平台后续只需实现相同的只读 `TargetDescriptor` 适配接口。
