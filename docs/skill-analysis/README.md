# Static Skill Analysis

Static Skill Analysis checks externally owned Agent definitions without executing
test Cases. The POC analyzes whether Skill descriptions overlap, conflict, duplicate
one another, or make routing ambiguous.

## Position

```text
Agent Evaluation
├── Static definition checks: skill_analysis/
└── Dynamic execution checks: run/ + evaluator/
```

Static analysis is also separate from post-run optimization:

```text
skill_analysis/  Checks an exact Target definition before execution
evaluator/       Scores observed Case executions
optimizer/       Analyzes failures from Runs, Results, and Traces
```

## POC Structure

```text
src/agentgate/
├── domain/skill_analysis.py
├── skill_analysis/
│   ├── __init__.py
│   └── relationships.py
├── application/skill_analysis.py
├── storage/
│   ├── repository.py
│   └── sqlite.py
└── server/routes/skill_analysis.py
```

- `domain/skill_analysis.py` defines immutable findings and reports plus human reviews.
- `skill_analysis/relationships.py` compares every unique Skill-description pair
  through an injected Judge model client.
- `application/skill_analysis.py` resolves exact Target descriptors, runs analysis,
  persists reports, and validates finding reviews.
- `storage/` stores immutable reports and one current review per report finding.
- `server/routes/skill_analysis.py` exposes analysis, report, and review workflows.

No analyzer base class, registry, factory, or generic pipeline is required for the POC.

## Call Chain

```text
HTTP request
    |
    v
SkillAnalysis application workflow
    |
    +--> resolve exact TargetDescriptor by content hash
    +--> analyze_skill_relationships(...)
    +--> save immutable SkillAnalysisReport
    +--> save/update human SkillAnalysisReview
```

The analyzer receives the persisted `TargetDescriptor`; it does not fetch Agent data
from an external platform independently.

## Analysis Contract

For `n` Skills, the analyzer evaluates `n * (n - 1) / 2` stable, unique pairs. Each
model response must be a bounded JSON object classified as:

- `none`
- `overlap`
- `ambiguous`
- `conflict`
- `duplicate`

Descriptions are redacted before they are sent to the model. Invalid responses,
timeouts, and provider failures become sanitized report errors. Successful pairs remain
available when other pairs fail, producing a `partial` report.

The report stores a static risk matrix. It must not be presented as an observed
confusion matrix: an observed confusion matrix requires executed Cases and belongs in
`optimizer/`.

## HTTP API

```text
POST /api/skill-analysis/reports
GET  /api/skill-analysis/reports?target_descriptor_sha256=...
GET  /api/skill-analysis/reports/{report_id}
PUT  /api/skill-analysis/reports/{report_id}/findings/{finding_id}/review
```

Reports are immutable. A review is stored separately and the POC keeps one current
review for each `(report_id, finding_id)` pair.

## Model Configuration

The standalone server reuses the optional Judge model configured by:

```text
AGENTGATE_JUDGE_PROVIDER_ID
AGENTGATE_JUDGE_BASE_URL
AGENTGATE_JUDGE_API_KEY
AGENTGATE_JUDGE_MODEL_ID
```

Without this configuration, report and review reads remain available, while starting
new analysis returns HTTP `503`. Future shared/private credential selection will replace
this process-level POC configuration without changing the application contract.

## Deferred

- Agent-Prompt-to-Skill and Skill-Prompt-to-Tool alignment.
- Deterministic description-quality checks.
- Embedding or lexical pre-filtering for large Skill catalogs.
- Analyzer plugins and configurable analysis pipelines.
- Automatic analysis during Agent creation or EvaluationRun creation.
- Observed routing confusion matrices and optimization suggestions.

The [archived behavior plan](../history/planning-v1/skill-static-analysis-plan.md)
contains broader research ideas, but its file map and API paths are not authoritative.
