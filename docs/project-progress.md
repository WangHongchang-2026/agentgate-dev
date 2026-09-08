# AgentGate Project Progress

Last updated: 2026-09-08

## Status Legend

- `[x]`: implemented and covered by the current test suite.
- `[ ]`: not implemented or not yet accepted as complete.
- Paths marked **new** do not exist yet.
- This checklist tracks the complete POC direction. Deferred production work is
  listed separately and is not required to finish the initial demo.

## Core Foundation

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Domain models | Define Dataset, Case, Run, Trace, Result, Target, and Evaluator concepts | `src/agentgate/domain/` |
| [x] | SQLite storage | Persist the POC domain objects | `src/agentgate/storage/sqlite.py` |
| [x] | Repository contract | Isolate application workflows from storage implementations | `src/agentgate/storage/repository.py` |
| [ ] | Artifact storage | Store files, screenshots, reports, and generated outputs | `src/agentgate/storage/artifacts.py` **new** |
| [x] | Storage cleanup | Remove obsolete or empty storage code after migration | `src/agentgate/storage/` |

## Dataset

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Dataset management | Create, edit, archive, publish, and version Datasets | `src/agentgate/application/dataset_management.py` |
| [x] | Dataset loading | Convert external data into Dataset and Case models | `src/agentgate/dataset/loader.py` |
| [x] | JSON format | Import and export complete Dataset structures | `src/agentgate/dataset/formats/json.py` |
| [x] | Excel format | Import existing single-sheet customer files | `src/agentgate/dataset/formats/xlsx.py` |
| [x] | Multi-turn Cases | Store multiple conversation turns in one Case | `src/agentgate/domain/case.py` |
| [ ] | Dataset sampling | Select reproducible smoke, regression, tagged, or risk-based subsets | `src/agentgate/dataset/sampling.py` **new**; planned after 2026-09-15 |
| [ ] | Dataset generation | Generate positive, negative, and boundary Cases from Agent metadata | `src/agentgate/dataset/generation/` **new**; planned after 2026-09-15 |
| [ ] | Public benchmarks | Import selected public evaluation datasets | `src/agentgate/dataset/benchmarks/` **new**; planned after 2026-09-15 |

## Evaluator And Result

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Rule evaluation | Evaluate routing, Tool use, state, policy, and output | `src/agentgate/evaluator/rule/` |
| [x] | Metrics | Aggregate Case Results into Run metrics | `src/agentgate/result/metrics.py` |
| [x] | Release gate | Decide whether a version passes evaluation | `src/agentgate/result/gate.py` |
| [x] | Report | Build the complete evaluation report | `src/agentgate/result/report.py` |
| [x] | Evaluator structure | Separate protocol, executor, runtime models, and Rule responsibilities | `src/agentgate/evaluator/` |
| [x] | JSON Schema Rule evaluation | Validate structured values with Draft 2020-12 structure, required-field, value, and composition keywords; allow safe local JSON Pointers; and reject invalid schemas during Run preflight for output, state, routing, and Tool-argument expectations | `src/agentgate/evaluator/rule/json_schema.py`, `src/agentgate/evaluator/rule/operators.py`, `src/agentgate/application/evaluator_management.py` |
| [x] | LLM Judge | Perform redacted case-level semantic answer-quality evaluation through configured models | `src/agentgate/evaluator/judge/` |
| [x] | OpenAI-compatible model transport | Call preconfigured public or private Chat Completions endpoints using resolved credentials | `src/agentgate/integrations/model_providers/` |
| [x] | POC Judge environment configuration | Build one optional process-level model connection from four environment variables, remain Rule-only when absent, and reject partial configuration | `src/agentgate/integrations/model_providers/environment.py` |
| [ ] | Persistent model provider configuration | Store allowlisted endpoints, managed secrets, and production credential resolution for application use | Design required before implementation |
| [ ] | Multimodal evaluation | Evaluate files, images, and other Artifacts | `src/agentgate/evaluator/judge/multimodal.py` **new**; planned after 2026-09-15 |
| [ ] | Result comparison | Compare two compatible EvaluationRuns | `src/agentgate/result/comparison.py` **new** |

## Trace And Target Execution

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Trace model | Represent normalized Agent behavior | `src/agentgate/domain/trace.py` |
| [x] | OTel capture | Capture real demo Agent spans | `src/agentgate/integrations/observability/in_memory.py` |
| [x] | OTLP receiver | Receive external OTLP JSON traces | `src/agentgate/integrations/observability/otlp_http_receiver.py` |
| [x] | Demo Agent adapter | Execute the Loan Agent | `src/agentgate/integrations/targets/demo_loan.py` |
| [x] | Target protocol | Standardize one Case execution | `src/agentgate/run/target_protocol.py` |
| [x] | Trace redaction | Remove secrets and private data before evaluation or display | `src/agentgate/trace/redaction.py` |
| [ ] | HTTP Agent adapter | Invoke Dify, Coze, or customer Agents | `src/agentgate/integrations/targets/http_agent.py` **new** |
| [ ] | Local process adapter | Execute CLI-based Agents | `src/agentgate/integrations/targets/process_agent.py` **new** |
| [ ] | Trace replay adapter | Evaluate an existing Trace without reinvoking an Agent | `src/agentgate/integrations/targets/trace_replay.py` **new** |
| [x] | Trace cleanup | Remove obsolete Trace scaffolds after migration | `src/agentgate/trace/` |

## Run, Queue, And Scheduler

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Run Engine | Execute every Case and invoke selected Evaluators | `src/agentgate/run/engine.py` |
| [x] | Worker claiming | Prevent two workers from executing the same Run | `src/agentgate/storage/sqlite.py` |
| [x] | Incremental persistence | Save each Case's Results as soon as evaluation finishes | `src/agentgate/run/engine.py` |
| [x] | Dispatcher protocol | Define whole-Run submission through `submit(run_id)` | `src/agentgate/integrations/job_dispatchers/protocol.py` |
| [x] | Dispatch workflow | Submit persisted Runs and fail dispatch errors safely | `src/agentgate/application/run_management.py` |
| [x] | Stale-Run recovery | Fail Runs abandoned by an expired worker | `src/agentgate/application/run_management.py` |
| [x] | Progress projection | Calculate completed Cases and Run progress from Results | `src/agentgate/application/result_reader.py` |
| [x] | Activity projection | Return queued, running, and recent terminal Runs | `src/agentgate/application/result_reader.py` |
| [x] | Celery dispatcher | Submit `run_id` through Redis | `src/agentgate/integrations/job_dispatchers/celery.py` |
| [x] | Celery worker | Load and execute the persisted Run with the same optional Judge catalog and task-local client cleanup | `src/agentgate/integrations/job_dispatchers/celery.py` |
| [ ] | Customer scheduler integration | Accept work from an external Java scheduler through the shared Run boundary | `src/agentgate/server/routes/runs.py` or `src/agentgate/integrations/job_dispatchers/`; planned after POC |
| [ ] | Retry mechanics | Retry classified infrastructure failures only | `src/agentgate/run/retry.py` **new** |
| [ ] | Local process management | Start, monitor, limit, and stop local Agent processes | `src/agentgate/run/process_manager.py` **new** |
| [ ] | Run Artifact collection | Register files and reports produced during execution | `src/agentgate/run/artifacts.py` **new** |
| [x] | Run cleanup | Remove legacy core, scheduler, lifecycle, model, and adapter placeholder files | `src/agentgate/run/` |

## Application And Server

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Dataset application service | Coordinate Dataset workflows | `src/agentgate/application/dataset_management.py` |
| [x] | Run application service | Coordinate Run creation, dispatch, and execution | `src/agentgate/application/run_management.py` |
| [x] | Result reader foundation | Read persisted Runs, Results, Traces, and reports | `src/agentgate/application/result_reader.py` |
| [x] | FastAPI foundation | Expose current Dataset, Run, Result, and Trace APIs | `src/agentgate/server/` |
| [ ] | Target catalog | Read external Agent and Skill metadata from Dify, Coze, or customer platforms | `src/agentgate/application/target_catalog.py` **new**; planned after POC |
| [x] | Evaluator management | Persist user identities and drafts, publish immutable versions, control availability, select exact specifications, and compose supported implementations | `src/agentgate/application/evaluator_management.py`, `src/agentgate/evaluator/versioning.py`, `src/agentgate/storage/sqlite.py` |
| [x] | Evaluator Catalog API | Expose built-in and user identities, drafts, publication, exact versions, enable state, and constrained deletion | `src/agentgate/server/routes/evaluators.py` |
| [x] | Judge API/worker wiring | Create API manifests and reconstruct worker execution from identical optional Judge configuration with process/task lifecycle cleanup | `src/agentgate/application/evaluator_management.py`, `src/agentgate/server/`, `src/agentgate/integrations/job_dispatchers/celery.py` |
| [ ] | Model provider management API | Configure provider endpoints, model options, and secret references without exposing credentials | Design required before implementation |
| [ ] | Skill analysis service | Coordinate static Skill analysis | `src/agentgate/application/skill_analysis.py` **new** |
| [ ] | Lineage queries | Find Runs by Dataset, Target, Evaluator, Prompt, or model version | `src/agentgate/application/lineage_queries.py` **new** |
| [x] | Asynchronous Run API | Create a Run, dispatch it, and return `202 Accepted` | `src/agentgate/server/routes/runs.py` |
| [x] | Run activity API | Expose queue, running status, progress, and history | `src/agentgate/server/routes/runs.py` |
| [ ] | API contract review | Finalize response models and sanitized error behavior | `src/agentgate/server/` |

## CLI

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | CLI refactor | Call the same application services used by FastAPI | `src/agentgate/cli/` |
| [x] | Dataset commands | Import, export, list, publish, and inspect Datasets | `src/agentgate/cli/dataset_commands.py` |
| [x] | Run commands | Execute Runs and inspect queue or execution status | `src/agentgate/cli/run_commands.py` |
| [x] | Result commands | Retrieve reports, metrics, failed Cases, protected Traces, and Gate conclusions | `src/agentgate/cli/result_commands.py` |
| [x] | Legacy cleanup | Remove CLI dependencies on the old Control Plane and Run core | `src/agentgate/cli/`, `src/agentgate/application/` |
| [x] | CLI tests | Verify commands through application boundaries | `tests/test_cli.py`, `tests/test_cli_*_commands.py` |

The CLI now composes the same Dataset, Run, and Result application boundaries used by
the server. Removing the remaining legacy Control Plane test callers is separate cleanup.

## Web

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Dataset workspace foundation | Browse and edit Dataset content | `web/src/pages/DatasetWorkspace.vue` |
| [x] | Web routing | Provide Vue Router navigation for implemented pages | web/src/router/, web/src/layouts/AppLayout.vue |
| [ ] | Overview | Show Dataset and Run status statistics | `web/src/pages/OverviewPage.vue` **new** |
| [x] | Run workspace | Show lifecycle counters plus queued, running, and historical work | `web/src/pages/RunWorkspacePage.vue` |
| [x] | Progress polling | Refresh every two seconds while active work exists and stop at terminal state | `web/src/api/runs.ts`, `web/src/pages/RunWorkspacePage.vue` |
| [ ] | Result center | Browse completed and failed Runs | `web/src/pages/ResultCenterPage.vue` **new** |
| [ ] | Result detail | Show metrics, release gate, badcases, evidence, and Trace attribution | `web/src/pages/ResultDetailPage.vue` **new** |
| [ ] | Evaluator management | Configure Rule, Judge, and Hybrid Evaluators | `web/src/pages/EvaluatorWorkspacePage.vue` **new** |
| [ ] | Model provider settings | Configure provider connections and available Judge models | `web/src/pages/ModelProviderSettingsPage.vue` **new** |
| [ ] | Skill analysis | Display Skill conflicts and prompt mismatches | `web/src/pages/SkillAnalysisPage.vue` **new** |
| [ ] | Optimizer | Display failure clusters and suggestions | `web/src/pages/OptimizerPage.vue` **new** |
| [x] | Browser verification | Verify desktop and mobile workflows against Redis, Celery, FastAPI, and SQLite | `web/tests/` |

Visible Web labels remain Chinese. Source identifiers, API fields, TypeScript names,
and comments remain English.

## A/B Testing

| Status | Capability | Function | Code location |
|---|---|---|---|
| [ ] | A/B definition | Bind two Target versions to one Dataset and evaluation configuration | `src/agentgate/application/ab_testing.py` **new** |
| [ ] | A/B execution | Create two ordinary EvaluationRuns through RunManagement | `src/agentgate/application/ab_testing.py` **new** |
| [ ] | A/B comparison | Compare scores, pass rates, latency, and failure categories | `src/agentgate/result/comparison.py` **new** |
| [ ] | Significance | Calculate confidence and statistical significance | `src/agentgate/result/statistics.py` **new** |
| [ ] | A/B API | Start and retrieve A/B comparisons | `src/agentgate/server/routes/comparisons.py` **new** |
| [ ] | A/B Web page | Display variants, differences, confidence, and winner | `web/src/pages/ComparisonPage.vue` **new** |

A/B testing composes ordinary Runs. It does not require a broad top-level
`experiment/` package for the POC.

## Skill Analysis And Optimizer

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Skill analysis domain | Define static analysis findings and reports | `src/agentgate/domain/skill_analysis.py` |
| [ ] | Analyzer contract | Define the common static analyzer input/output boundary | `src/agentgate/skill_analysis/analyzer_protocol.py` **new** |
| [ ] | Description checks | Check clarity, completeness, and routability | `src/agentgate/skill_analysis/description_quality.py` **new** |
| [ ] | Skill relationships | Detect overlap, conflict, and confusion among Skills | `src/agentgate/skill_analysis/skill_relationships.py` **new** |
| [ ] | Prompt alignment | Compare Agent Prompt, Skill Prompt, description, Tools, and capability | `src/agentgate/skill_analysis/prompt_alignment.py` **new** |
| [ ] | Semantic Skill checks | Run bounded LLM-assisted definition analysis | `src/agentgate/skill_analysis/llm_semantic.py` **new** |
| [ ] | Skill analysis pipeline | Compose analyzers and build the static risk matrix | `src/agentgate/skill_analysis/pipeline.py` **new** |
| [ ] | Failure clustering | Group similar badcases | `src/agentgate/optimizer/clustering.py` |
| [ ] | Confusion matrix | Measure expected versus actual Skill routing | `src/agentgate/optimizer/clustering.py` |
| [ ] | Root-cause analysis | Explain common failure causes | `src/agentgate/optimizer/root_cause.py` |
| [ ] | Suggestions | Produce reviewable optimization recommendations | `src/agentgate/optimizer/suggestions.py` |
| [x] | Optimizer cleanup | Remove the rejected generic service wrapper | `src/agentgate/optimizer/service.py` |

Optimizer work is the final POC feature group and will receive a separate detailed
plan before implementation.

## Verification And Delivery

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Current backend regression | Verify current refactor and persistent Evaluator Catalog behavior | `tests/` - 592 passing |
| [x] | Redis/Celery integration | Verify broker, worker, state, queue visibility, and progress end to end | `tests/test_celery_dispatcher.py`, `web/tests/`, operational smoke |
| [x] | Browser verification | Verify all currently implemented desktop and mobile workflows | `web/tests/` - 8 passing |
| [x] | Documentation | Explain setup, APIs, Redis, Celery, and demo operation | `README.md`, `web/README.md`, `docs/` |
| [ ] | Repository cleanup | Delete obsolete placeholders and compatibility code | Entire repository |
| [ ] | Demo packaging cleanup | Move standalone demo behavior out of the reusable AgentGate package if still appropriate | `src/agentgate/demo/`, `examples/` |
| [x] | Async slice regression | Run backend, frontend, and browser suites for the asynchronous vertical slice | Entire repository |
| [ ] | Delivery | Commit, push, and tag the completed refactor POC | Git repository |

## Deferred Production Capabilities

- PostgreSQL migration and high-availability Redis.
- Authentication, authorization, tenant isolation, quotas, and audit integration.
- Dependency-based evaluator short-circuiting with explicit blocked/skipped Results and
  `blocked_by_evaluator_id` provenance.
- Priority queues, tenant fairness, multiple worker pools, and resource-aware routing.
- Time-based reservations and recurring schedules.
- Cooperative cancellation of active local and remote Agent executions.
- Customer-specific Java scheduler and Agent-platform adapters.
- Production observability platform integrations and external Result callbacks.
- Automated resume or retry of partially completed Runs.
