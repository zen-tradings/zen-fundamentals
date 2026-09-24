# RFC-008: `merger_arb` Template

Status: Discussion

Date: 2026-09-23

Depends on: RFC-004, RFC-005, RFC-006, RFC-007

## Problem

A thesis is only as good as the questions it tracks. If every user defined their own quantities, extraction targets, and thresholds, the result would be theses that can't be compared, evaluated, or reviewed consistently. Templates are maintained centrally so one replay evaluation (RFC-007) covers every thesis that uses them. This RFC defines the only template we ship: `merger_arb`.

## Template contract (all templates)

A template defines:

1. tracked quantities and their types;
2. required evidence types;
3. extraction targets, per document type;
4. the ReviewPacket layout;
5. default `material_change` thresholds.

It also defines dependency edges between quantities, deterministic impact rules, resolution-class evidence, routing constraints, and self-check tolerances.

Templates follow semver, and a thesis pins `{id, version}`:

- **major**: the quantity schema changes (requires a new thesis or an explicit migration);
- **minor**: extraction targets, prompts, or impact rules change;
- **patch**: threshold defaults or packet layout change.

A replay result is valid only for the template version it ran on.

> Trade-off: central templates give up per-user flexibility in exchange for comparability. Every `merger_arb` thesis is evaluated by the same RFC-007 run. A thesis can override thresholds and disable optional quantities, but it cannot add quantities.

## Subject

```yaml
subject:
  target:    { name, cik, ticker }          # required; US-listed SEC registrant
  acquirers: [{ name, cik?, ticker? }]      # private acquirers may lack CIK/ticker
  announcement: { as_of, accession? }       # earliest public announcement
  structure: merger | tender_offer | two_step   # optional hint; extracted if absent
```

## Outcome definitions

Every probability in this template is relative to three mutually exclusive, exhaustive outcomes **for this acquirer**:

| Outcome | Definition |
|---|---|
| `completed_as_announced` | The target is acquired by the named acquirer(s) with consideration type, per-share price, and exchange ratio unchanged from signing. A change of structure alone (merger → tender offer) doesn't count as a change. |
| `renegotiated` | The target is acquired by the named acquirer(s) with changed consideration type, per-share price, or exchange ratio (a bump, a cut, or a switch between cash and stock) |
| `terminated` | The agreement is terminated, or the target is acquired by a **different** acquirer (a topping bid wins) |

> Trade-off: counting a topping bid as `terminated` keeps the thesis about *this* deal, which is what the merger agreement's conditions describe. A holder of the target who is happy to be bought by anyone would see a "loss" where they actually made money. The `terminated` scenario's price estimate captures that: a topping bid shows up as a high terminated-scenario price.

## Tracked quantities

| Quantity | Type | Required | Definition |
|---|---|---|---|
| `scenarios` | `scenario_set` | yes | One entry per outcome: `{outcome, probability, target_price_per_share, price_rationale}`. Probabilities sum to 1. `target_price_per_share` is the estimated target share price once that outcome resolves: for completion, the consideration value per share at close; for termination, the estimated standalone price (or topping-bid price). |
| `close_probability` | `probability` (derived) | yes | `P(completed_as_announced) + P(renegotiated)`. Computed by code from `scenarios`, never estimated directly. Claim provenance is `computed`. |
| `expected_close_date` | `date` | yes | Point estimate of the closing date **conditional on completion**, with an optional 80% interval `{low, high}` |
| `conditions` | `condition_list` | yes | Each item: `{key, type, description, status, expected_by?}` where `type ∈ {regulatory, shareholder_vote, financing, other}` and `status ∈ {pending, satisfied, waived, failed, not_applicable}` |
| `key_terms` | `key_terms` | yes | `consideration {type: cash | stock | mixed | election, cash_per_share?, exchange_ratio?, collar?, cvr?}`, `price_per_share` (headline value at announcement), `currency`, `break_fee {target_termination_fee?, reverse_termination_fee?}`, `outside_date {initial, extensions[], current}` |

JSON shapes are in [`thesis-version.schema.json`](../schemas/thesis-version.schema.json) `$defs`.

> Trade-off: deriving `close_probability` from scenarios makes the headline number consistent with the scenario table by construction, and it forces the model to state *how* it expects the deal to close. Estimating three probabilities and two prices costs more tokens and gives the model more ways to go wrong than estimating one number. The self-check (RFC-005 step 8) and scenario metrics (RFC-007 §4) exist to catch that.

### Condition key vocabulary

Condition keys are canonical, so RFC-007 can compute recall by key.

| Key | Type |
|---|---|
| `regulatory:hsr` | regulatory |
| `regulatory:ec`, `regulatory:cma`, `regulatory:samr`, `regulatory:<iso-country>:<agency>` | regulatory |
| `regulatory:cfius` | regulatory |
| `regulatory:sector:<agency>` (FCC, FERC, state PUC, state insurance, banking regulators) | regulatory |
| `vote:target_shareholders`, `vote:acquirer_shareholders` | shareholder_vote |
| `tender:minimum_condition` | other |
| `financing:debt`, `financing:equity` (only where the agreement makes financing a condition; otherwise financing risk appears as an investor judgment item) | financing |
| `other:s4_effective`, `other:listing`, `other:no_injunction`, `other:mae`, `other:<slug>` | other |

## Dependency edges

```
conditions ──▶ scenarios ──▶ close_probability (derived)
conditions ──▶ expected_close_date
key_terms  ──▶ scenarios   (price under completion outcomes)
```

If a quantity is affected (RFC-005 step 5), every quantity downstream of it is marked affected too.

## Sources and tiers

| Source | Tier | Content |
|---|---|---|
| SEC EDGAR | primary | Filings by target and acquirer CIKs: `8-K`, `8-K/A`, `S-4`, `S-4/A`, `DEFM14A`, `PREM14A`, `425`, `SC TO-T`, `SC TO-T/A`, `SC 14D9` (plus exhibits, notably EX-2.1 merger agreement, EX-99.1 press releases). `as_of` = acceptance datetime. |
| Company press releases | primary | Target and acquirer IR pages or wire services. `as_of` = wire timestamp; a date-only timestamp becomes 23:59:59 in the publisher's timezone. |
| Web search | secondary | News and commentary. `as_of` = publication date if reliable, else `retrieved_at`. Disabled in replay (RFC-007 §1.4). |
| Market data | primary (for prices only) | Daily closes for target, acquirer(s), and the configured market proxy ticker; the 3-month T-bill yield. `as_of` = session close. Used **only** for the market-implied probability; never given to the estimator. |

Planned primary sources: regulator releases (FTC/DOJ early termination and complaints, EC case register, CMA case pages).

## Required evidence

- **Initial version** requires an announcement document (8-K Item 1.01 or announcement press release) **and** the merger agreement (EX-2.1), or the offer document for tender offers. Without them the job ends in `needs_input` ("merger agreement not found; supply accession or wait").
- `policy.min_primary_sources` defaults to 1 per changed quantity.

## Extraction targets

Extraction runs document-locally and is shared across theses (RFC-001), on the low-cost extractor route.

| Document | Targets |
|---|---|
| 8-K Item 1.01 / EX-2.1 merger agreement | `key_terms.*` (consideration, price, collar, CVR), `break_fee.*`, `outside_date.*` (with extension mechanics), closing-conditions article → `conditions[]`, regulatory efforts covenant (hell-or-high-water or not; divestiture caps) |
| PREM14A / DEFM14A | `conditions[]` with status, regulatory filing dates and status, expected timing statements, meeting date, background of the merger (competing bidders, leak dates) |
| S-4 / S-4/A | same as proxy, plus exchange ratio mechanics and effectiveness |
| 425 | timing statements, regulatory updates, integration statements that imply timing |
| SC TO-T / SC TO-T/A | offer price, minimum condition, other offer conditions, expiration and extensions, tendered-share counts |
| SC 14D9 | board recommendation, background, appraisal rights |
| 8-K Item 8.01 / 7.01 | regulatory milestones (second request, clearances, suits) |
| 8-K Item 5.07 | vote results → `vote:*` status |
| 8-K Item 1.02 | termination → resolution-class |
| 8-K Item 2.01 | completion → resolution-class |
| Press releases | the same regulatory, timing, amendment, and resolution facts as the 8-K items |

## Deterministic impact rules

These rules are applied before the planner, and they can only add affected quantities (RFC-005 step 5). Examples:

| Evidence | Affected |
|---|---|
| Any document amending the merger agreement (8-K Item 1.01 with "Amendment") | `key_terms`, `scenarios`, `conditions` |
| Text matching second request, Phase II, Phase 2, CFIUS investigation, complaint, injunction | `conditions`, `scenarios`, `expected_close_date` |
| 8-K Item 5.07 | `conditions`, `scenarios` |
| SC TO-T/A extending expiration | `expected_close_date` |
| 8-K Item 1.02 / 2.01 | all (resolution-class; always material; skips debounce) |

## Default material-change thresholds

These are **starting points**, to be tuned on replay (RFC-007). They are not validated values.

```yaml
material_change:
  scenarios:           { prob_abs: 0.05, price_rel: 0.05 }
  close_probability:   { abs: 0.05 }                 # applies to derived value
  expected_close_date: { days: 14 }
  conditions:          { on: [added, removed, status_changed] }
  key_terms:           { on: any }
market_gap_flag: 0.15   # |agent − market| above this → investor judgment item
```

## Routing

| Role | Work | Model constraint |
|---|---|---|
| planner | impact mapping, needs_input questions | strongest available model |
| estimator | re-estimate scenarios/date/conditions, reconcile conflicts, self-check review pass | strongest available model (same route as planner by default) |
| extractor | terms and conditions from filings | low-cost model |
| auditor | citation support, provenance labels, stated-date checks | low-cost model **from a different provider than the estimator** |

```yaml
routing:                                   # capability tiers resolved at runtime (README §Dynamic model routing)
  planner:   { tier: strongest }
  estimator: { tier: strongest, same_route_as: planner }
  extractor: { tier: low_cost, schema_strict: true }
  auditor:   { tier: low_cost, provider_must_differ_from: estimator }
  alternates:                              # RFC-005 failure recovery
    extractor: { tier: low_cost, provider_must_differ_from: extractor }
    auditor:   { tier: low_cost, provider_must_differ_from: estimator }
```

Constraints are enforced fail-closed. If no route satisfies `provider_must_differ_from`, the job is held rather than falling back to the same provider. Per-lane tool allowlists:

- planner: evidence read (PIT view) and discovery requests;
- extractor: document read only;
- estimator: EvidenceMatrix and extractions only, no fetch or search;
- auditor: evidence read (PIT view) only.

> Trade-off: putting the strongest model on the planner and estimator concentrates cost where judgment happens. Extraction is high-volume and checkable, so a cheap model is enough there. RFC-007 ablation A1 tests whether the strong estimator earns its cost. Provider diversity for the auditor is argued in RFC-006.

## Market-implied probability

This is computed by code at every evaluation's `clock`, stored in `ThesisVersion.market_implied` and `EvaluationRecord.market_implied`, and shown next to the agent's `close_probability` in the ReviewPacket. It is also baseline B1 in RFC-007.

**Formula (version `mi-1`).**

```
p_t = (S_t − D_t) / (V_t − D_t)            clipped to [0, 1]

S_t = target close at the latest session with as_of ≤ clock
V_t = PV of consideration per share
    = (cash_per_share + exchange_ratio_eff × A_t) / (1 + r_t)^τ_t
D_t = downside (standalone) price if the deal breaks
    = S_u × (M_t / M_u)
```

where:

- `A_t` = acquirer close at the same session; `exchange_ratio_eff` applies any collar at `A_t`;
- `S_u`, `M_u` = target close and market-proxy close on the point-in-time `unaffected_date` (the last session before announcement); `M_t` = market-proxy close at `t`;
- `r_t` = 3-month T-bill yield (annualized) with `as_of ≤ clock`;
- `τ_t` = years from `t` to `announcement + median_duration_ref`, floored at 10 trading days. `median_duration_ref` is the RFC-007 reference set's median announcement-to-close duration.

**Assumptions** (all shown in the packet):

1. Binary outcome: close at `V` or break to `D`. This ignores renegotiation and topping bids, so a target trading above `V_t` is clipped to `p = 1` and flagged `trading_through`.
2. Risk-neutral pricing. No risk premium for deal risk, so `p` understates the true physical probability when arbitrage capital demands compensation.
3. Downside moves one-for-one with the market proxy since the unaffected date (β = 1). Sector moves and the target's own news are ignored.
4. Time value uses a reference-set duration, **not** the agent's `expected_close_date`, so the baseline stays independent of the agent.
5. Dividends, stock borrow cost, and financing costs are ignored. CVRs are valued at 0. Election deals use the stated proration mix.
6. If `V_t − D_t ≤ 0.01 × V_t` (almost no premium), `p` is undefined: reported `null` with reason `degenerate_spread`.

> Trade-off: `mi-1` is deliberately the simple textbook spread formula. It is transparent and reproducible from public closes, and its known biases (assumptions 2 and 3) point in documented directions. A richer model (option-implied, sector-β downside) could make a stronger baseline, but it would also add fitted parameters that could themselves leak hindsight.

## ReviewPacket layout

Sections in order:

1. Header, audit status, degradations
2. Scenario table (old → new probability and price per outcome), derived `close_probability`, market-implied comparison
3. Conditions: added, removed, and status changes, then unchanged conditions collapsed
4. Expected close date: old → new, interval, drivers
5. Key terms: changed fields only, then full terms collapsed
6. Conflicts
7. Uncertain items
8. Investor judgment items
9. Self-check and recoveries
10. Evidence appendix

**Standard investor-judgment prompts.** The estimator raises these when they apply:

- Will the acquirer accept remedies beyond the agreement's divestiture cap (or a hell-or-high-water covenant)?
- Is a political or national-security objection likely to become formal action?
- Is a topping bid plausible given the background-of-the-merger disclosures?
- Is financing at risk in the current credit market (when financing is not a formal condition)?
- The agent's close probability and the market-implied probability disagree by more than `market_gap_flag`. Which view do you hold?

## Self-check tolerances

| Check | Tolerance |
|---|---|
| Σ scenario probabilities | 1e-6 |
| Headline price vs. consideration | 0.5% of price, or 0.01 in currency units |
| Completed-scenario price vs. consideration value at reference price | 2% (allows for collars and CVR disagreement) |
| Derived close probability | exact (computed) |

## Open questions

- A market data source for daily closes that is free, redistributable, and stable enough for a rebuildable dataset. Without one, B1 cannot be reproduced exactly by third parties.
- Should `renegotiated` be split into `bumped` and `cut`? They have opposite price implications, and grouping them loses information in the scenario Brier.
- Two-step deals (tender then merger): one `expected_close_date` (the merger) or two?
