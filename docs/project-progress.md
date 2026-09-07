# AgentGate Project Progress

Last updated: 2026-09-06

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
| [ ] | Storage cleanup | Remove obsolete or empty storage code after migration | `src/agentgate/storage/` |

## Dataset

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Dataset management | Create, edit, archive, publish, and version Datasets | `src/agentgate/application/dataset_management.py` |
| [x] | Dataset loading | Convert external data into Dataset and Case models | `src/agentgate/dataset/loader.py` |
| [x] | JSON format | Import and export complete Dataset structures | `src/agentgate/dataset/formats/json.py` |
| [x] | Excel format | Import existing single-sheet customer files | `src/agentgate/dataset/formats/xlsx.py` |
| [x] | Multi-turn Cases | Store multiple conversation turns in one Case | `src/agentgate/domain/case.py` |
| [ ] | Dataset sampling | Select reproducible smoke, regression, tagged, or risk-based subsets | `src/agentgate/dataset/sampling.py` **new** |
| [ ] | Dataset generation | Generate positive, negative, and boundary Cases from Agent metadata | `src/agentgate/dataset/generation/` **new** |
| [ ] | Public benchmarks | Import selected public evaluation datasets | `src/agentgate/dataset/benchmarks/` **new** |

## Evaluator And Result

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Rule evaluation | Evaluate routing, Tool use, state, policy, and output | `src/agentgate/evaluator/rules/` |
| [x] | Metrics | Aggregate Case Results into Run metrics | `src/agentgate/result/metrics.py` |
| [x] | Release gate | Decide whether a version passes evaluation | `src/agentgate/result/gate.py` |
| [x] | Report | Build the complete evaluation report | `src/agentgate/result/report.py` |
| [ ] | Evaluator structure | Separate protocol, executor, rules, Judge, and Hybrid responsibilities | `src/agentgate/evaluator/` |
| [ ] | JSON evaluator | Validate JSON structure, required fields, and field values | `src/agentgate/evaluator/rule/json_structure.py` **new** |
| [ ] | LLM Judge | Perform semantic evaluation through configured models | `src/agentgate/evaluator/judge/` **new** |
| [ ] | Model providers | Support public and private model credentials | `src/agentgate/integrations/model_providers/` **new** |
| [ ] | Multimodal evaluation | Evaluate files, images, and other Artifacts | `src/agentgate/evaluator/judge/multimodal.py` **new** |
| [ ] | Result comparison | Compare two compatible EvaluationRuns | `src/agentgate/result/comparison.py` **new** |

## Trace And Target Execution

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Trace model | Represent normalized Agent behavior | `src/agentgate/domain/trace.py` |
| [x] | OTel capture | Capture real demo Agent spans | `src/agentgate/integrations/observability/in_memory.py` |
| [x] | OTLP receiver | Receive external OTLP JSON traces | `src/agentgate/integrations/observability/otlp_http_receiver.py` |
| [x] | Demo Agent adapter | Execute the Loan Agent | `src/agentgate/integrations/targets/demo_loan.py` |
| [x] | Target protocol | Standardize one Case execution | `src/agentgate/run/target_protocol.py` |
| [ ] | Trace redaction | Remove secrets and private data before evaluation or display | `src/agentgate/trace/redaction.py` **new** |
| [ ] | HTTP Agent adapter | Invoke Dify, Coze, or customer Agents | `src/agentgate/integrations/targets/http_agent.py` **new** |
| [ ] | Local process adapter | Execute CLI-based Agents | `src/agentgate/integrations/targets/process_agent.py` **new** |
| [ ] | Trace replay adapter | Evaluate an existing Trace without reinvoking an Agent | `src/agentgate/integrations/targets/trace_replay.py` **new** |
| [ ] | Trace cleanup | Remove obsolete Trace scaffolds after migration | `src/agentgate/trace/` |

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
| [x] | Celery dispatcher | Submit `run_id` through Redis | `src/agentgate/integrations/job_dispatchers/celery.py` **new** |
| [x] | Celery worker | Load and execute the persisted Run | `src/agentgate/integrations/job_dispatchers/celery.py` **new** |
| [ ] | Customer scheduler integration | Accept work from an external Java scheduler through the shared Run boundary | `src/agentgate/server/routes/runs.py` or `src/agentgate/integrations/job_dispatchers/`; design pending |
| [ ] | Retry mechanics | Retry classified infrastructure failures only | `src/agentgate/run/retry.py` **new** |
| [ ] | Local process management | Start, monitor, limit, and stop local Agent processes | `src/agentgate/run/process_manager.py` **new** |
| [ ] | Run Artifact collection | Register files and reports produced during execution | `src/agentgate/run/artifacts.py` **new** |
| [ ] | Run cleanup | Remove legacy core, scheduler, lifecycle, and model files | `src/agentgate/run/` |

## Application And Server

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Dataset application service | Coordinate Dataset workflows | `src/agentgate/application/dataset_management.py` |
| [x] | Run application service | Coordinate Run creation, dispatch, and execution | `src/agentgate/application/run_management.py` |
| [x] | Result reader foundation | Read persisted Runs, Results, Traces, and reports | `src/agentgate/application/result_reader.py` |
| [x] | FastAPI foundation | Expose current Dataset, Run, Result, and Trace APIs | `src/agentgate/server/` |
| [ ] | Target catalog | Read external Agent and Skill metadata | `src/agentgate/application/target_catalog.py` **new** |
| [ ] | Evaluator management | Create and manage Evaluator specifications | `src/agentgate/application/evaluator_management.py` **new** |
| [ ] | Skill analysis service | Coordinate static Skill analysis | `src/agentgate/application/skill_analysis.py` **new** |
| [ ] | Lineage queries | Find Runs by Dataset, Target, Evaluator, Prompt, or model version | `src/agentgate/application/lineage_queries.py` **new** |
| [x] | Asynchronous Run API | Create a Run, dispatch it, and return `202 Accepted` | `src/agentgate/server/routes/runs.py` |
| [x] | Run activity API | Expose queue, running status, progress, and history | `src/agentgate/server/routes/runs.py` |
| [ ] | API contract review | Finalize response models and sanitized error behavior | `src/agentgate/server/` |

## CLI

| Status | Capability | Function | Code location |
|---|---|---|---|
| [ ] | CLI refactor | Call the same application services used by FastAPI | `src/agentgate/cli/` |
| [ ] | Dataset commands | Import, export, list, publish, and inspect Datasets | `src/agentgate/cli/commands.py` |
| [ ] | Run commands | Submit Runs and inspect queue or execution status | `src/agentgate/cli/commands.py` |
| [ ] | Result commands | Retrieve reports, metrics, and failed Cases | `src/agentgate/cli/commands.py` |
| [ ] | Legacy cleanup | Remove CLI dependencies on the old Control Plane and Run core | `src/agentgate/cli/`, `src/agentgate/control_plane/` |
| [ ] | CLI tests | Verify commands through application boundaries | `tests/test_cli.py` |

CLI work is deferred until the FastAPI and worker workflows are stable.

## Web

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Dataset workspace foundation | Browse and edit Dataset content | `web/src/pages/DatasetWorkspace.vue` |
| [ ] | Web routing | Provide final Vue page navigation | `web/src/router/` |
| [ ] | Overview | Show Dataset and Run status statistics | `web/src/pages/OverviewPage.vue` **new** |
| [ ] | Run workspace | Configure Runs and show queued, running, and historical work | `web/src/pages/RunWorkspacePage.vue` **new** |
| [ ] | Progress polling | Refresh status while queued or running work exists | `web/src/api/runs.ts` **new** |
| [ ] | Result center | Browse completed and failed Runs | `web/src/pages/ResultCenterPage.vue` **new** |
| [ ] | Result detail | Show metrics, release gate, badcases, evidence, and Trace attribution | `web/src/pages/ResultDetailPage.vue` **new** |
| [ ] | Evaluator management | Configure Rule, Judge, and Hybrid Evaluators | `web/src/pages/EvaluatorWorkspacePage.vue` **new** |
| [ ] | Skill analysis | Display Skill conflicts and prompt mismatches | `web/src/pages/SkillAnalysisPage.vue` **new** |
| [ ] | Optimizer | Display failure clusters and suggestions | `web/src/pages/OptimizerPage.vue` **new** |
| [ ] | Browser verification | Verify desktop and mobile workflows | `web/tests/` |

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
| [ ] | Optimizer cleanup | Remove the rejected generic service wrapper | `src/agentgate/optimizer/service.py` |

Optimizer work is the final POC feature group and will receive a separate detailed
plan before implementation.

## Verification And Delivery

| Status | Capability | Function | Code location |
|---|---|---|---|
| [x] | Current backend regression | Verify current refactor behavior | `tests/` - 278 passing |
| [ ] | Redis/Celery integration | Verify broker, worker, state, and progress end to end | `tests/integration/` **new** |
| [ ] | Browser verification | Verify all primary desktop and mobile workflows | `web/tests/` |
| [ ] | Documentation | Explain setup, APIs, Redis, Celery, and demo operation | `README.md`, `docs/` |
| [ ] | Repository cleanup | Delete obsolete placeholders and compatibility code | Entire repository |
| [ ] | Demo packaging cleanup | Move standalone demo behavior out of the reusable AgentGate package if still appropriate | `src/agentgate/demo/`, `examples/` |
| [ ] | Final regression | Run backend, frontend, and browser suites | Entire repository |
| [ ] | Delivery | Commit, push, and tag the completed refactor POC | Git repository |

## Deferred Production Capabilities

- PostgreSQL migration and high-availability Redis.
- Authentication, authorization, tenant isolation, quotas, and audit integration.
- Priority queues, tenant fairness, multiple worker pools, and resource-aware routing.
- Time-based reservations and recurring schedules.
- Cooperative cancellation of active local and remote Agent executions.
- Customer-specific Java scheduler and Agent-platform adapters.
- Production observability platform integrations and external Result callbacks.
- Automated resume or retry of partially completed Runs.
