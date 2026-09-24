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
ingest ─▶ as_of + tier ─▶ route ─▶ batch ─▶ impact ─▶ extract ─▶ estimate ─▶ self-check ─▶ audit ─▶ gate ─┬─▶ ThesisVersion (needs_review)
(adapters)                (by CIK,  (debounce)  (planner) (extractor) (estimator) (estimator   (auditor)  └─▶ EvaluationRecord (no notify)
                          form)                                                  + code)
```

Every step from `impact` onward runs with a fixed `clock` (see *Point-in-time*). Tool and extraction failures at any step go through *Failure recovery* below.

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

5. **Impact mapping (planner role).** Input: the new evidence, the current head values, and the template's quantity definitions. Output: an `ImpactAssessment` that says, for **each** tracked quantity, `affected: bool` with a short rationale and pointers to evidence spans. Template rules are applied first and can only *add* affected quantities, never remove them. For example, `DEFM14A → {conditions, key_terms, expected_close_date}` and `8-K mentioning "second request" → {conditions, scenarios, expected_close_date}`. Template dependency edges then propagate: if `conditions` is affected, then `scenarios` and `expected_close_date` are too, and `scenarios` always implies the derived `close_probability` (RFC-008).

   If nothing is affected, the job ends with an EvaluationRecord (`decision: no_impact`).

   > Trade-off: re-estimating only affected quantities saves cost and avoids spurious drift in quantities that have no new reason to move. The risk is a missed cross-effect. Asking the planner about every quantity, plus dependency edges, reduces that risk. Not re-estimating everything on every filing is a deliberate cost/recall choice, and RFC-007 measures it.

6. **Extract (extractor role).** For affected quantities, run the template's extraction targets over the new documents. Document-local extractions come from the shared cache when present (RFC-001).

7. **Estimate (estimator role).** Re-estimate the affected quantities from the EvidenceMatrix, which is the ranked, deduplicated, quota-limited, point-in-time view of the thesis's evidence (`TaskContract → SearchPlan → EvidenceMatrix`), plus the extractions. The estimator also reconciles conflicting signals (for example a press release and an 8-K that disagree on the expected timing) and records how it resolved them. The estimator lane has **no fetch tools**; it sees only what the EvidenceMatrix gives it.

   `close_probability` is **derived** from the `scenarios` quantity, not estimated separately (RFC-008). The estimator re-estimates scenarios, and code computes `close_probability`.

   The estimator does **not** see market prices or the market-implied probability. Those are computed alongside the estimate and shown to the reviewer (RFC-006).

   > Trade-off: keeping the market signal away from the estimator keeps its view independent. That is what makes "agent vs. market" a meaningful comparison in RFC-007, and it stops the agent from simply echoing the spread. The cost is that the estimator ignores one of the most informative signals a practitioner has. An ablation where the estimator does see market data is planned.

8. **Self-check (estimator role + code).** Before emitting a candidate, the estimator runs an explicit self-check, and the result is recorded in `ThesisVersion.self_check` or `EvaluationRecord.self_check`. The checks are:

   | Check | How |
   |---|---|
   | Scenario probabilities sum to 1 (tolerance 1e-6); every probability is in [0, 1] | code |
   | `close_probability` equals the value derived from scenarios | code |
   | `expected_close_date ≥ clock`; `expected_close_date ≤` current outside date, or an extension is cited | code |
   | Key terms reconcile: headline price is consistent with consideration (cash + exchange ratio × reference price, within the collar); the completed-scenario price matches the consideration value | code, with tolerances from the template |
   | Every changed quantity has ≥ 1 claim with a citation | code |
   | Every cited `as_of ≤ clock` | code |
   | Condition statuses agree with scenarios (for example a `failed` regulatory condition alongside a high `completed` probability) and the estimator's own narrative agrees with its numbers | estimator model, one self-review pass |

   On failure the estimator gets **one** revision. After that:
   - a failed numeric reconciliation (sums, derivation, term arithmetic) means the job **fails** (`self_check_failed`), because a version whose numbers don't add up is not reviewable;
   - a missing citation means the quantity is flagged uncertain and the audit will block approval;
   - an `as_of` violation is a hard error, as always;
   - a model-judged inconsistency means the item is flagged uncertain and listed in the ReviewPacket.

   > Trade-off: several self-checks duplicate deterministic audit checks. We keep both because the self-check runs before the auditor, is cheap, and lets the estimator fix its own mistakes in context. The auditor stays an independent second line. RFC-007 measures each line's catch rate separately.

9. **Audit (auditor role + deterministic checks).** See RFC-006. Summary:
   - deterministic: every cited evidence ID is in `evidence_set`, and every `as_of ≤ clock`;
   - model: does each cited span support its claim, and is each claim's `extracted` / `inferred` label correct.
   If a citation fails, the estimator gets **one** repair attempt. Claims that are still unsupported afterward are kept, marked `unsupported`, and block approval without an override.

10. **Gate.** Compare the candidate against the approved head (RFC-004) using `policy.material_change`, which falls back to template defaults.

### Material-change rules

Rules are per quantity type. The shipped defaults are in the `merger_arb` template (RFC-008). They are **starting points to be tuned against replay results, not validated values.**

| Quantity type | Material if |
|---|---|
| `probability` | `|new − head| ≥ abs` (for a derived probability, this applies to the derived value) |
| `scenario_set` | any outcome's probability moves by `≥ prob_abs`, or any outcome's target price moves by `≥ price_rel` (relative), or an outcome is added or removed |
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

This records the evidence and the no-change decision without notifying anyone. Fields: `thesis_id`, `spec_revision`, `clock`, `trigger`, `evidence_set`, `impact_assessment`, `proposed_values` (when estimation ran), `deltas_vs_head`, `decision` (`no_impact | no_change | below_threshold | consistent_with_pending | version_created`), `version_id` (when created), `market_implied`, `self_check`, `recoveries`, `routing`, `cost`, `latency`. Records are immutable and written in the same fenced transaction as any version.

### Failure recovery

Tool and extraction failures are retried or routed to an alternate path, and every failure is recorded as a `RecoveryEvent` in the version or EvaluationRecord (`recoveries[]`). Each event is also emitted as `tool_execution_quality` feedback with no human needed.

| Failure | Retry | Alternate path | If still failing |
|---|---|---|---|
| Source fetch: 5xx, timeout, connection reset | exponential backoff, max 4 attempts, honor `Retry-After` | mirror endpoint if the adapter declares one (for example the EDGAR full submission `.txt` instead of the primary HTML document) | the evidence stays invisible; the job continues without it, and the recovery event is recorded (the item will be picked up by a later ingest) |
| 429 / rate limit | wait for `Retry-After`, counted against `max_latency_s` | none | hold the job (`failed: rate_limited`), retried by the scheduler |
| Document parse / normalize failure (malformed HTML, broken tables) | 1 | alternate normalizer (text-only, PDF exhibit, XBRL where present) | item stored as `normalize_failed`; not citable |
| Extractor model: timeout, malformed output, schema violation | 1 with a schema-repair prompt | alternate extractor route (same cost tier, different provider) | quantity marked `extraction_unavailable`, flagged uncertain in the packet; the estimator may still reason from the EvidenceMatrix text, but those claims are `inferred` |
| Estimator model failure | 1 | alternate estimator route of the same capability tier, if configured | job `failed` (never silently downgraded to a weaker tier) |
| Auditor unavailable | 1 | alternate auditor route that still satisfies the provider-diversity constraint | job held, fail-closed |

`RecoveryEvent`: `{step, tool_or_route, error_class, attempts, path: retry | alternate:<name> | degraded | failed, outcome: recovered | degraded | failed, latency_ms}`.

> Trade-off: routing to alternates keeps the loop alive through routine outages. But an alternate extractor or normalizer may be less accurate, so every alternate path is marked in the ReviewPacket and a reviewer can discount it. The estimator is never swapped for a weaker tier, because that is where accuracy lives.

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
