# Static Skill Analysis

`skill_analysis/` is a top-level evaluation capability that checks externally owned
Agent and Skill definitions without executing test Cases.

## Product Position

```text
Agent Evaluation
├── Static evaluation: skill_analysis/
└── Dynamic evaluation: evaluator/ + run/
```

Static analysis reads an exact `TargetDescriptor` and checks Skill-description quality,
Skill conflict or confusion, Agent-Prompt-to-Skill alignment, Skill-Prompt-to-Tool
alignment, coverage, and fallback definitions. It produces reviewable findings and a
static risk matrix.

It remains separate from post-run optimization:

```text
skill_analysis/  Definition checks without Agent execution
evaluator/       Scores actual Case executions
optimizer/       Analyzes failed Runs, Results, and Traces
```

## Target Structure

```text
skill_analysis/
├── __init__.py
├── analyzer_protocol.py
├── models.py
├── description_quality.py
├── skill_relationships.py
├── prompt_alignment.py
├── llm_semantic.py
└── pipeline.py
```

- `analyzer_protocol.py`: common static-analyzer contract.
- `models.py`: non-persisted runtime inputs, candidates, features, and errors.
- `description_quality.py`: deterministic Skill-description quality checks.
- `skill_relationships.py`: overlap, conflict, and confusion checks between Skills.
- `prompt_alignment.py`: Agent Prompt, Skill Prompt, description, and Tool alignment.
- `llm_semantic.py`: bounded semantic checks through an injected model provider.
- `pipeline.py`: analyzer execution, finding merge, and static risk-matrix construction.

Persisted specifications, findings, reviews, and reports belong in
`domain/skill_analysis.py`. Target resolution, persistence, invocation, and review
workflows belong in `application/skill_analysis.py`. HTTP endpoints later belong in
`server/routes/skill_analysis.py`.

Do not label the static risk matrix as an observed confusion matrix. An observed confusion
matrix requires executed Cases and belongs in `optimizer/`.

The [archived behavior plan](../history/planning-v1/skill-static-analysis-plan.md) retains useful checks and
acceptance criteria, but its pre-refactor file map is not authoritative.
