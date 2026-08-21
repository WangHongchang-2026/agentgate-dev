# Evaluator Refactor File Plan

This document records the implemented file-level change set for the evaluator refactor.

Status labels:

- `[ADD]`: create a new file.
- `[MOD]`: modify an existing file.
- `[DEL]`: remove an obsolete file.
- Files not shown remain unchanged.

```text
agentgate-goal/
├── src/agentgate/
│   │
│   ├── contracts.py                         [DEL] Replaced by focused domain models
│   │
│   ├── domain/                              [ADD] Shared Pydantic data contracts
│   │   ├── __init__.py                      [ADD] Export public domain models
│   │   ├── base.py                          [ADD] Immutable DomainModel, canonical JSON, hashing
│   │   ├── expectation.py                   [ADD] Expectations and readable Conditions
│   │   ├── case.py                          [ADD] Case and Dataset definitions
│   │   ├── trace.py                         [ADD] Canonical Trace, spans, final_state/output
│   │   ├── evaluation.py                    [ADD] Rule/Judge/Hybrid specs and Judge snapshots
│   │   ├── result.py                        [ADD] CheckResult, Result, Outcome, FailureStage
│   │   ├── metric.py                        [ADD] MetricPlan and MetricSummary
│   │   ├── gate.py                          [ADD] GateSpec and GateDecision
│   │   ├── run.py                           [ADD] Run, RunSnapshot, RunStatus
│   │   └── report.py                        [ADD] Complete RunReport model
│   │
│   ├── evaluator/
│   │   ├── __init__.py                      [MOD] Export evaluator public API and register rules
│   │   ├── core.py                          [DEL] Remove old five-function evaluator implementation
│   │   ├── models.py                        [MOD] Runtime Evaluation and Observation models
│   │   ├── base.py                          [MOD] Evaluator abstract interface
│   │   ├── registry.py                      [MOD] Evaluator/operator registration and resolution
│   │   ├── validation.py                    [ADD] Validate Dataset and evaluation plan before Run
│   │   ├── observations.py                  [ADD] Read Trace values; define MISSING sentinel
│   │   ├── calc_score.py                    [ADD] Convert multiple checks into one Result
│   │   ├── runner.py                        [MOD] Execute evaluators; handle N/A, ERROR and dependencies
│   │   │
│   │   ├── operators/
│   │   │   ├── __init__.py                  [ADD] Export comparison operators
│   │   │   ├── comparison.py                [ADD] equals, range, tolerance, pattern, missing
│   │   │   └── collection.py                [ADD] contains_all and contains_none
│   │   │
│   │   ├── rules/
│   │   │   ├── __init__.py                  [ADD] Register P1 Rule evaluators
│   │   │   ├── routing.py                   [ADD] Skill-routing evaluation
│   │   │   ├── tool_use.py                  [ADD] Required/forbidden tool and argument checks
│   │   │   ├── state.py                     [ADD] Final-state checks
│   │   │   └── policy.py                    [ADD] Policy-compliance checks
│   │   │
│   │   ├── builtin/                         [DEL] Empty old structure replaced by rules/
│   │   │   ├── __init__.py                  [DEL]
│   │   │   ├── cost.py                      [DEL]
│   │   │   ├── final_answer.py              [DEL]
│   │   │   ├── final_state.py               [DEL]
│   │   │   ├── forbidden_tool.py            [DEL]
│   │   │   ├── latency.py                   [DEL]
│   │   │   ├── policy.py                    [DEL]
│   │   │   ├── required_tool.py             [DEL]
│   │   │   ├── tool_arguments.py            [DEL]
│   │   │   └── trajectory.py                [DEL]
│   │   │
│   │   ├── llm_judge/
│   │   │   └── README.md                    [ADD] Document P2 LLM Judge scope
│   │   └── hybrid/
│   │       └── README.md                    [ADD] Document P2 Hybrid scope
│   │
│   ├── result/
│   │   ├── __init__.py                      [MOD] Export reporting services
│   │   ├── calc_metrics.py                  [ADD] Calculate metric/dimension/kind/overall summaries
│   │   ├── gate.py                          [ADD] Apply threshold, blocking veto and fail-closed rules
│   │   ├── service.py                       [MOD] Build RunReport from results, metrics and gate
│   │   ├── aggregate.py                     [DEL] Replaced by calc_metrics.py
│   │   ├── gates.py                         [DEL] Replaced by gate.py
│   │   ├── models.py                        [DEL] Models moved to domain/
│   │   └── report.py                        [DEL] Report model moved to domain/report.py
│   │
│   ├── run/
│   │   └── core.py                          [MOD] Validate plan and snapshot MetricPlan/GateSpec/hash
│   │
│   ├── control_plane/
│   │   └── core.py                          [MOD] Remove hard-coded evaluator/metric mappings
│   │
│   ├── demo/
│   │   └── loan.py                          [MOD] Use Expectations and emit routing spans
│   │
│   ├── storage/
│   │   ├── base.py                          [MOD] Import new domain types
│   │   └── sqlite.py                        [MOD] Canonical JSON persistence and snapshot hash checks
│   │
│   ├── trace/
│   │   ├── normalizer.py                    [MOD] Convert received telemetry to canonical Trace
│   │   └── receivers/
│   │       ├── __init__.py                  [MOD] Export OTLP/HTTP receiver
│   │       └── otlp_http.py                 [MOD] Parse real OTLP/HTTP POST payloads
│   │
│   ├── server/
│   │   └── application.py                   [MOD] Delegate OTLP ingestion; update API response models
│   │
│   └── cli/
│       └── application.py                   [MOD] Render the new RunReport and GateDecision
│
├── web/
│   ├── vite.config.ts                       [MOD] Configurable API proxy for isolated tests
│   ├── playwright.config.ts                 [MOD] Dedicated ports and per-run test database
│   ├── src/
│   │   ├── api/client.ts                    [MOD] New outcomes, nullable scores and report types
│   │   ├── App.vue                          [MOD] Evaluator categories, summaries and check details
│   │   └── style.css                        [MOD] New report/error/N/A presentation
│   └── tests/
│       └── demo.spec.ts                     [MOD] Real launch/report tests on desktop and mobile
│
├── tests/
│   ├── test_contracts.py                    [DEL] Replaced by focused domain tests
│   ├── test_domain_models.py                [ADD] Domain contract validation
│   ├── test_expectations.py                 [ADD] Expectation and Condition behavior
│   ├── test_snapshot_immutability.py        [ADD] Deep immutability and snapshot hashing
│   ├── test_evaluator_validation.py         [ADD] Invalid evaluation-plan cases
│   ├── test_observations.py                 [ADD] Trace extraction, null versus MISSING
│   ├── test_operators.py                    [ADD] Operator truth tables
│   ├── test_evaluator_runner.py             [ADD] N/A, ERROR, dependency and timeout behavior
│   ├── test_rule_evaluators.py              [ADD] Six P1 Rule evaluators
│   ├── test_metrics.py                      [ADD] Metric aggregation algorithms
│   ├── test_gate.py                         [ADD] Threshold, blocking and fail-closed behavior
│   ├── test_otlp_http.py                    [ADD] Real POST ingestion and normalization
│   ├── test_api.py                          [MOD] New report/API response structure
│   ├── test_cli.py                          [MOD] New CLI report structure
│   ├── test_demo_engine.py                  [MOD] Risky fails; fixed passes; six evaluators
│   ├── test_metrics_api.py                  [MOD] Metric/dimension/kind/overall summaries
│   ├── test_python_target.py                [MOD] Import new domain models
│   └── test_imports.py                      [MOD] Ensure removed contracts/core imports are absent
│
└── docs/
    ├── evaluator/refactor-plan.md            [ADD] Architecture, behavior, and terminology plan
    ├── evaluator/file-plan.md       [ADD] This file-level change map
    ├── arch.md                               [MOD] New domain/evaluator/result architecture
    ├── capability-mapping.md                 [MOD] Rule / LLM Judge / Hybrid terminology
    └── progress.md                           [MOD] Checkpoints, verification, and remaining P2 work
```

## Unchanged in P1

- `pyproject.toml`: JSON Schema execution and its dependency remain deferred.
- `src/agentgate/experiment/`: A/B consistency validation remains P2.
- `src/agentgate/evaluator/external/`: existing third-party adapter boundary remains unchanged.
- `src/agentgate/result/compare.py`: comparison work remains deferred.
- SQLite table layout: P1 starts with a fresh database and does not implement V1-to-V2 migration.
- LLM Judge and Hybrid runtime code: only their contracts and scope documentation are added.
