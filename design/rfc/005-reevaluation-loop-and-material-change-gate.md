# RFC-005: Re-evaluation Loop and Material-Change Gate

Status: Discussion

Date: 2026-09-23

Depends on: RFC-001, RFC-002, RFC-003, RFC-004

## Problem

The old monitor loop scored "novelty" and published once novelty crossed a threshold. That fits content, not beliefs. A new filing can be completely novel and still change nothing we track (a routine 425 re-posting investor slides). A short 8-K line ("the parties received a Second Request") can move two quantities a lot. The loop has to ask **what this evidence changes**, not how new it is.

## Proposal

### Loop overview

```
evidence layer                     judgment layer (per thesis)
──────────────                     ────────────────────────────────────────────────────────────────
ingest ─▶ as_of + tier ─▶ route ─▶ batch ─▶ impact ─▶ extract ─▶ estimate ─▶ audit ─▶ gate ─┬─▶ ThesisVersion (needs_review)
(adapters)                (by CIK,  (debounce)  (planner) (extractor) (estimator) (auditor)  └─▶ EvaluationRecord (no notify)
                          form)
```

Every step from `impact` onward runs with a fixed `clock` (see *Point-in-time*).

### Steps

1. **Ingest (evidence layer).** Adapters `discover → fetch → normalize`. Each item gets `as_of`, `tier`, `doc_type`, and entity links (CIKs, tickers). Duplicates are dropped by content hash.

2. **Route (deterministic, no model).** Each thesis has a subscription derived from `sources`: entity IDs and form types. An evidence item is routed to every active, watching thesis whose subscription it matches.

   > Trade-off: deterministic routing is cheap and auditable, but it will miss relevant evidence that doesn't name a subscribed entity (for example an FTC statement that names only the deal). Discovery requests (RFC-001) and secondary web search cover part of that gap.

3. **Batch.** Items routed to a thesis within `policy.debounce_s` of the first unprocessed item are batched into one evaluation job. Resolution-class evidence (template-defined, for example 8-K Item 1.02 termination or Item 2.01 completion) skips the debounce.

   > Trade-off: debouncing merges an S-4 and its same-day exhibits into one evaluation, which cuts cost and duplicate versions. The price is up to `debounce_s` of added latency.

4. **Fix the clock.** The job's `clock` is set when the job is created and never changes afterward:
   - live: `clock = max(as_of of batch)`. That is always ≤ wall time at job creation, and the job still sees every earlier evidence item;
   - replay (RFC-007): `clock` = the as_of of the replay event.

   Evidence that arrives after job creation waits for the next job. Because of this, every live evaluation can later be re-run in replay with the same `clock` and `evidence_set`.

5. **Impact mapping (planner role).** Input: the new evidence, the current head values, and the template's quantity definitions. Output: an `ImpactAssessment` that says, for **each** tracked quantity, `affected: bool` with a short rationale and pointers to evidence spans. Template rules are applied first and can only *add* affected quantities, never remove them. For example, `DEFM14A → {conditions, key_terms, expected_close_date}` and `8-K mentioning "second request" → {conditions, close_probability, expected_close_date}`. Template dependency edges then propagate: if `conditions` is affected, then `close_probability` and `expected_close_date` are too (RFC-008).

   If nothing is affected, the job ends with an EvaluationRecord (`decision: no_impact`).

   > Trade-off: re-estimating only affected quantities saves cost and avoids spurious drift in quantities that have no new reason to move. The risk is a missed cross-effect. Asking the planner about every quantity, plus dependency edges, reduces that risk. Not re-estimating everything on every filing is a deliberate cost/recall choice, and RFC-007 measures it.

6. **Extract (extractor role).** For affected quantities, run the template's extraction targets over the new documents. Document-local extractions come from the shared cache when present (RFC-001).

7. **Estimate (estimator role).** Re-estimate the affected quantities from the EvidenceMatrix, which is the ranked, deduplicated, quota-limited, point-in-time view of the thesis's evidence (`TaskContract → SearchPlan → EvidenceMatrix`), plus the extractions. The estimator also reconciles conflicting signals (for example a press release and an 8-K that disagree on the expected timing) and records how it resolved them. The estimator lane has **no fetch tools**; it sees only what the EvidenceMatrix gives it.

8. **Audit (auditor role + deterministic checks).** See RFC-006. Summary:
   - deterministic: every cited evidence ID is in `evidence_set`, and every `as_of ≤ clock`;
   - model: does each cited span support its claim, and is each claim's `extracted` / `inferred` label correct.
   If a citation fails, the estimator gets **one** repair attempt. Claims that are still unsupported afterward are kept, marked `unsupported`, and block approval without an override.

9. **Gate.** Compare the candidate against the approved head (RFC-004) using `policy.material_change`, which falls back to template defaults.

### Material-change rules

Rules are per quantity type. The shipped defaults are in the `merger_arb` template (RFC-008). They are **starting points to be tuned against replay results, not validated values.**

| Quantity type | Material if |
|---|---|
| `probability` | `|new − head| ≥ abs` |
| `date` | `|new − head| ≥ days` |
| `condition_list` | any condition added or removed, or any status change in `on:` (default: all status changes) |
| `key_terms` | any field changes (default), or only the fields listed in `on:` |
| any | the trigger is resolution-class evidence |

Gate outcomes:

| Situation | Result |
|---|---|
| No quantity material, no pending candidate | EvaluationRecord `below_threshold` (proposed values and deltas stored; no notification) |
| Some quantity material vs. head, no pending candidate | new ThesisVersion, `needs_review` |
| Material vs. head, pending candidate exists, and the new candidate is material vs. pending | new version supersedes the pending one |
| Material vs. head but within threshold of the pending candidate | EvaluationRecord `consistent_with_pending` |
| Unchanged | EvaluationRecord `no_change` |

> Trade-off: a single per-quantity threshold is easy to explain and review, but it ignores the context the quantity sits in. A 0.05 move from 0.50 is different from a 0.05 move from 0.97, where the implied spread can be very sensitive. Log-odds thresholds are an option (see open questions). We start simple so reviewers can predict when they'll be paged.

### EvaluationRecord

This records the evidence and the no-change decision without notifying anyone. Fields: `thesis_id`, `spec_revision`, `clock`, `trigger`, `evidence_set`, `impact_assessment`, `proposed_values` (when estimation ran), `deltas_vs_head`, `decision` (`no_impact | no_change | below_threshold | consistent_with_pending | version_created`), `version_id` (when created), `routing`, `cost`, `latency`. Records are immutable and written in the same fenced transaction as any version.

### Point-in-time

- Every evaluation job carries `clock`. Every read of the evidence store takes `clock` and filters on `as_of ≤ clock`.
- Derived artifacts (extractions, EvidenceMatrix rows) inherit `as_of = max(as_of of inputs)`.
- Before any model call, the context builder asserts that every evidence item in the prompt context has `as_of ≤ clock`. If one doesn't, that is a **hard error**: the job fails with `point_in_time_violation`, no version or record is committed, and the event is counted in telemetry and in RFC-007. It is not a warning, and it is not retried with the item dropped.
- Evidence without a reliable `as_of` cannot be used. EDGAR `as_of` is the acceptance datetime. A press release's `as_of` is the wire or dateline timestamp, and a date-only timestamp is pinned to 23:59:59 in the publisher's timezone, which is the later, safer choice. For a web item with no publication date, `as_of = retrieved_at` in live mode. Such an item is therefore invisible to any replay clock earlier than retrieval.

> Trade-off: the filter should make the assertion redundant, and it's there anyway. It catches bugs like a cached extraction from a later amendment or a join that forgot the clock. Failing hard costs availability, but a version that silently used future evidence would be worse than no version, because nothing downstream could detect it.

### Lifecycle, fencing, idempotency

- Evaluation jobs follow the RFC-002 lifecycle: `queued → running → (needs_input ⇄ running) → completed | failed | cancelled | superseded`. A spec revision supersedes queued and running jobs from older revisions.
- `needs_input`: the planner can pause and ask the thesis owner a question when the subject is ambiguous (for example which share class, or which of two announced deals). The question is answered via `POST /v1/evaluations/:id/answer`.
- Leased execution with RFC-003 fencing. Commit is one transaction: version or EvaluationRecord, ReviewPacket, `head` pointer unchanged (only approval moves it), and the outbox intent (if any).
- Idempotency key: `(thesis_id, spec_revision, clock, hash(evidence_set))`. A re-delivered batch or a reaped-and-reclaimed job cannot produce a second version for the same inputs.
- Retries survive restarts and honor provider `Retry-After`. A terminal failure never rewrites a committed version.

### Budget and latency

`budget_usd_per_evaluation` and `max_latency_s` are enforced. Under pressure, the planner degrades in a fixed order and logs what it dropped in the ReviewPacket:

1. drop secondary-tier evidence;
2. skip re-estimating quantities that are marked affected only through dependency edges;
3. hold the job (`failed: budget_exceeded`).

It never skips the audit.

> Trade-off: fixing the degrade order makes cost overruns predictable and visible to reviewers. It rules out smarter per-case trade-offs a planner could make on its own.

## Open questions

- Log-odds vs. absolute thresholds for `close_probability`.
- Should a periodic "heartbeat" re-estimation run with no new evidence? Time passing alone moves `expected_close_date` risk as the outside date gets closer.
- Debounce and resolution latency: is skipping the debounce for resolution-class evidence enough, or do some mid-deal events (a second request, an injunction) need to skip it too?
