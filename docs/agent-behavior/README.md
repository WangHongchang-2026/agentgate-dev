# Agent Behavior Catalog

What an Agent must get right, and which Evaluator kind can prove it. This catalog is
domain-neutral: the behaviors below apply to any Agent under evaluation. Worked examples
using real business rules live in [finance.md](finance.md).

This document is an input to Dataset design and to `domain/expectation.py`. Where a
behavior cannot be expressed today, that is recorded rather than omitted.

## Why this exists

Most evaluation effort goes into checking the final answer. For an Agent the answer is
rarely the interesting part — the *trajectory* is. An Agent can produce the correct
outcome through a path that is unsafe, unauditable, or ruinously expensive, and a final-
answer check will call it a pass.

The behaviors below are the ones that decide whether an Agent is fit for production.

## The twelve behaviors

### Structural — provable by Rule Evaluators

| # | Behavior | Question it answers |
| --- | --- | --- |
| 1 | **Routing** | Did the right Skill handle the request? |
| 2 | **Required action** | Was the mandatory step actually performed? |
| 3 | **Forbidden action** | Did it refrain from the action it must not take? |
| 4 | **Argument correctness** | Right Tool, right values — the amount, the account, the flag |
| 5 | **End state** | Is the resulting business state correct? |
| 6 | **Cross-turn memory** | Did it carry context from earlier turns instead of re-asking? |
| 7 | **Asking vs guessing** | With information missing, did it request it rather than invent it? |

### Judgment — the expensive failures

| # | Behavior | Question it answers |
| --- | --- | --- |
| 8 | **Escalation judgment** | Does it escalate the cases that need it — and only those? |
| 9 | **Failure direction** | On a tool error or timeout, does it stop or proceed? |
| 10 | **Holding position** | Under user pressure, does it keep refusing what it must refuse? |
| 11 | **Grounding** | Does every stated fact come from a Tool result? |
| 12 | **Consistency** | Same input, same decision, run after run? |

**Behavior 8 deserves separate attention.** An Agent that escalates everything passes
every safety check and is worthless. An Agent that escalates nothing is dangerous. Both
extremes are invisible to a Dataset containing only the dangerous direction.

**Behavior 9 has a correct answer, not a preference.** Where an action has consequences,
an unanswered check must deny, never permit. An Agent that reads a timeout as "no problem
found" has inverted the meaning of the check.

## Every rule needs three Cases

`CaseCategory` is not metadata. It is the discipline that makes a Dataset trustworthy.

| Category | Asserts | Catches |
| --- | --- | --- |
| `POSITIVE` | the clean path is taken | over-caution, over-escalation, refusing valid work |
| `NEGATIVE` | the violation is refused | the unsafe behavior everyone thinks of first |
| `BOUNDARY` | the ambiguous edge is handled | what real Agents actually fail |

Writing only `NEGATIVE` Cases is the most common Dataset mistake. It produces a suite that
a maximally cautious, useless Agent scores 100% on.

## Which Evaluator proves what

Prefer the deterministic Rule wherever the failure is structural. A Judge call costs money,
adds latency, and is itself non-deterministic — spend it only where language is the
evidence.

| Behavior | Evaluator | Expectation |
| --- | --- | --- |
| Routing | `RULE` | `SkillRouteExpectation` |
| Required action | `RULE` | `ToolCallExpectation(mode="required")` |
| Forbidden action | `RULE` | `ToolCallExpectation(mode="forbidden")` |
| Argument correctness | `RULE` | `ToolArgumentExpectation` |
| End state | `RULE` | `StateExpectation` |
| Cross-turn memory | `RULE` | `StateExpectation` on a later turn |
| Asking vs guessing | `RULE` | `OutputExpectation` |
| Escalation judgment | `RULE` | requires `POSITIVE` **and** `NEGATIVE` Cases |
| Failure direction | `RULE` | `StateExpectation` plus a Case whose Tool errors |
| Holding position | `LLM_JUDGE` | criteria prompt |
| Grounding | `LLM_JUDGE` | criteria prompt against Trace evidence |
| Consistency | — | not expressible; needs repeated Runs |

Absence is as checkable as presence. `mode="forbidden"` is what lets a Rule Evaluator
express "must not act", which is the shape of most compliance requirements.

## Not expressible today

These are real behaviors with no way to assert them in the current contract. Recorded so
the gap is a decision rather than an oversight.

| Gap | Needed |
| --- | --- |
| **Order of operations** — check before act | an ordering Expectation; `TraceSpan.sequence` already carries the data |
| **Call count** — exactly once, at most twice | a count on `ToolCallExpectation`; today only required/forbidden |
| **Turn or step limit** — stop looping | a Run-level bound |
| **Cost** — tokens, latency, redundant calls | not captured in the Trace contract |
| **Run-to-run consistency** | repeated Runs and variance; one Run currently equals one truth |
| **Language behaviors** — grounding, tone, disclosure | the LLM Judge runtime, deferred to P2 |

Order and count are the cheapest to close and need no LLM. Both are pure Rule Evaluator
work, and the Trace already contains everything required to evaluate them.

## Using this catalog

When designing a Dataset for a new Agent:

1. List the behaviors from this catalog that the Agent's business rules actually constrain.
2. For each, write three Cases — `POSITIVE`, `NEGATIVE`, `BOUNDARY`.
3. Map each Case to Expectations using the table above; reach for a Judge only for rows
   that name one.
4. Build a deliberately broken Agent version and confirm the suite catches it. A Dataset
   that has never failed has not been tested.

Step 4 is not optional. An evaluation nobody has seen fail is an assumption, not a result.
