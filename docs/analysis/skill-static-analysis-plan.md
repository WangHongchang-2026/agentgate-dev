# Skill Static Analysis Plan

## Goal

Detect ambiguous or conflicting Skill definitions and Agent Prompt mismatches before or
during evaluation, without executing the Agent.

```text
External Agent Platform
        |
        v
TargetCatalogAdapter
        |
        v
Agent TargetDescriptor
  - Agent Prompt
  - Skill descriptions
  - Skill Prompts
  - tools and I/O schemas
        |
        v
Static Skill Analysis
  - description quality
  - pairwise conflict
  - pairwise confusion
  - Prompt-to-Skill alignment
  - coverage and fallback checks
        |
        v
AnalysisReport
  - findings
  - evidence
  - confidence
  - severity
  - suggested changes
        |
        +--> external platform creation workflow
        +--> AgentGate evaluation workflow
        +--> later optimizer correlation
```

The capability is “static” because it analyzes definitions rather than running test
Cases. It may use deterministic algorithms and an optional LLM semantic analyzer.

## Product Use Cases

### Agent Creation or Update

The external platform calls AgentGate after a user configures Agent Prompt and Skills:

```text
create/update Agent draft
  -> send or reference TargetDescriptor
  -> run static analysis
  -> show warnings before publish
  -> user accepts, edits, or records an override
```

AgentGate returns findings only. The external platform owns the draft and publish action.

### Evaluation Preparation

```text
select Agent version for evaluation
  -> resolve exact TargetDescriptor
  -> run or reuse static analysis
  -> attach AnalysisReport reference to Run context
  -> continue evaluation
```

Static findings do not automatically block evaluation unless a separately configured
policy explicitly treats a severity as blocking.

### Result Investigation

Later, the optimizer can compare:

```text
static pairwise confusion risk
          +
dynamic routing confusion matrix from real Cases
          |
          v
stronger root-cause hypothesis
```

Static risk is not actual observed routing failure.

## Current State and Gap

Available foundations:

- external target plan defines Agent/Skill TargetDescriptor;
- TargetDescriptor can contain Agent Prompt, Skill descriptions, Skill Prompts, tools,
  and I/O schemas;
- immutable domain models, canonical JSON, and content hashing exist;
- LLM Judge contracts and future credential boundary are identified;
- optimizer module boundary exists.

Missing:

- no `analysis/` source module;
- no persisted analysis specification or report;
- no normalized definition of conflict, confusion, or Prompt mismatch;
- no deterministic description checks;
- no pairwise semantic analysis;
- no API for creation-time invocation;
- no evaluation-time integration;
- no static risk matrix;
- no UI for findings, evidence, and overrides;
- no link between static findings and later dynamic Badcases.

## Scope

The complete POC capability includes:

1. normalized static-analysis input from TargetDescriptor;
2. deterministic description-quality checks;
3. deterministic pairwise overlap checks;
4. LLM-assisted semantic conflict/confusion analysis;
5. Agent Prompt-to-Skill alignment analysis;
6. fallback and capability-coverage findings;
7. finding confidence, severity, evidence, and suggestions;
8. versioned analyzer configuration and reproducibility;
9. API for creation-time and evaluation-time invocation;
10. persisted reports and reuse by descriptor hash;
11. Chinese Web visualization and review state;
12. integration boundary for optimizer correlation.

## Non-Goals

- executing the Agent or routing real user requests;
- producing the dynamic routing confusion matrix;
- creating or editing external Agent/Skill assets;
- automatically applying Prompt or description changes;
- replacing Dataset-based routing evaluation;
- proving that a finding caused an observed failure;
- training an embedding model;
- unrestricted custom-code analyzers;
- production organization approval workflow.

## Terms

### Static Analysis

Analysis of Agent/Skill definitions without executing the Agent.

### Skill Description Quality

Whether a description is present, specific, internally coherent, and sufficiently
distinct to guide routing.

### Skill Conflict

Two or more Skills contain contradictory instructions, incompatible ownership, or
overlapping actions where choosing both or either may violate intended behavior.

Example:

```text
Skill A: approve all high-value loans automatically
Skill B: send all high-value loans to human review
```

### Skill Confusion

Two or more Skills describe substantially overlapping intents or trigger conditions, so
the router may not have enough information to select one reliably.

Example:

```text
Skill A: query available loan amount
Skill B: query current approved credit limit
```

Confusion is ambiguity; conflict is contradiction or incompatible action. One pair can
have both findings, but they are not synonyms.

### Prompt-to-Skill Mismatch

The Agent system Prompt's routing instructions, names, constraints, or capabilities do
not agree with the supplied Skill definitions.

Examples:

- Prompt references a Skill that does not exist.
- Skill exists but the Prompt never permits or describes routing to it.
- Prompt says one Skill owns an intent while another Skill description claims it.
- Prompt fallback instruction contradicts Skill trigger rules.

### Coverage Gap

The Agent Prompt claims a capability or intent domain for which no Skill is available, or
the set of Skills has no fallback/clarification behavior for uncovered requests.

### Finding

One reviewable analysis output with type, involved assets, severity, confidence, evidence,
reason, and suggestion.

### Severity

Potential product impact:

```text
info
warning
high
blocking
```

Severity does not represent certainty.

### Confidence

How strongly the analyzer supports the finding, normalized to `0..1`. Confidence is not a
quality score for the Agent.

### Static Risk Matrix

An N-by-N matrix of pairwise confusion/conflict risk between Skills. It is predictive
analysis of definitions, not the observed confusion matrix calculated from evaluation
Cases.

### Override

A human decision to accept, dismiss, or defer a finding with a reason. It does not delete
the original finding.

## Ownership Boundaries

```text
run/targets/
  resolves external TargetDescriptor

analysis/
  owns static analyzers, findings, report, scoring, and suggestions

domain/analysis.py
  owns persisted analysis specifications and outputs

evaluator/
  owns Case/Trace-based Agent evaluation, not static definition analysis

optimizer/
  consumes static reports plus dynamic Results later

control_plane/
  exposes application workflow

server/
  exposes HTTP API

web/
  presents findings and review actions

external platform
  owns Agent/Skill edits and publish decisions
```

Static analysis must not be implemented as a fake Evaluator Result because it has no Case
or Trace.

## Input Contract

The service accepts:

```text
TargetDescriptor
├── exact Agent TargetRef
├── display name and description
├── Agent Prompt or Prompt reference/hash
├── SkillDescriptor[]
│   ├── exact Skill/version identity
│   ├── name
│   ├── description
│   ├── Skill Prompt or reference/hash
│   ├── tools
│   └── I/O schemas
└── descriptor content hash
```

Required for a full analysis:

- at least two Skills for pairwise analysis;
- non-empty Skill identity and name;
- Skill description;
- Agent Prompt for Prompt-alignment checks.

Missing optional content produces an explicit `insufficient_input` finding or skipped
check. The analyzer must not invent unavailable Prompt or description content.

## Domain Model

Add `src/agentgate/domain/analysis.py`.

### AnalysisKind

```python
class AnalysisKind(StrEnum):
    DESCRIPTION_QUALITY = "description_quality"
    SKILL_CONFLICT = "skill_conflict"
    SKILL_CONFUSION = "skill_confusion"
    PROMPT_ALIGNMENT = "prompt_alignment"
    COVERAGE_GAP = "coverage_gap"
    FALLBACK_GAP = "fallback_gap"
    INSUFFICIENT_INPUT = "insufficient_input"
```

### AnalysisMethod

```text
deterministic_rule
lexical_similarity
semantic_model
llm_analysis
```

Each method records implementation name and version.

### AnalysisSpec

```python
class AnalysisSpec(DomainModel):
    id: str
    version: str
    enabled_kinds: tuple[AnalysisKind, ...]
    deterministic_config: FrozenJsonObject
    semantic_config: FrozenJsonObject
    llm_config_ref: str | None
    severity_policy: FrozenJsonObject
    content_sha256: str
```

The complete spec is snapshotted into AnalysisRun. A version string alone is insufficient
for reproducibility.

### SkillPairRef

```python
class SkillPairRef(DomainModel):
    left_skill_id: str
    left_version_id: str
    right_skill_id: str
    right_version_id: str
```

Pair ordering is canonicalized by stable external identity so the same pair cannot appear
twice in reversed order.

### AnalysisEvidence

```python
class AnalysisEvidence(DomainModel):
    source_type: Literal[
        "agent_prompt", "skill_description", "skill_prompt",
        "tool_schema", "input_schema", "output_schema"
    ]
    source_id: str
    content_sha256: str
    excerpt: str | None
    location: str | None
```

Excerpts are bounded and redacted. Full external Prompt content is not copied into every
finding.

### AnalysisFinding

```python
class AnalysisFinding(DomainModel):
    id: str
    kind: AnalysisKind
    severity: AnalysisSeverity
    confidence: float
    title: str
    reason: str
    skill_ids: tuple[str, ...]
    pair: SkillPairRef | None
    evidence: tuple[AnalysisEvidence, ...]
    methods: tuple[MethodRef, ...]
    suggestions: tuple[str, ...]
```

### FindingReview

```python
class FindingReview(DomainModel):
    finding_id: str
    status: Literal["unreviewed", "accepted", "dismissed", "deferred"]
    reason: str | None
    reviewer_id: str | None
    reviewed_at: datetime | None
```

Reviews are separate from immutable findings.

### SkillRiskCell

```python
class SkillRiskCell(DomainModel):
    pair: SkillPairRef
    confusion_risk: float
    conflict_risk: float
    finding_ids: tuple[str, ...]
```

### AnalysisReport

```python
class AnalysisReport(DomainModel):
    id: str
    target_ref: TargetRef
    target_descriptor_sha256: str
    analysis_spec: AnalysisSpec
    status: Literal["completed", "partial", "error"]
    findings: tuple[AnalysisFinding, ...]
    risk_matrix: tuple[SkillRiskCell, ...]
    reviews: tuple[FindingReview, ...]
    created_at: datetime
    content_sha256: str
```

An analyzer technical failure does not erase successful independent findings. Report
status becomes `partial` when optional analyzers fail or input is insufficient.

## Analysis Pipeline

```text
validate TargetDescriptor
        |
        v
normalize definitions
        |
        +--> deterministic quality rules
        |
        +--> pairwise lexical/structural analysis
        |
        +--> semantic/LLM pair analysis
        |
        +--> Prompt alignment and coverage
        |
        v
deduplicate and merge findings
        |
        v
calculate static risk matrix
        |
        v
persist immutable AnalysisReport
```

## Deterministic Checks

### Description Quality

Check:

- missing or whitespace-only description;
- description identical to Skill name;
- duplicate normalized descriptions;
- descriptions below configurable information length;
- generic trigger language with no differentiating conditions;
- missing action/result statement;
- contradictory positive/negative trigger statements inside one description;
- Prompt/tool names referenced but not defined;
- identical tool and input-schema ownership across multiple Skills.

Text thresholds are snapshotted configuration, not hidden constants.

### Normalization

For deterministic comparison:

- Unicode normalization;
- case normalization where relevant;
- punctuation/whitespace normalization;
- configurable stop-word handling;
- Chinese character n-grams and token-aware comparison when available;
- stable sorted keyword and tool sets.

Do not use English whitespace tokenization as the only Chinese similarity method.

### Pairwise Risk

Deterministic features may include:

```text
description n-gram similarity
trigger keyword overlap
exclusive-condition overlap
tool-set overlap
input-schema overlap
output/action contradiction
Prompt ownership overlap
```

Feature values and thresholds appear in evidence. A weighted aggregate creates candidate
risk, but the individual features remain visible.

## LLM-Assisted Semantic Analysis

The complete POC supports optional LLM semantic analysis because lexical overlap alone
cannot reliably identify business meaning.

Input:

- bounded Agent Prompt;
- two Skill descriptions and relevant Skill Prompt excerpts;
- tool and schema summaries;
- deterministic feature summary.

Structured output:

```json
{
  "confusion_risk": 0.0,
  "conflict_risk": 0.0,
  "reasons": [],
  "evidence_refs": [],
  "suggestions": []
}
```

Rules:

- use a versioned Prompt and rubric snapshot;
- require structured schema validation;
- record requested/resolved model, request ID, latency, and Prompt/rubric hashes;
- public/private Key resolution uses the credential boundary;
- malformed output is analyzer ERROR, not a Skill conflict;
- LLM output is a hypothesis requiring evidence and review;
- deterministic findings remain available when the LLM is unavailable.

## Prompt-to-Skill Alignment

Checks include:

- Prompt references unknown Skill name or ID;
- Prompt omits a configured Skill from routing instructions;
- Prompt assigns the same intent to multiple Skills without disambiguation;
- Prompt claims an unsupported capability;
- Prompt forbids an action required by a Skill;
- Skill description contradicts global fallback/clarification policy;
- Agent Prompt and Skill Prompt disagree on input requirements;
- tool ownership in Prompt differs from Skill metadata.

The report identifies the exact Prompt/description hashes used.

## Finding Merge Rules

Multiple analyzers may identify the same issue.

Merge key:

```text
analysis kind
canonical involved Skill identities
normalized evidence locations
```

Merge behavior:

- keep all methods and non-duplicate evidence;
- choose highest severity;
- combine confidence using a documented versioned method;
- retain distinct reasons when they identify different mechanisms;
- bound suggestion count and text length;
- deterministic ordering by severity, kind, Skill identity, and finding ID.

Do not average away a blocking deterministic contradiction because an LLM returns low
confidence.

## API

Creation-time direct analysis:

```text
POST /api/skill-analysis
GET  /api/skill-analysis/{report_id}
POST /api/skill-analysis/{report_id}/findings/{finding_id}/review
```

Request supports either:

```text
exact TargetRef
or
inline TargetDescriptor for an unpublished external draft
```

Inline draft descriptors are validated and hashed but do not become AgentGate-owned
Agent assets.

Evaluation-time:

```text
POST /api/runs
  static_analysis:
    mode: reuse_or_run
    analysis_spec_id: default
```

AgentGate reuses a report only when TargetDescriptor hash and AnalysisSpec content hash
match exactly.

## Web UI

Provide a Chinese static-analysis workspace:

```text
Header
  Agent/version, descriptor hash, analysis status, rerun

Summary
  conflict count, confusion count, high-risk count, coverage gaps

Risk matrix
  Skill x Skill static confusion/conflict risk

Finding list
  severity, type, involved Skills, confidence, review status

Finding detail
  reason, evidence, methods, suggestions, review action
```

The UI must label the matrix as static risk, not observed confusion.

Creation-time integration can use the same API in an embedded page or render the response
inside the external platform. AgentGate does not require ownership of the external
creation page.

## Persistence and Reuse

```text
analysis_reports
  id, platform_id, target_type, target_id, version_id,
  descriptor_sha256, spec_sha256, status, created_at, payload

analysis_reviews
  report_id, finding_id, status, reason, reviewer_id, reviewed_at
```

Unique reusable report key:

```text
(target_descriptor_sha256, analysis_spec_sha256)
```

Reports are immutable. Reviews are mutable audit records. A new descriptor or spec hash
creates a new report.

## Error Semantics

| Condition | Handling |
| --- | --- |
| unknown TargetRef | request/configuration error |
| missing required Skill identity | request/configuration error |
| one Skill only | pairwise checks not applicable; other checks continue |
| Prompt unavailable | partial report + insufficient-input finding |
| deterministic analyzer crash | analyzer error; report partial/error |
| LLM timeout/unavailable | report partial; deterministic results retained |
| malformed LLM output | analyzer error, never a Skill finding |
| credential unavailable | LLM analyzer error; deterministic results retained |
| descriptor changes during analysis | reject stale result and rerun exact snapshot |

Static findings are not evaluator FAILs and do not receive Trace failure stages.

## Security and Resource Limits

- treat Prompt, descriptions, tools, and schemas as potentially sensitive;
- persist hashes and bounded evidence excerpts rather than duplicating complete content;
- resolve credentials by opaque reference;
- redact secrets before deterministic or LLM analysis;
- configure maximum Skills per report and pair count;
- bound Prompt/description/schema bytes;
- cap LLM request size, timeout, retry, concurrency, and output length;
- do not follow URLs or execute code found in descriptions;
- do not expose another tenant's descriptor/report;
- record analyzer/model versions for audit;
- allow external platforms to disable Prompt persistence.

For N Skills, pairwise analysis is O(N²). The plan must set a POC limit and show a clear
error or sampled strategy above it; it must not start an unbounded number of LLM calls.

## Rules to Avoid Design Drift

1. Static analysis does not execute the Agent.
2. Do not implement it as a Case evaluator or fake Result.
3. Do not call static risk an observed confusion matrix.
4. Do not treat lexical similarity alone as semantic conflict.
5. Do not treat LLM output as proven root cause.
6. Do not automatically modify external Agent Prompt or Skill descriptions.
7. Do not fetch external metadata independently from each analyzer.
8. Do not identify Skills by display name alone.
9. Do not merge findings without preserving methods and evidence.
10. Do not conflate confidence with severity.
11. Do not make static findings block evaluation implicitly.
12. Do not hide missing Prompt/description data by inventing content.
13. Do not expose complete sensitive Prompt content in findings or logs.
14. Do not run unbounded pairwise LLM analysis.
15. Do not place analysis algorithms in FastAPI routes or Vue.

## Parallel Development Boundary

```text
Static analysis owner
  domain/analysis.py
  analysis/
  analysis persistence
  analysis-focused API and tests

Target owner
  domain/target.py
  TargetDescriptor and catalog adapter

Evaluator/credential owner
  LLM provider and CredentialRef contracts

Optimizer owner
  dynamic Badcases and observed confusion matrix

Shared integration
  storage/base.py
  storage/sqlite.py
  control_plane/
  server/
  web navigation
```

The static-analysis branch can implement pure analyzers against fixture
TargetDescriptors. Shared persistence/API/UI integration follows target and storage
contract merges.

## Code Change Map

Status labels:

- `[ADD]` create;
- `[MOD]` modify;
- `[DEL]` delete;
- `[KEEP]` reuse;
- `[DEFER]` post-POC.

```text
agentgate-goal/
├── src/agentgate/
│   ├── domain/
│   │   ├── __init__.py                         [MOD] Export analysis contracts
│   │   └── analysis.py                         [ADD] Specs, findings, reports, reviews, matrix
│   │
│   ├── analysis/
│   │   ├── __init__.py                         [ADD] Public analysis API
│   │   ├── base.py                             [ADD] Analyzer Protocol
│   │   ├── models.py                           [ADD] Runtime candidates/features/errors
│   │   ├── registry.py                         [ADD] Analyzer registration/version resolution
│   │   ├── normalization.py                    [ADD] Unicode/text/schema normalization
│   │   ├── description_quality.py              [ADD] Deterministic quality checks
│   │   ├── pairwise.py                         [ADD] Lexical/structural pair features
│   │   ├── prompt_alignment.py                 [ADD] Prompt/Skill/coverage checks
│   │   ├── llm_semantic.py                     [ADD] Structured semantic analyzer
│   │   ├── merge.py                            [ADD] Finding dedupe/merge/order
│   │   ├── matrix.py                           [ADD] Static risk matrix
│   │   └── service.py                          [ADD] End-to-end analysis workflow
│   │
│   ├── storage/
│   │   ├── base.py                             [MOD] Analysis report/review repository
│   │   └── sqlite.py                           [MOD] Analysis tables and reuse lookup
│   │
│   ├── control_plane/
│   │   └── service.py                          [MOD] Analysis application workflow
│   │
│   ├── server/
│   │   └── application.py                      [MOD] Analysis and review APIs
│   │
│   ├── run/
│   │   └── targets/                            [KEEP] Supplies TargetDescriptor
│   │
│   ├── evaluator/                              [KEEP] No static-analysis execution
│   └── optimizer/                              [KEEP] Later consumes reports
│
├── web/src/
│   ├── pages/SkillAnalysisWorkspace.vue        [ADD] Chinese analysis workspace
│   ├── components/analysis/
│   │   ├── AnalysisSummary.vue                 [ADD]
│   │   ├── SkillRiskMatrix.vue                 [ADD]
│   │   ├── FindingTable.vue                    [ADD]
│   │   └── FindingDetail.vue                   [ADD]
│   ├── api/analysis.ts                         [ADD]
│   ├── types/analysis.ts                       [ADD]
│   └── App.vue                                 [MOD] Navigation after workspace integration
│
├── tests/
│   ├── test_analysis_models.py                 [ADD]
│   ├── test_analysis_normalization.py          [ADD]
│   ├── test_description_quality.py             [ADD]
│   ├── test_pairwise_analysis.py               [ADD]
│   ├── test_prompt_alignment.py                [ADD]
│   ├── test_llm_semantic_analysis.py           [ADD]
│   ├── test_analysis_merge.py                  [ADD]
│   ├── test_analysis_matrix.py                 [ADD]
│   ├── test_analysis_service.py                [ADD]
│   ├── test_analysis_repository.py             [ADD]
│   ├── test_analysis_api.py                    [ADD]
│   └── web/tests/skill-analysis.spec.ts        [ADD]
│
└── docs/
    ├── analysis/README.md                      [ADD]
    ├── analysis/skill-static-analysis-plan.md  [ADD] This document
    ├── progress.md                             [MOD] Only after verification
    └── capability-mapping.md                   [MOD] Only after acceptance
```

No existing source file is deleted.

## Delivery Checkpoints

### 1. Domain and Deterministic Quality

- analysis models, identity, immutability, and hashing;
- description quality and missing-input checks;
- deterministic tests using Chinese and English fixtures.

### 2. Pairwise Static Risk

- canonical Skill pairs;
- lexical/tool/schema feature extraction;
- confusion/conflict candidates;
- static risk matrix and deterministic ordering.

### 3. Prompt Alignment

- unknown/omitted Skill references;
- intent ownership conflicts;
- fallback and coverage gaps;
- evidence and suggestions.

### 4. LLM Semantic Analyzer

- versioned Prompt/rubric and structured output;
- credential/provider boundary;
- limits, timeout, error isolation, and audit evidence;
- deterministic results retained on LLM failure.

### 5. Persistence, API, and Invocation

- immutable report reuse by descriptor/spec hash;
- creation-time TargetRef or inline-draft API;
- evaluation-time reuse/run integration;
- finding review audit.

### 6. Web Experience

- summary, static risk matrix, findings, detail, and review;
- explicit static-versus-observed labels;
- real API and persistence browser acceptance.

## Acceptance Tests

At minimum:

1. empty Skill description produces a quality finding.
2. identical descriptions produce a pairwise confusion finding.
3. clearly distinct Skills do not produce high confusion risk.
4. contradictory high-value-loan instructions produce a conflict finding.
5. unknown Skill referenced by Agent Prompt produces alignment finding.
6. configured Skill omitted from Prompt produces alignment finding.
7. unsupported Prompt capability produces coverage-gap finding.
8. absent fallback/clarification behavior produces fallback-gap finding.
9. one-Skill Agent skips pairwise checks but runs other analysis.
10. missing Prompt produces partial report, not invented content.
11. Chinese similarity does not rely only on whitespace tokenization.
12. canonical Skill pair does not duplicate reversed order.
13. findings preserve analyzer methods and evidence hashes.
14. confidence and severity remain separate.
15. duplicate findings merge deterministically.
16. risk-matrix ordering and values are reproducible.
17. LLM structured output is schema validated.
18. malformed LLM output becomes analyzer error, not a finding.
19. LLM timeout retains deterministic findings in a partial report.
20. public/private credential values never enter reports or logs.
21. same descriptor/spec hashes reuse an immutable report.
22. changed Skill description creates a new report.
23. review changes do not mutate original finding content.
24. creation-time API accepts an inline unpublished descriptor.
25. evaluation-time integration resolves the exact TargetDescriptor.
26. static findings do not implicitly become evaluator FAIL.
27. static matrix is visibly labelled differently from observed confusion.
28. O(N²) limit prevents unbounded pairwise model calls.
29. external Agent/Skill assets are never modified.
30. Web browser scenario uses real API, persists review, and reloads correctly.

End-to-end acceptance:

```text
submit Agent draft with two overlapping Skill descriptions
  -> run deterministic and LLM-assisted static analysis
  -> show pairwise confusion risk and Prompt mismatch
  -> user dismisses one finding with reason
  -> update one Skill description externally
  -> submit new descriptor hash
  -> receive a new report with reduced risk
  -> select same Agent version for evaluation
  -> AgentGate links or reuses the matching static report
```

## Post-POC Extensions

- automatic patch generation and application;
- organization-specific analyzer policy packs;
- calibrated embedding models;
- historical trend across external Agent versions;
- cross-Agent Skill conflict analysis;
- graph-based capability coverage;
- multilingual semantic calibration;
- optimizer causality ranking using static plus dynamic evidence.
