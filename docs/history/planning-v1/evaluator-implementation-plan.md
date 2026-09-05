# Evaluator Implementation Plan

> [!IMPORTANT]
> Pre-refactor design record. Behavior and acceptance criteria remain useful, but file
> paths and module ownership are superseded by
> [the architecture review ledger](../architecture-review-ledger.md).


## Goal

Extend the existing evaluator kernel with the highest-priority deterministic output
validation required by the product:

```text
Case expectation
  -> structural Rule evaluation
  -> JSON parsing when explicitly configured
  -> JSON Schema and field-value validation
  -> CheckResult with score, reason, expected value, actual value, and Trace evidence
  -> remaining Rule evaluators
  -> future LLM Judge and Hybrid evaluators
```

JSON validation belongs to `evaluator/`. Dataset and Case store reusable expectations,
but they do not implement comparison algorithms or execute schemas.

The first delivery increment adds JSON Schema and final-output Rule evaluation. It also
defines execution-order semantics that later LLM Judge and Hybrid implementations must
follow.

## Current State

Implemented:

- immutable evaluator specifications and Expectations under `domain/`;
- Rule, LLM Judge, and Hybrid product kinds;
- six deterministic Rule evaluators for routing, tool use, arguments, state, and policy;
- comparison and collection operators;
- evaluator registration, plan validation, dependency resolution, scoring, and error
  isolation;
- `MatchesJsonSchema` as a persisted Condition;
- extraction of final output through `OutputExpectation`;
- PASS, FAIL, REVIEW, NOT_APPLICABLE, and ERROR result semantics.

Missing:

- execution of `MatchesJsonSchema`;
- a final-output Rule evaluator;
- validation and compilation of configured JSON Schemas before a Run starts;
- explicit structural-validation execution phase;
- structured JSON validation error reporting;
- LLM Judge and Hybrid runtime execution.

The current pre-run validator intentionally rejects `MatchesJsonSchema`. This rejection
is removed only after the operator, output evaluator, and tests are complete.

## Ownership Boundaries

```text
domain/expectation.py
  Owns persisted expectation and condition data.
  Does not execute JSON Schema.

case/
  Owns Dataset/Case editing, import, export, and publish validation.
  Verifies that an expectation is structurally well formed.
  Does not judge Agent output.

evaluator/
  Owns evaluator execution, observation, operators, JSON Schema behavior,
  ordering, dependency handling, scoring input, and evaluator errors.

result/
  Owns aggregation, report metrics, and Gate decisions.
  Does not rerun an evaluator.

run/
  Owns complete Run orchestration and immutable evaluator snapshots.
  Does not contain JSON-specific validation logic.
```

An Excel or JSON Dataset importer may deserialize a `MatchesJsonSchema` Condition, but
the importer must not duplicate or approximate JSON Schema evaluation.

## Parallel Development Boundary

The Dataset/Case implementation may proceed in parallel when the work uses separate Git
branches and worktrees.

```text
Dataset/Case owner
  domain/case.py, case/, Dataset persistence, Dataset API, Dataset Web workspace

Evaluator owner
  domain/evaluation.py, evaluator/, JSON Schema operator, evaluator-focused tests

Shared contract requiring coordination
  domain/expectation.py
```

The Evaluator increment must not modify `domain/case.py`, `case/`, Dataset storage,
Dataset routes, or the Dataset Web workspace. If Dataset work also needs to change
`domain/expectation.py`, merge and verify one contract change before the second branch
edits it. Do not run both Codex sessions in the same worktree.

## Terms

### Evaluator

A configured judge that produces one `Result` for one Case. An evaluator has stable
identity, version, kind, dimension, metric, and severity.

### Rule Evaluator

A deterministic evaluator. The same Case, Trace, evaluator version, and operator version
must produce the same Result.

### Expectation

A Case-owned declaration of which target value should be inspected. Examples are final
output, final state, and tool arguments.

### Condition

Persisted data describing what an observed value must satisfy. `MatchesJsonSchema` is a
Condition.

### Operator

A reusable deterministic algorithm that compares an observed value with a Condition.
`matches_json_schema` is an operator, not an evaluator, metric, or Gate.

### JSON Schema

The schema used by `matches_json_schema` to validate one observed JSON instance. The
initial implementation supports JSON Schema Draft 2020-12 only.

### Structured Value

An already-parsed JSON-compatible value such as an object, array, string, number,
boolean, or null.

### JSON Text

A string whose contents encode a JSON value. JSON text is parsed only when the Condition
explicitly requests JSON-text mode.

### Execution Phase

The ordering category used by the evaluator runner:

```text
1. structural_rule   JSON structure and required field validation
2. rule              other deterministic Rule evaluators
3. llm_judge         future model-based evaluation
4. hybrid            future combination of completed child Results
```

Execution phase controls order only. It does not change score weight or Gate severity.

### Severity

Whether a failed Result can veto the release Gate. `blocking` affects the Gate; it does
not implicitly stop evaluator execution.

### Dependency

An explicit relationship where one evaluator requires another evaluator's Result.
Execution order alone is not a dependency.

### FAIL, ERROR, and NOT_APPLICABLE

- `FAIL`: the evaluator ran correctly and the Agent output violated a valid expectation.
- `ERROR`: the evaluator crashed, timed out, or returned malformed output.
- `NOT_APPLICABLE`: the evaluator has no relevant expectation for the Case, or a future
  explicitly declared prerequisite prevents it from judging the Case.

An invalid configured JSON Schema is a plan/configuration error before execution. It is
not an Agent FAIL and must not be converted into a Case Result.

## JSON Validation Design

### Supported Standard

- Support JSON Schema Draft 2020-12.
- Use the maintained `jsonschema` Python library rather than implementing schema
  semantics inside AgentGate.
- If `$schema` is absent, apply Draft 2020-12.
- Reject an explicitly declared unsupported draft during plan validation.
- Permit local `$defs` and local fragment references.
- Do not resolve HTTP, HTTPS, file, or other remote `$ref` resources.

### Condition Contract

Extend `MatchesJsonSchema` with an explicit instance mode:

```python
class MatchesJsonSchema(DomainModel):
    kind: Literal["matches_json_schema"] = "matches_json_schema"
    json_schema: FrozenJsonObject
    instance_mode: Literal["structured", "json_text"] = "structured"
```

Behavior:

| Mode | Actual value | Behavior |
| --- | --- | --- |
| `structured` | object/array/scalar/null | validate the value directly |
| `structured` | string | validate it as a JSON string; never parse implicitly |
| `json_text` | string containing JSON | parse once, then validate the parsed value |
| `json_text` | non-string | fail with an input-mode mismatch |
| either | missing value | fail as missing, distinct from JSON null |

Explicit modes prevent a quoted JSON string from silently changing meaning between
versions.

### Structure and Field-Value Validation

JSON Schema covers both requested behaviors:

```text
Structure
  type, required, properties, items, additionalProperties

Field value
  const, enum, minimum, maximum, minLength, maxLength, pattern

Composition
  allOf, anyOf, oneOf, not, if/then/else
```

Path-specific value checks can continue to use `Equals`, `OneOf`, `WithinRange`,
`WithinTolerance`, `MatchesPattern`, and `MustBeMissing`. Do not generate a separate
evaluator class for every JSON Schema keyword.

### Schema Validation and Caching

Before a Run starts:

1. Locate every `MatchesJsonSchema` Condition in the selected Dataset version.
2. Verify the declared draft.
3. Run the library's schema self-check.
4. Reject unsupported external references.
5. Canonicalize the schema and calculate its content hash.
6. Compile/cache a validator by draft plus content hash.

The RunSnapshot already embeds the Dataset and evaluator definitions. Historical Runs
therefore retain the exact schema used for their decisions.

The cache is an optimization only. Correctness must not depend on cache state.

### Validation Result

For valid output:

```text
outcome = pass
score = 1.0
reason = output matches JSON Schema
```

For invalid output:

```text
outcome = fail
score = 0.0
primary_failure_step = final_output
reason = bounded summary of validation violations
expected = configured schema
actual = observed or parsed instance
```

Sort violations deterministically by instance path, schema path, and message. Include at
most the first 20 violations and cap the public reason length. The complete Agent output
must not be copied into exception messages or logs.

JSON text parsing errors are normal measured failures when `instance_mode=json_text`.
Library crashes or internal programming errors are evaluator ERRORs.

## Final-Output Rule Evaluator

Add `FinalOutputEvaluator` with `evaluator_type="final_output"`.

```text
For each OutputExpectation:
  observe Trace.final_output at the configured path
  preserve the distinction between missing and null
  resolve the Condition's registered operator
  execute the operator
  create one CheckDraft

Combine CheckDrafts
  -> Result through the existing calculate_result() path
```

It supports all existing Conditions, not only `MatchesJsonSchema`. This avoids separate
output evaluators for equality, ranges, patterns, and schemas.

The default evaluator set receives one new specification:

```text
id: final-output
kind: rule
evaluator_type: final_output
execution_phase: structural_rule
dimension: answer
metric: final_output_validity
```

For the initial increment, all `OutputExpectation` checks run in the structural phase.
If later requirements need non-structural output scoring, execution phase must become an
explicit evaluator-spec setting rather than being inferred from names.

## Priority and Blocking Rules

“JSON Rule evaluator has highest priority” means:

1. structural Rule evaluators execute before other Rules;
2. all deterministic Rules execute before LLM Judge calls;
3. result order is deterministic and follows the validated execution plan;
4. a structural failure is available to downstream evaluators as a dependency result.

The first increment does **not** globally stop after a JSON failure. Continuing other
deterministic Rules provides useful diagnostics at low cost.

When LLM Judge runtime is added, skipping it requires an explicit prerequisite policy,
for example:

```text
LLM Judge depends on final-output
  prerequisite PASS/REVIEW -> execute Judge
  prerequisite FAIL       -> not_applicable with dependency reason
  prerequisite ERROR      -> not_applicable; Gate still fails closed on the ERROR
```

Do not use `severity=blocking` as an implicit dependency or short-circuit flag.

## Security and Resource Rules

- No remote `$ref` retrieval or network access during schema evaluation.
- Reject schemas over a configured serialized-size limit.
- Apply bounded nesting/depth checks before accepting untrusted schemas.
- Bound the number and length of reported violations.
- Never evaluate executable Python, expressions, templates, or custom callbacks from a
  Dataset.
- Do not log credentials, complete private outputs, or unbounded schemas.
- Evaluator timeout remains part of the snapshotted execution configuration when
  asynchronous or LLM evaluators are introduced.
- Public and private model Key handling belongs to a credential/provider boundary, not
  the JSON Schema operator.

## Rules to Avoid Design Drift

1. Do not implement JSON Schema checks in `case/`, an importer, FastAPI routes, Vue, or
   the Run engine.
2. Do not hand-write a partial JSON Schema implementation.
3. Do not implicitly parse every string as JSON.
4. Do not allow remote references, filesystem references, or custom resolver callbacks.
5. Do not treat an invalid configured schema as an Agent failure.
6. Do not convert evaluator ERROR into FAIL or assign it an Agent failure stage.
7. Do not confuse execution phase, dependency, severity, metric weight, and Gate
   threshold; they are separate concepts.
8. Do not depend on caller tuple order as the long-term execution contract.
9. Do not mutate a published Dataset expectation or a RunSnapshot during evaluation.
10. Do not add JSON-specific fields to `Run`, `Trace`, or `Dataset` when the concept is
    owned by an Expectation or evaluator specification.
11. Do not expose raw validation-library exceptions directly through the API.
12. Do not start LLM Judge, Hybrid, credential, or multimodal work in this increment.

## Code Change Map

Status labels:

- `[ADD]`: create a new file.
- `[MOD]`: modify an existing file.
- `[DEL]`: remove a file.
- `[KEEP]`: behavior is reused without modification.

```text
agentgate-goal/
├── pyproject.toml                                      [MOD] Add jsonschema runtime dependency
│
├── src/agentgate/
│   ├── domain/
│   │   ├── expectation.py                             [MOD] Add explicit JSON instance mode
│   │   └── evaluation.py                              [MOD] Add persisted execution phase
│   │
│   ├── evaluator/
│   │   ├── __init__.py                                [MOD] Register default final-output spec
│   │   ├── execution.py                               [ADD] Build deterministic phase-ordered plan
│   │   ├── validation.py                              [MOD] Validate/compile schemas; remove deferral
│   │   ├── observations.py                            [KEEP] Reuse final-output extraction and MISSING
│   │   ├── runner.py                                  [MOD] Execute validated phase order
│   │   ├── calc_score.py                              [KEEP] Reuse Result calculation
│   │   ├── operators/
│   │   │   ├── __init__.py                            [MOD] Register matches_json_schema v1
│   │   │   └── json_schema.py                         [ADD] Draft 2020-12 validation operator
│   │   └── rules/
│   │       ├── __init__.py                            [MOD] Register FinalOutputEvaluator
│   │       └── output.py                              [ADD] Evaluate OutputExpectations
│   │
│   ├── case/                                          [KEEP] No validation algorithm here
│   ├── run/                                           [KEEP] Existing orchestration calls evaluator
│   ├── result/                                        [KEEP] Existing metrics and Gate consume Results
│   └── storage/                                       [KEEP] Domain JSON persists through current adapter
│
├── tests/
│   ├── test_json_schema_operator.py                   [ADD] Schema/operator truth table and limits
│   ├── test_output_evaluator.py                       [ADD] Output checks and failure evidence
│   ├── test_evaluator_execution.py                    [ADD] Phase ordering and determinism
│   ├── test_evaluator_validation.py                   [MOD] Valid/invalid schema plan validation
│   ├── test_domain_models.py                          [MOD] Instance mode and phase serialization
│   ├── test_demo_engine.py                            [MOD] Default evaluator count and compatibility
│   └── test_imports.py                                [MOD] Public module import checks
│
└── docs/
    ├── evaluator/README.md                            [MOD] Link this implementation plan
    ├── evaluator/implementation-plan.md               [ADD] This document
    ├── progress.md                                    [MOD] Update only after verification passes
    └── capability-mapping.md                          [MOD] Update status only after acceptance
```

No file is deleted in this increment.

## Delivery Checkpoints

### 1. Operator

- Add the dependency and `matches_json_schema` operator.
- Validate Draft 2020-12 schemas.
- Support structured and explicit JSON-text modes.
- Disable external reference retrieval.
- Add focused operator tests.

### 2. Output Evaluator

- Add `FinalOutputEvaluator`.
- Support every existing output Condition.
- Produce expected/actual values and final-output failure evidence.
- Register it in the default evaluator set.

### 3. Execution Plan

- Add explicit persisted execution phase.
- Validate and order evaluator specs deterministically.
- Keep severity and Gate semantics unchanged.
- Demonstrate structural Rules execute before other Rules.

### 4. Regression Verification

- Existing risky/fixed loan outcomes remain unchanged.
- Existing Rule evaluator tests remain green.
- API and CLI continue to serialize Results.
- RunSnapshot hash changes when schema, mode, operator version, or execution phase changes.

## Acceptance Tests

At minimum, automated tests cover:

1. valid nested object passes;
2. missing required field fails;
3. incorrect field type fails;
4. enum or const mismatch fails;
5. numeric range violation fails;
6. unexpected property fails when `additionalProperties=false`;
7. array item failure reports its instance path;
8. local `$defs` reference works;
9. remote `$ref` is rejected before Run execution;
10. invalid schema is rejected before Run execution;
11. structured mode does not parse a JSON-looking string;
12. JSON-text mode parses valid text;
13. malformed JSON text is a measured FAIL;
14. missing output differs from explicit JSON null;
15. violations are sorted and bounded deterministically;
16. structural output evaluator runs before other Rules;
17. evaluator library failure becomes ERROR, not FAIL;
18. schema content is preserved in RunSnapshot and affects its hash.

End-to-end acceptance:

```text
Create or load a Case with OutputExpectation(MatchesJsonSchema)
  -> validate evaluation plan
  -> execute Demo Agent
  -> evaluate final output
  -> persist Result
  -> display score, reason, expected schema, actual output, and failure stage
```

## Deferred Work

- LLM Judge provider execution and public/private Key management;
- Hybrid combination semantics and execution;
- file and multimodal artifact evaluation;
- evaluator CRUD and independent evaluator-version UI;
- user-authored custom code evaluators;
- distributed evaluator workers;
- automatic Dataset generation;
- Dataset Excel mapping.

These capabilities may reuse the evaluator execution plan, but they must receive separate
design and acceptance plans.
