# Result

The Result capability owns derived evaluation conclusions:

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

## Implemented rerun comparison

`result/comparison.py` contains pure comparison rules for matching original and rerun
results by Evaluator ID and classifying changes as `improved`, `regressed`, `unchanged`,
or `incomparable`; mixed result sets are reported as `mixed`.

`application/result_reader.py` assembles the comparison response, including root,
parent, and rerun identities. The Web and HTTP layers consume that response without
reimplementing comparison policy.
