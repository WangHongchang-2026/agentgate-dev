# Result

The Result capability owns derived evaluation conclusions:

`metrics.py`, `gate.py`, and `report.py` are implemented. `comparison.py` is a future
module and will be created only with an approved regression or A/B workflow. See
[project progress](../project-progress.md).

```text
result/
├── metrics.py
├── gate.py
├── report.py
└── comparison.py
```

Domain Result models belong in `domain/`. Read-only retrieval and assembly for Web, CLI,
and APIs belongs in `application/result_reader.py`. Persistence belongs in `storage/`,
and optional external delivery belongs in `integrations/result_outputs/`.

Result does not execute Evaluators, invoke Agents, collect Traces, or render Web charts.

## Gate and Report Rules

- `MetricPlan` selects a versioned algorithm; unsupported versions fail explicitly.
- Metric keys are machine identifiers. Localized labels belong to the Web layer.
- One metric key cannot be assigned to multiple quality dimensions in one Run.
- `metrics.py` is the only source of calculated scores. `gate.py` consumes the overall
  metric instead of calculating another score.
- `gate.py` fails closed when primary Results are missing, reviewed, errored, contain a
  blocking failure, or provide no applicable score. Individual not-applicable Results do
  not block a Run that still has a valid applicable score.
- Gate decisions carry a typed reason code; the Web layer owns translated display text.
- Result counts live in Metrics rather than being duplicated on the Gate decision.
- Metrics do not expose an ambiguous `incomplete` flag: evaluator errors use the `errors`
  count, while missing expected Results use `ReleaseGateDecision.missing_results`.
- `report.py` assembles a completed Run, Results, Metrics, and release-gate decision.
- `EvaluationReport` validates Result identities and evaluator metadata against the
  immutable `RunManifest`, including the expected Case-by-primary-Evaluator matrix.
