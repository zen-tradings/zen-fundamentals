# zen-fundamentals

An open-source, long-running **fundamental analysis agent that monitors a thesis continuously**, exposed as an API. Define a thesis, point it at primary sources, and it keeps its estimates current as filings and press releases arrive. Every change is point-in-time, cited, and human-reviewed before anyone relies on it.

The first template is **merger arbitrage**. When a deal is announced, the agent builds an initial view: outcome scenarios and close probability, expected timing, key economic and legal terms, closing conditions, and the points that need investor judgment. It then re-estimates as new filings land.

Auditable, reproducible, model-agnostic.

> **Status: design only.** Nothing below is implemented yet. Everything is **planned** unless marked otherwise. Specs live in [`design/rfc/`](design/rfc/) and [`design/schemas/`](design/schemas/).

## What it does

```
sources ──▶ evidence layer ──▶ re-evaluation loop ──────────────────────────────▶ gate ──┬──▶ ThesisVersion + ReviewPacket ──▶ human review ──▶ (optional webhook)
(EDGAR,     (as_of, tier,      impact → extract → estimate → self-check → audit          └──▶ EvaluationRecord (no-change, no notification)
 press,      dedupe; shared    (point-in-time clock on every step)
 web)        across theses)
```

A **thesis** is a declarative spec, not a workflow. It has a subject, a template, tracked quantities, sources, and a policy:

```yaml
thesis: acme-buys-widgetco
template: { id: merger_arb, version: "1.0.0" }
subject:
  target:    { name: "WidgetCo Inc.", cik: "0000000001", ticker: WDGT }
  acquirers: [{ name: "Acme Corp.", cik: "0000000002", ticker: ACME }]
  announcement: { as_of: "2026-03-02T12:05:00Z" }
sources:                         # priority order
  - type: edgar                  # primary
    ciks: ["0000000001", "0000000002"]
    forms: ["8-K", "S-4", "DEFM14A", "PREM14A", "425", "SC TO-T", "SC 14D9"]
  - type: press_release          # primary
    issuers: ["0000000001", "0000000002"]
  - type: web_search             # secondary
    queries: ["WidgetCo Acme antitrust"]
  - type: market_data            # market-implied baseline only; never shown to the estimator
    tickers: [WDGT, ACME]
policy:
  material_change:               # overrides template defaults (example values)
    scenarios: { prob_abs: 0.05, price_rel: 0.05 }
    expected_close_date: { days: 14 }
  budget_usd_per_evaluation: 1.00
  max_latency_s: 600
  review: required
delivery:
  webhook: { url: https://example.com/hook, on: [version_approved] }   # optional
```

Every material update produces an immutable **ThesisVersion** containing:

- the new value of each tracked quantity (`scenarios` → derived `close_probability`, `expected_close_date`, `conditions`, `key_terms`);
- the delta from the last approved version;
- the evidence behind each change;
- the market-implied probability for comparison;
- the estimator's self-check and any failure recoveries;
- a **ReviewPacket** that separates what was *read* from evidence from what a model *inferred* (and which model, in which role), and lists items flagged as uncertain or recommended for investor judgment.

## API

Planned.

```
POST   /v1/theses                       create from spec
GET    /v1/theses/:id                   status, head version, pending candidate, monitor state
PUT    /v1/theses/:id                   revise spec (new spec_revision); supersedes in-flight evaluations and unapproved candidates
POST   /v1/theses/:id/run               re-evaluate now  (?dry_run=true → evaluate, commit nothing)
POST   /v1/theses/:id/watch             start / stop the continuous loop
GET    /v1/theses/:id/versions          version history (seq, clock, material changes, review state)
GET    /v1/theses/:id/evaluations       evaluation records, including no-change decisions
POST   /v1/theses/:id/feedback          outcome_audit on resolution
GET    /v1/versions/:id                 values, deltas, evidence set, market-implied, self-check, trace, cost
GET    /v1/versions/:id/review-packet   ReviewPacket (JSON, or ?format=md)
POST   /v1/versions/:id/approve         approve a needs_review version → becomes head; fires webhook via outbox
POST   /v1/versions/:id/reject          reject with reason; head unchanged
POST   /v1/versions/:id/feedback        user_rating | tool_execution_quality
DELETE /v1/evaluations/:id              cancel an in-flight evaluation; refused once its version is committed
POST   /v1/evaluations/:id/answer       resolve a needs_input question
GET    /v1/evidence/:id                 shared evidence item (source, tier, as_of, hash)
POST   /v1/evals/replay                 start a replay evaluation run (RFC-007)
GET    /v1/evals/:id                    results table + exclusions
GET    /v1/templates  ·  /v1/connectors  ·  /v1/skills
```

Streaming via SSE on `/run` for progressive steps (impact, extraction, estimate, audit). An OpenAPI spec is planned at `design/openapi.yaml`. Payloads follow [`design/schemas/`](design/schemas/).

## Design

Ranked by priority.

1. **Thesis, not content.** The core object is a thesis with tracked quantities. The output is an immutable ThesisVersion with deltas, evidence, and a ReviewPacket ([RFC-004](design/rfc/004-thesis-and-thesis-version.md)). Templates are maintained centrally and define quantities, required evidence, extraction targets, packet layout, and default thresholds. `merger_arb` ([RFC-008](design/rfc/008-merger-arb-template.md)) is the only template that ships. *Trade-off: central templates give up per-user flexibility so that one replay evaluation covers every thesis.*
2. **Point-in-time evidence.** Every evidence item carries `as_of` (publication or filing time). Every estimation step runs with a `clock`. Evidence with `as_of > clock` in a model's context is a **hard error**, not a warning. *Trade-off: failing hard costs availability, but a version that silently used future evidence would be undetectable downstream.*
3. **Shared evidence, per-thesis judgment.** One filing is fetched, normalized, and extracted once, and cited by many theses. Judgment (impact, estimates, versions) is per-thesis and reads evidence only through a point-in-time view ([RFC-001](design/rfc/001-evidence-judgment-separation.md)).
4. **Source-agnostic.** One adapter interface (`discover → fetch → normalize`). Priority, recency, and trust tier (`primary` / `secondary`) are config. Evidence is ranked before any model sees it.
5. **Skills & MCP.** Source adapters and tools ship as MCP servers. Extraction targets and prompts are versioned with the template and model-independent.
6. **Context engineering.** `TaskContract → SearchPlan → EvidenceMatrix`: the estimator sees ranked, deduplicated, quota-limited, point-in-time evidence, never raw results. Long runs compact instead of growing.
7. **Re-evaluation loop with a material-change gate.** New evidence → which quantities does it affect? → extract → re-estimate → self-check → audit. If any change exceeds `policy.material_change` against the approved head, a new version goes to `needs_review`. Otherwise the evidence and the no-change decision are recorded without notifying anyone ([RFC-005](design/rfc/005-reevaluation-loop-and-material-change-gate.md)). *Trade-off: comparing against the approved head (not the last evaluation) lets slow drift accumulate until it crosses the threshold, at the cost of occasionally paging on a change no single filing caused.*
8. **Role-based model routing.** The planner and estimator use the strongest available model. The extractor uses a low-cost model. The auditor uses a low-cost model **from a different provider than the estimator**, so the two don't share failure modes; this is enforced fail-closed. Separate reasoning and output token budgets. *Trade-off: provider diversity buys independent errors at the cost of a weaker judge, so the auditor only answers narrow, checkable questions.*
9. **Subagent orchestration.** Lanes have their own budget, timeout, context, and tool allowlist. Hand-offs are typed artifacts (`EvidenceMatrix`, `ImpactAssessment`, `ExtractionSet`, `CandidateEstimate`, `AuditReport`, `ReviewPacket`). Failed lanes are isolated, not restarted.
10. **Self-check and recovery.** The estimator runs an explicit self-check before emitting (numbers reconcile, every change is cited, every `as_of ≤ clock`) and records the result. Tool and extraction failures are retried or routed to alternate paths, and every recovery is recorded.
11. **ReviewPacket.** For each changed quantity: old → new value, the evidence that caused the change (source, tier, `as_of`), and each claim labeled `extracted`, `computed`, or `inferred` (with model and role). Scenario table, market-implied comparison, conflicts, uncertain items, and investor-judgment items. A failed audit blocks approval unless someone overrides it with a reason ([RFC-006](design/rfc/006-review-packet.md)).
12. **Replay evaluation.** 40 resolved US deals replayed in `as_of` order with a moving clock. Brier score and calibration, close-date error, condition recall, citation precision, point-in-time violations (must be 0), cost and latency. Baselines: base rate and market-implied. Ablations: low-cost planner, no auditor. Contamination is handled by a training-cutoff split, an anonymized variant, and a knowledge probe; headline numbers use only post-cutoff or anonymized runs. Robustness variants cover distractor evidence, injected errors, and injected tool failures ([RFC-007](design/rfc/007-replay-evaluation.md)). No results exist yet.
13. **Structured feedback.** `user_rating`, `outcome_audit` (scored with the replay metric definitions, and promotable into the replay dataset), and `tool_execution_quality`.
14. **Durable execution.** Separate lifecycle state machines ([RFC-002](design/rfc/002-job-lifecycle-state-machine.md)), leased workers with fencing tokens ([RFC-003](design/rfc/003-fencing-token-for-job-execution.md)), and an idempotent outbox. The idempotency key is `(thesis, spec_revision, clock, evidence_set)`.
15. **Lifecycle.** Evaluations move `queued → running → needs_input ⇄ running → completed | failed | cancelled | superseded`. Versions move `needs_review → approved | rejected | superseded`. A newer material candidate supersedes an unreviewed one and is diffed against the approved head. Revising the spec supersedes in-flight work. Retries survive restarts and honor `Retry-After`, and a terminal failure never rewrites a committed version.
16. **Safeguards & permissions.** Scoped API keys; per-lane tool allowlists (the estimator has no fetch tools); review required by default (`review: auto` is replay-only); fail-closed gates, held and never silently degraded.
17. **Observability.** Content-free per-call telemetry (model, provider, role, tokens, cost, latency, finish reason), with per-thesis SLO rollups on the API.
18. **Delivery.** One optional signed webhook on version approval, sent through the outbox.

## Quick start

Planned. There is no runnable code yet.

```bash
git clone https://github.com/zen-tradings/zen-fundamentals
cd zen-fundamentals && cp .env.example .env
docker compose up          # api + worker + postgres
curl -X POST localhost:8080/v1/theses -d @examples/acme-buys-widgetco.yaml
```

## Reference

Design lessons draw on [zen-tradings/internal-marketing-agent](https://github.com/zen-tradings/internal-marketing-agent): evidence tiers, role-split models, fail-closed gates, idempotent delivery, and offline eval.

## Status

Early design. RFCs in [`design/rfc/`](design/rfc/):

- [001](design/rfc/001-evidence-judgment-separation.md): shared evidence layer vs. per-thesis judgment layer
- [002](design/rfc/002-job-lifecycle-state-machine.md): separate lifecycle state machines
- [003](design/rfc/003-fencing-token-for-job-execution.md): fencing tokens for leased execution
- [004](design/rfc/004-thesis-and-thesis-version.md): Thesis and ThesisVersion model, feedback
- [005](design/rfc/005-reevaluation-loop-and-material-change-gate.md): re-evaluation loop, material-change gate, self-check, failure recovery
- [006](design/rfc/006-review-packet.md): ReviewPacket
- [007](design/rfc/007-replay-evaluation.md): replay evaluation
- [008](design/rfc/008-merger-arb-template.md): `merger_arb` template, market-implied probability

Schemas in [`design/schemas/`](design/schemas/): [Thesis](design/schemas/thesis.schema.json), [ThesisVersion](design/schemas/thesis-version.schema.json), [EvidenceItem](design/schemas/evidence-item.schema.json), [ReviewPacket](design/schemas/review-packet.schema.json), [eval results row](design/schemas/eval-result-row.schema.json).

Planned: OpenAPI spec, model capability profiles, replay dataset manifest and annotation guide, reference implementation.

## Open questions

- **Post-cutoff terminated deals are scarce.** Recent model cutoffs plus months-long deals may leave too few terminated deals in the named post-cutoff subset, so headline termination performance may rest mainly on anonymized runs.
- **Anonymization strength.** Sector plus relative size may still re-identify famous deals. We will only know after the re-identification probe runs on a built corpus.
- **Free, redistributable daily price data.** Without it, the market-implied baseline can't be rebuilt exactly by third parties.
- **Threshold shape.** Absolute vs. log-odds material-change thresholds for probabilities near 0 or 1.
- **Time-only re-estimation.** Should a heartbeat re-estimate run with no new evidence as the outside date approaches?
- **Estimator and market signal.** Keeping market prices away from the estimator keeps "agent vs. market" meaningful but discards a strong signal; the planned ablation will quantify the cost.
- **Eval judge independence.** Should the eval-time citation judge come from a third provider, distinct from both the estimator and the auditor?

## License

Apache-2.0
