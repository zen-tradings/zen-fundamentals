# zen-fundamentals

An open-source, long-running **fundamental analysis agent that monitors a thesis continuously**, exposed as an API. Define a thesis, point it at primary sources, and it keeps its estimates current as filings and press releases arrive. Every change is point-in-time, cited, and human-reviewed before anyone relies on it.

The first template is **neocloud deal watch**. Pick a neocloud (a GPU-cloud or AI data-center company) and a list of candidate buyers (AI labs such as Anthropic and OpenAI, hyperscalers, chipmakers). The agent estimates who is likely to acquire it or take a strategic stake within a fixed horizon, and how likely each is. It maps the target's contracts, investors, and financing ties to each candidate, tracks deal signals, and flags the points that need investor judgment. It then re-estimates as new filings, press releases, and reports land.

Auditable, reproducible, model-agnostic.

> **Status: design only.** Nothing below is implemented yet. Everything is **planned** unless marked otherwise. Specs live in [`design/rfc/`](design/rfc/) and [`design/schemas/`](design/schemas/).

## What it does

```
sources ──▶ evidence layer ──▶ re-evaluation loop ──────────────────────────────▶ gate ──┬──▶ ThesisVersion + ReviewPacket ──▶ human review ──▶ (optional webhook)
(EDGAR,     (as_of, tier,      impact → extract → estimate → self-check → audit          └──▶ EvaluationRecord (no-change, no notification)
 press,      dedupe; shared    (point-in-time clock on every step;
 news,       across theses)     monthly scheduled re-estimate when nothing arrives)
 web)
```

A **thesis** is a declarative spec, not a workflow. It has a subject, a template, tracked quantities, sources, and a policy:

```yaml
thesis: who-buys-gridcompute
template: { id: neocloud_deal, version: "1.0.0" }
subject:
  target: { name: "GridCompute Inc.", listing: private, cik: "0000000001" }
  candidates:                    # everyone else is "other"
    - { key: anthropic, name: "Anthropic PBC",   type: ai_lab }
    - { key: openai,    name: "OpenAI",          type: ai_lab }
    - { key: microsoft, name: "Microsoft Corp.", ticker: MSFT, type: hyperscaler }
    - { key: nvidia,    name: "NVIDIA Corp.",    ticker: NVDA, type: chipmaker }
  horizon: { start: "2026-10-01T00:00:00Z", end: "2027-09-30" }
sources:                         # priority order
  - type: edgar                  # primary; candidate filings routed only if they mention the target
    ciks: ["0000000001"]
    related_tickers: [MSFT, NVDA]   # candidates' filings, routed only if they mention the target
    forms: ["8-K", "10-K", "10-Q", "S-1", "SC 13D", "SC 13G", "D"]
  - type: press_release          # primary
    issuers: [gridcompute, anthropic, openai, microsoft, nvidia]
  - type: news                   # secondary; named outlets
    outlets: [reuters, bloomberg, the-information]
  - type: web_search             # secondary; live only
    queries: ["GridCompute acquisition"]
policy:
  material_change:               # overrides template defaults (example values)
    acquirer_distribution: { logit_abs: 0.7, prob_abs_min: 0.02 }
    stake_probabilities:   { logit_abs: 0.7, prob_abs_min: 0.02 }
  budget_usd_per_evaluation: 1.00
  max_latency_s: 600
  review: required
delivery:
  webhook: { url: https://example.com/hook, on: [version_approved] }   # optional
```

Every material update produces an immutable **ThesisVersion** containing:

- the new value of each tracked quantity: `acquirer_distribution` (who signs the first acquisition: each candidate, `other`, or `none`) → derived `p_acquired`; `stake_probabilities` (per candidate, a stake of ≥ 5% or ≥ US$1bn); `expected_announcement_date`; `relationships`; `signals`; `target_facts`. Every stake and equity or debt tie carries a **structure tag** (`vendor_financing`, `capacity_backstop`, `customer_equity_kicker`, `pure_equity`, `undetermined`), because much of the equity in this sector is a way to sell GPUs or lock in capacity rather than a strategic bet. Tags describe the deal but never decide whether a stake counted;
- the delta from the last approved version;
- the evidence behind each change;
- a rule-based reference prior ("the biggest customer or investor is the likeliest buyer") for comparison;
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
GET    /v1/versions/:id                 values, deltas, evidence set, reference prior, self-check, trace, cost
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

Ranked by priority: first what makes the agent auditable and reproducible, then the core product behavior, then the execution infrastructure it runs on.

1. **Point-in-time evidence.** Every evidence item carries `as_of` (publication or filing time). Every estimation step runs with a `clock`. Evidence with `as_of > clock` in a model's context is a **hard error**, not a warning. *Trade-off: failing hard costs availability, but a version that silently used future evidence would be undetectable downstream.*
2. **Replay evaluation.** Historical neocloud target-windows (**target:** ≥ 30 targets, ≥ 60 twelve-month windows) replayed in `as_of` order with a moving clock. Log loss and Brier on who acquires, stake Brier, calibration at low base rates, top-1/top-3 rank of the eventual acquirer or investor before the announcement, lead time against false-alarm rate, relationship recall, citation precision, point-in-time violations (must be 0), cost and latency. Baselines: base rate and the reference prior. Ablations: low-cost planner, no auditor, primary sources only. Contamination is handled by a training-cutoff split on the whole window, an anonymized variant, and a knowledge probe; headline numbers use only post-cutoff or anonymized runs. Robustness variants cover distractor evidence (including false "in talks" rumors), injected errors, and injected tool failures ([RFC-007](design/rfc/007-replay-evaluation.md)). No results exist yet.
3. **ReviewPacket.** For each changed quantity: old → new value, the evidence that caused the change (source, tier, `as_of`), and each claim labeled `extracted`, `computed`, or `inferred` (with model and role). Acquirer and stake tables, reference-prior comparison, conflicts, uncertain items, and investor-judgment items. A failed audit blocks approval unless someone overrides it with a reason. Any change supported only by news or rumor fails the audit by design, so a human always signs off on it ([RFC-006](design/rfc/006-review-packet.md)).
4. **Thesis, not content.** The core object is a thesis with tracked quantities. The output is an immutable ThesisVersion with deltas, evidence, and a ReviewPacket ([RFC-004](design/rfc/004-thesis-and-thesis-version.md)). Templates are maintained centrally and define quantities, outcome definitions, required evidence, extraction targets, packet layout, and default thresholds. `neocloud_deal` ([RFC-008](design/rfc/008-neocloud-deal-template.md)) is the only template that ships. *Trade-off: central templates give up per-user flexibility so that one replay evaluation covers every thesis.*
5. **Re-evaluation loop with a material-change gate.** New evidence (or a monthly scheduled re-estimate, so probabilities decay as the horizon runs out) → which quantities does it affect? → extract → re-estimate → self-check → audit. If any change exceeds `policy.material_change` against the approved head, a new version goes to `needs_review`. Probability thresholds are in log-odds with an absolute floor, because base rates are low. Otherwise the evidence and the no-change decision are recorded without notifying anyone ([RFC-005](design/rfc/005-reevaluation-loop-and-material-change-gate.md)). *Trade-off: comparing against the approved head (not the last evaluation) lets slow drift accumulate until it crosses the threshold, at the cost of occasionally paging on a change no single filing caused.*
6. **Self-check and recovery.** The estimator runs an explicit self-check before emitting (the acquirer distribution sums to 1, each candidate's stake probability is at least its acquisition probability, commercial structure tags link to the contract behind them, every change is cited, every `as_of ≤ clock`) and records the result. A scheduled re-estimate cites the elapsed time instead of new evidence. Tool and extraction failures are retried or routed to alternate paths, and every recovery is recorded.
7. **Role-based model routing.** The planner and estimator use the strongest available model. The extractor uses a low-cost model. The auditor uses a low-cost model **from a different provider than the estimator**, so the two don't share failure modes; this is enforced fail-closed. Separate reasoning and output token budgets. Some candidates are also model providers, so every version flags any role whose provider is a named candidate, and replay results are split by that flag. *Trade-off: provider diversity buys independent errors at the cost of a weaker judge, so the auditor only answers narrow, checkable questions.*
8. **Safeguards & permissions.** Public or licensed sources only, with no path for material non-public information; scoped API keys; per-lane tool allowlists (the estimator has no fetch tools); review required by default (`review: auto` is replay-only); fail-closed gates, held and never silently degraded.
9. **Shared evidence, per-thesis judgment.** One filing is fetched, normalized, and extracted once, and cited by many theses: a hyperscaler's 10-K that names several GPU-cloud suppliers serves every thesis on those neoclouds. Judgment (impact, estimates, versions) is per-thesis and reads evidence only through a point-in-time view ([RFC-001](design/rfc/001-evidence-judgment-separation.md)).
10. **Structured feedback.** `user_rating`, `outcome_audit` (scored with the replay metric definitions, and promotable into the replay dataset), and `tool_execution_quality`.
11. **Context engineering.** `TaskContract → SearchPlan → EvidenceMatrix`: the estimator sees ranked, deduplicated, quota-limited, point-in-time evidence, never raw results. Long runs compact instead of growing.
12. **Durable execution & lifecycle.** Separate lifecycle state machines ([RFC-002](design/rfc/002-job-lifecycle-state-machine.md)), leased workers with fencing tokens ([RFC-003](design/rfc/003-fencing-token-for-job-execution.md)), and an idempotent outbox. The idempotency key is `(thesis, spec_revision, clock, evidence_set)`. Evaluations move `queued → running → needs_input ⇄ running → completed | failed | cancelled | superseded`. Versions move `needs_review → approved | rejected | superseded`. A newer material candidate supersedes an unreviewed one and is diffed against the approved head. Revising the spec supersedes in-flight work. Retries survive restarts and honor `Retry-After`, and a terminal failure never rewrites a committed version.
13. **Subagent orchestration.** Lanes have their own budget, timeout, context, and tool allowlist. Hand-offs are typed artifacts (`EvidenceMatrix`, `ImpactAssessment`, `ExtractionSet`, `CandidateEstimate`, `AuditReport`, `ReviewPacket`). Failed lanes are isolated, not restarted.
14. **Source-agnostic.** One adapter interface (`discover → fetch → normalize`) for EDGAR, press releases, named-outlet news, and web search. Priority, recency, trust tier (`primary` / `secondary`), and outlet reliability are config. Evidence is ranked before any model sees it. Under budget pressure, low-reliability sources are dropped first and trusted news last, since it is often the only signal for private neoclouds.
15. **Skills & MCP.** Source adapters and tools ship as MCP servers. Extraction targets and prompts are versioned with the template and model-independent.
16. **Observability.** Content-free per-call telemetry (model, provider, role, tokens, cost, latency, finish reason), with per-thesis SLO rollups on the API, and scheduled re-estimates costed separately from evidence-driven ones.
17. **Delivery.** One optional signed webhook on version approval (for example when the top-ranked candidate changes) or on thesis resolution (an acquisition is announced or the horizon ends), sent through the outbox.

## Quick start

Planned. There is no runnable code yet.

```bash
git clone https://github.com/zen-tradings/zen-fundamentals
cd zen-fundamentals && cp .env.example .env
docker compose up          # api + worker + postgres
curl -X POST localhost:8080/v1/theses -d @examples/who-buys-gridcompute.yaml
```

## Reference

Design lessons draw on [zen-tradings/internal-marketing-agent](https://github.com/zen-tradings/internal-marketing-agent): evidence tiers, role-split models, fail-closed gates, idempotent delivery, and offline eval.

## Status

Early design. RFCs in [`design/rfc/`](design/rfc/):

- [001](design/rfc/001-evidence-judgment-separation.md): shared evidence layer vs. per-thesis judgment layer
- [002](design/rfc/002-job-lifecycle-state-machine.md): separate lifecycles for evidence ingest, evaluation, version review, delivery, and replay
- [003](design/rfc/003-fencing-token-for-job-execution.md): fencing tokens for leased execution
- [004](design/rfc/004-thesis-and-thesis-version.md): Thesis and ThesisVersion model, feedback
- [005](design/rfc/005-reevaluation-loop-and-material-change-gate.md): re-evaluation loop, material-change gate, self-check, failure recovery
- [006](design/rfc/006-review-packet.md): ReviewPacket
- [007](design/rfc/007-replay-evaluation.md): replay evaluation
- [008](design/rfc/008-neocloud-deal-template.md): `neocloud_deal` template, outcome definitions, stake structure tags, rumor handling, reference prior
- [009](design/rfc/009-template-contract.md): template contract: what a template provides, core quantity types, two-stage validation, chaining

Core schemas in [`design/schemas/core/`](design/schemas/core/): [Thesis](design/schemas/core/thesis.schema.json), [ThesisVersion](design/schemas/core/thesis-version.schema.json), [EvidenceItem](design/schemas/core/evidence-item.schema.json), [ReviewPacket](design/schemas/core/review-packet.schema.json), [eval results row](design/schemas/core/eval-result-row.schema.json), [quantity types](design/schemas/core/quantity-types.schema.json).

Templates in [`design/templates/`](design/templates/): [`neocloud_deal`](design/templates/neocloud_deal/) (manifest, subject, values, params, baseline, eval spec and metrics).

Planned: OpenAPI spec, model capability profiles, replay dataset manifest and annotation guide, reference implementation.

## Open questions

- **Acquisitions are scarce.** Control acquisitions of neoclouds by AI labs or big tech are rare, and rarer still after recent model cutoffs. Acquisition metrics may rest on single-digit events, so stake events carry most of the calibration evidence. Widening the universe to all AI-infrastructure targets would help, at the cost of a less specific question.
- **Contamination and anonymization.** The universe is small, recent, and famous. Post-cutoff windows will be few, and an anonymized GPU cloud whose biggest customer is "a hyperscaler" may be re-identified almost every time. We will only know after the probes run on a built corpus.
- **News as evidence.** Private targets depend on news and reported talks. The archive-capture `as_of` rule is safe but may drop thinly archived trade coverage and bias the corpus toward famous targets.
- **Candidate coverage.** A thesis that leaves out the eventual acquirer can only put mass on `other`. Should the template suggest candidates from extracted relationships?
- **Stake edge cases.** Undisclosed ownership at private targets, the 90-day window that links equity to a commercial deal, and private targets that disclose too little to tag a stake's structure at all.
- **Provider as candidate.** Is a split report enough when a model's provider is also a candidate, or should those probabilities be excluded from headline rows?
- **Eval judge independence.** Should the eval-time citation judge come from a third provider, distinct from both the estimator and the auditor?

## License

Apache-2.0
