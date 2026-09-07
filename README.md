# AgentGate

AgentGate is an open-source evaluation harness for enterprise agents.

It helps teams run agent test cases, collect traces, evaluate behavior, compare versions, and make release gate decisions.

## Goal

AgentGate focuses on:

- Active evaluation: run cases against an agent.
- Passive evaluation: score existing production traces.
- Business contracts: validate tool calls, arguments, policies, workflow rules, and final state.
- Release gates: decide whether an agent/model/prompt version is safe to ship.
- Dataset growth: turn failures and traces into regression cases.

## Initial Architecture

```text
CLI / Web / REST API
        |
    Control Layer
        |
Case -> Run -> Trace -> Evaluator -> Result
```

## Project Layout

```text
src/agentgate/
  case/          # Cases, datasets, custom/public benchmark import
  run/           # Run engine, targets, lifecycle
  trace/         # Trace model, OTel import, execution graph
  evaluator/     # Built-in and external evaluators
  result/        # Results, reports, compare, release gates
  experiment/    # Controlled A/B experiments and statistical decisions
  queue/         # Public reservation and queue orchestration
  optimizer/     # Badcase analysis and human-reviewed recommendations
  lineage/       # Asset versions and dependency lineage
  control_plane/ # Local control-plane service used by CLI/API/Web
  cli/           # Command-line entry point
  server/        # REST API entry point

web/             # Vue/TypeScript evaluation UI
docs/            # Design docs
examples/        # Demo agents and datasets
tests/           # Test suite
```

The five core evaluation objects remain `Case -> Run + Trace -> Evaluator -> Result`.
Experiment, queue, optimizer, and lineage are product modules composed around that core;
they do not replace it. See the [documentation index](docs/README.md) and individual
module design records for verified capability ownership and progress.

## First Demo Target

The first demo should be a loan approval agent:

- The agent may create a loan application.
- The agent must not approve high-risk loans directly.
- Approval may require human review.
- Evaluators check tool calls, tool arguments, workflow policy, and final state.

## P1 Demo

The repository contains a working SQLite-backed loan-approval evaluation slice with a
deterministic target, HTTP External Target support, CLI, REST/OTLP HTTP endpoints, and a
Chinese Vue UI. Current status is maintained in the relevant Trace, Run, Dataset, and
Evaluator documents. The original P1 walkthrough is retained under
[history](docs/history/p1-demo/demo-test-guide.md).

Published Dataset versions can be exported as JSON or Excel. Excel imports create a new
Dataset Draft and support single-turn and multi-turn Cases. See the
[Dataset documentation](docs/dataset/README.md) for the workbook contract and limits.

Dataset Drafts also support AI-assisted Case generation from an exact Agent or Skill version.
Candidates are reviewed before an atomic batch insert; generation never publishes or runs the
Dataset automatically. The initial implementation uses complete fake Target descriptors and an
optional Alibaba Bailian model profile. Its API key can be supplied from the generation dialog as
a process-memory-only override, or through the server-side `DASHSCOPE_API_KEY` environment variable.
