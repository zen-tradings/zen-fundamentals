# RFC-008: `neocloud_deal` Template

Status: Discussion

Date: 2026-09-24 (replaces the `merger_arb` draft of 2026-09-23)

Depends on: RFC-004, RFC-005, RFC-006, RFC-007

## Problem

A thesis is only as good as the questions it tracks. If every user defined their own quantities, extraction targets, and thresholds, the result would be theses that can't be compared, evaluated, or reviewed consistently. Templates are maintained centrally so one replay evaluation (RFC-007) covers every thesis that uses them. This RFC defines the only template we ship: `neocloud_deal`.

The question it answers: **for one neocloud (a company whose main business is renting GPU or accelerator compute, or building AI-dedicated data-center capacity), who is likely to acquire it or take a strategic equity stake in it within a fixed horizon, and how likely is each?** Candidates are AI labs (Anthropic, OpenAI, …), hyperscalers, chipmakers, and other neoclouds.

This is a **pre-announcement** template. Nothing has been signed when the thesis starts, most theses resolve to "nothing happened", and the evidence is indirect: compute contracts, customer concentration, ownership tables, financing, and reported talks.

## Template contract (all templates)

A template defines:

1. tracked quantities and their types;
2. required evidence types;
3. extraction targets, per document type;
4. the ReviewPacket layout;
5. default `material_change` thresholds.

It also defines dependency edges between quantities, deterministic impact rules, resolution-class evidence, the scheduled re-estimate cadence, routing constraints, and self-check tolerances.

Templates follow semver, and a thesis pins `{id, version}`:

- **major**: the quantity schema or the outcome definitions change (requires a new thesis or an explicit migration);
- **minor**: extraction targets, prompts, impact rules, or the reference-prior weights change;
- **patch**: threshold defaults or packet layout change.

A replay result is valid only for the template version it ran on.

> Trade-off: central templates give up per-user flexibility in exchange for comparability. Every `neocloud_deal` thesis is evaluated by the same RFC-007 run. A thesis can override thresholds, choose its candidates, and set its horizon, but it cannot add quantities or change the outcome definitions.

## Subject

```yaml
subject:
  target:
    name: "GridCompute Inc."
    listing: private | ipo_filed | public   # at thesis creation; tracked afterwards in target_facts
    cik: "0000000001"                        # if an SEC registrant or Form D filer
    ticker: GRDC                             # if listed
  candidates:                                # 1..12 named candidates; everyone else is "other"
    - { key: anthropic, name: "Anthropic PBC", type: ai_lab }
    - { key: openai,    name: "OpenAI",        type: ai_lab }
    - { key: microsoft, name: "Microsoft Corp.", ticker: MSFT, type: hyperscaler }
    - { key: nvidia,    name: "NVIDIA Corp.",    ticker: NVDA, type: chipmaker }
  horizon:
    start: "2026-10-01T00:00:00Z"            # thesis clock at creation
    end:   "2027-09-30"                      # default start + 12 months; max 24 months
```

`candidate.type ∈ {ai_lab, hyperscaler, chipmaker, neocloud, other}`. Candidate keys are slugs used in quantity keys and condition-style vocabularies below. `other` and `none` are reserved keys.

Adding or removing a candidate is a spec revision (RFC-004). The horizon cannot be changed after creation; a new horizon is a new thesis.

> Trade-off: a fixed horizon makes every thesis resolve on a known date, which is what RFC-007 needs to score it. A rolling "within 12 months of now" horizon would be more natural to read, but it never resolves, and its probabilities at different clocks answer different questions.

## Outcome definitions

Two kinds of event are tracked, both within `[horizon.start, horizon.end]`.

### Acquisition

An **acquisition** is the public announcement of a definitive agreement under which one party acquires **control** of the target: more than 50% of its voting power, or all or substantially all of its equity or operating assets. The form can be a merger, tender offer, share purchase, or asset purchase. A merger of two neoclouds counts, with the counterparty as the acquirer. A bankruptcy §363 sale of substantially all assets counts.

- The event is the **signing announcement**, not the closing. An agreement that is later terminated still counts as an acquisition event on its announcement date.
- Letters of intent, reported talks, and exclusivity agreements do not count.
- Only the **first** acquisition announced in the horizon counts. A later topping bid does not change the outcome.

`acquirer_distribution` is a distribution over mutually exclusive outcomes: each candidate key, `other` (any non-candidate acquirer, including private equity), and `none` (no acquisition in the horizon).

### Equity stake

An **equity stake** event for candidate `c` is the announcement or disclosure that `c` (or an entity it controls) has acquired, or agreed to acquire, equity in the target such that either:

1. `c`'s disclosed beneficial ownership **crosses** `stake_min_pct` (default 5%, matching the SC 13D/13G threshold), counting warrants and convertibles exercisable within 60 days; or
2. a single new investment by `c` is at least `stake_min_usd` (default US$1bn), whatever the resulting ownership.

Debt, prepayments for compute, and commercial contracts without an equity component do not count. An acquisition by `c` also counts as a stake event for `c`.

**Warrants and milestone equity.** Warrants or options that vest with commercial milestones (for example capacity delivered, or spend under a compute contract) count toward the thresholds only once they are vested or exercisable within 60 days, the same rule as SC 13D/13G beneficial ownership. The stake event date is the disclosure of the vesting that makes the holding cross, not the signing of the contract that granted the warrants.

Stake events are **not** mutually exclusive across candidates. `stake_probabilities` holds one independent probability per candidate.

> Trade-off: counting equity stakes gives the eval far more positive events than acquisitions alone, and a large strategic stake is often the step before, or the substitute for, an acquisition. The cost is a second definition with its own edge cases (undisclosed ownership percentages at private targets, equity that is really part of a commercial deal). The thresholds are stated in the manifest, and the structure tags below handle the commercial cases.

### Stake structure

Much of the equity in this sector is not a pure strategic bet. A chipmaker invests in a neocloud that spends the money on the chipmaker's accelerators. An AI lab receives warrants as part of a compute contract. An investor agrees to buy any capacity the target can't sell. These deals are hard to classify by intent, and they are probably a much weaker signal of a coming acquisition than pure equity.

The template keeps the **event** rule mechanical: equity that crosses a threshold is a stake event, whatever its motive. Every stake event, and every `equity` or `debt` relationship, also carries a **structure tag** that records the commercial context. Tags describe the deal; they never decide whether an event happened.

| Tag | Applies when (all from primary sources) |
|---|---|
| `vendor_financing` | The investor or lender is a **supplier** to the target (`gpu_supply` or another supply relationship), and the financing is disclosed as funding purchases from the investor, is conditioned on such purchases, or is announced within 90 days of a supply agreement between the two |
| `capacity_backstop` | The investor commits to buy the target's unsold or unused capacity (a contingent-customer commitment), in the same agreement as the equity or within 90 days of it |
| `customer_equity_kicker` | The investor is a **customer** (`compute_contract`) and receives equity, warrants, or options as part of, or within 90 days of, the compute contract |
| `pure_equity` (`arms_length` for debt) | None of the above: no commercial agreement between the two is linked to the investment or falls within 90 days of it |
| `undetermined` | Primary sources don't say enough to decide (common at private targets). Secondary reports may be cited in the rationale, but can't set a tag. |

When several tags apply, `structure` is the first match in the order above (vendor financing, then backstop, then customer kicker), and `structure_flags` lists every tag that applies. A chipmaker that supplies accelerators **and** backstops capacity is tagged `vendor_financing`, with flags `[vendor_financing, capacity_backstop]`.

Each tagged item lists `linked_relationships`: the supply, compute-contract, or backstop relationship keys that justify the tag. The self-check requires the link (see *Self-check tolerances*).

> Trade-off: putting the judgment into a tag instead of the event definition keeps outcomes objective and rebuildable, and it keeps the few positive events in one pool. The cost is that `stake_probabilities` answers "will they put in equity?", not "will they make a strategic bet?". A user who cares only about strategic bets reads the tag and the split results in RFC-007 §4. The alternative, a separate `strategic_financing` event type, would have made whether an event happened depend on judging intent.

### Resolution

| Event | Effect |
|---|---|
| Acquisition announced (any acquirer) | Thesis resolves. `acquirer_distribution` outcome = the acquirer's key, or `other`. Every candidate's stake outcome is fixed at that point (the acquirer's stake outcome is 1). |
| Stake event for candidate `c` | **Partial resolution.** `stake_probabilities[c]` is fixed at 1 (a `computed` value, never estimated again), with its structure tag. The thesis keeps running. |
| `horizon.end` reached | Thesis resolves with acquisition outcome `none`. Unresolved stake outcomes are 0. |
| Target ceases operations or is liquidated without a control transaction | Thesis resolves with outcome `none`, reason `target_ceased`. |

All of these are resolution-class evidence: always material, and they skip the debounce (RFC-005).

## Tracked quantities

| Quantity | Type | Required | Definition |
|---|---|---|---|
| `acquirer_distribution` | `candidate_distribution` | yes | One entry per candidate key plus `other` and `none`: `{key, probability, rationale}`. Probabilities sum to 1. |
| `p_acquired` | `probability` (derived) | yes | `1 − P(none)`. Computed by code from `acquirer_distribution`, never estimated directly. Claim provenance is `computed`. |
| `stake_probabilities` | `probability_map` | yes | One entry per candidate: `{key, probability, resolved, structure?, rationale}`. Independent probabilities; they do not sum to 1. `structure` is set when resolved. |
| `expected_announcement_date` | `date` | yes | Point estimate of the acquisition announcement date **conditional on an acquisition happening in the horizon**, with an optional 80% interval `{low, high}`. Must lie in `[clock, horizon.end]`. |
| `relationships` | `relationship_list` | yes | Disclosed ties between the target and each candidate. Each item: `{key, candidate, type, role, status, value?, term?, ownership_pct?, structure?, structure_flags?, linked_relationships?, first_disclosed_as_of}`. `structure` is required on `equity` and `debt` items. |
| `signals` | `signal_list` | yes | Canonical deal-relevant signals. Each item: `{key, description, status, direction, candidates[], basis}`. |
| `target_facts` | `target_facts` | yes | `listing {status, exchange?, ticker?}`, `control {voting_control_holder?, dual_class, change_of_control_provisions[]}`, `capital {last_valuation?, total_debt?, contracted_backlog?}`, `capacity {power_mw?, accelerators?}`, `customer_concentration {top_customer?, top_customer_share?}` |

JSON shapes are in [`thesis-version.schema.json`](../schemas/thesis-version.schema.json) `$defs`.

> Trade-off: deriving `p_acquired` from the distribution keeps the headline consistent with the per-candidate table by construction, and forces the model to say *who* it thinks buys. Spreading probability over up to 14 outcomes gives the model more ways to be wrong than one number, and most of the mass sits on `none`. The self-check and the ranking metrics in RFC-007 §4 exist to catch that.

### Relationship vocabulary

Relationship keys are canonical, `<type>:<candidate>[:<slug>]`, so RFC-007 can compute recall by key.

| `type` | `role` of candidate | Examples |
|---|---|---|
| `compute_contract` | `customer` | multi-year capacity agreement; `value` = total contract value, `term` = years |
| `gpu_supply` | `supplier` | accelerator supply or allocation agreement |
| `equity` | `investor` | existing stake, warrants, convertibles; `ownership_pct` when disclosed; always carries a structure tag |
| `debt` | `lender` | credit facility, GPU-backed financing; always carries a structure tag (`vendor_financing` when the lender is a supplier) |
| `capacity_backstop` | `customer` | commitment to buy the target's unsold or unused capacity |
| `board` | `investor` | board seat or observer right |
| `partnership` | `partner` | co-development, reseller, joint venture |
| `other:<slug>` | any | anything else material |

`status ∈ {announced, active, expired, terminated}`.

### Signal vocabulary

| Key | Direction (typical) | Basis (typical) |
|---|---|---|
| `strategic_review` | raises | primary: target says it is exploring strategic alternatives or has hired an advisor |
| `talks:<candidate>` | raises | secondary: reported discussions with a candidate |
| `talks_denied:<candidate>` | lowers | either |
| `concentration:<candidate>` | raises | primary: candidate is ≥ 20% of revenue or backlog |
| `financing:equity_round` | ambiguous | primary (Form D, press release) or secondary |
| `financing:debt` | ambiguous | primary |
| `financing:stress` | raises | primary: covenant waiver, going-concern language, missed payment |
| `ipo:filed`, `ipo:priced`, `ipo:withdrawn` | ambiguous | primary |
| `candidate:own_capacity:<candidate>` | lowers | primary: candidate announces large self-built capacity |
| `candidate:capex_up:<candidate>` | ambiguous | primary: candidate raises capex guidance |
| `control:founder_lock` | lowers | primary: dual-class or founder voting control |
| `regulatory:antitrust:<candidate>` | lowers | primary: regulator inquiry into the candidate's AI partnerships or acquisitions |
| `regulatory:foreign_ownership` | lowers | primary: CFIUS or equivalent sensitivity |
| `regulatory:export_control` | ambiguous | primary |
| `leadership:change` | ambiguous | primary |
| `other:<slug>` | any | any |

`status ∈ {present, resolved, contradicted}`. `basis ∈ {primary, secondary_only}`. A signal whose only support is secondary evidence is always `secondary_only`, whatever its key.

## Dependency edges

```
relationships ──┐
signals ────────┼──▶ acquirer_distribution ──▶ p_acquired (derived)
target_facts ───┤                          └─▶ expected_announcement_date
                └──▶ stake_probabilities
signals ─────────────▶ expected_announcement_date
```

If a quantity is affected (RFC-005 step 5), every quantity downstream of it is marked affected too.

## Sources and tiers

| Source | Tier | Content |
|---|---|---|
| SEC EDGAR | primary | Filings by the target and candidate CIKs: `8-K`, `10-K`, `10-Q`, `S-1`, `S-1/A`, `F-1`, `424B*`, `SC 13D`, `SC 13G` (and amendments), `D`, `DEF 14A`, `20-F`, `6-K`. Candidate `10-K`/`10-Q` filings are routed to a thesis only if they mention the target (entity link, RFC-005 step 2). `as_of` = acceptance datetime. |
| Company press releases | primary | Target and candidate IR pages or wire services. `as_of` = wire timestamp; a date-only timestamp becomes 23:59:59 in the publisher's timezone. |
| News (named outlets) | secondary | A configured outlet list, each with a `reliability` (`high` / `normal`). `as_of` = the later of the stated publication time and the first archive capture (RFC-007 §1.4). Used in live **and** replay. |
| Web search | secondary | Open web. `as_of` = publication date if reliable, else `retrieved_at`. Live only; disabled in replay. |

Planned primary sources: regulator publications (FTC, DOJ, CMA, EC statements and market studies on AI partnerships), state utility and interconnection filings (power capacity).

There is no market-data source in this template. Prices do not give a clean pre-announcement probability; see *Reference prior*.

**Public information only.** Every adapter reads public or licensed sources. Licensed sources sit in tenant partitions (RFC-001). The template has no path for material non-public information, and a thesis owner must not supply it through `needs_input` answers.

> Trade-off: many neoclouds are private, so their primary-source trail is thin (a Form D, a few press releases) and the deal-relevant news is secondary. Unlike a post-announcement template, this one cannot work from primary sources alone, so named-outlet news is enabled in replay too, under a stricter `as_of` rule. Changes driven only by secondary evidence are always flagged (see *Rumor handling*).

## Required evidence

- The **initial version** requires at least one primary-source document about the target with `as_of ≤ clock` that establishes its identity and listing status (for example an S-1, a 10-K, a Form D, or a target press release). Without one, the job ends in `needs_input` ("no primary source for target; supply a document or confirm the entity").
- For each candidate, the initial version records whether any relationship evidence was found. "None found" is a valid, cited-by-absence state, and the packet shows it.
- `policy.min_primary_sources` defaults to 1 per changed quantity, except as described under *Rumor handling*.

## Rumor handling

Reported talks are often the earliest signal of a deal, and they are almost always secondary. The template lets them move estimates, but never silently:

- A changed quantity whose supporting claims cite only secondary evidence is flagged `uncertain` (`reason: secondary_only`) by a deterministic audit check. That check fails the packet (`audit: failed`, RFC-006), so approving it needs an explicit `override_reason`. A human therefore always signs off on a rumor-driven move.
- The estimator must raise an investor-judgment item for every `talks:*` signal it relies on: "Is this report credible?", with the outlet, its reliability, and any denial.
- `talks_denied:*` does not cancel `talks:*`. Both stay in `signals`, and the estimator reconciles them as a conflict (RFC-006).

> Trade-off: requiring an override for every rumor-driven change adds review friction exactly when things get interesting. The alternative, letting a low-cost auditor pass rumor-driven estimates on its own, would put unverifiable claims into the approved head with no human decision behind them.

## Extraction targets

Extraction runs document-locally and is shared across theses (RFC-001), on the low-cost extractor route.

| Document | Targets |
|---|---|
| Target S-1 / F-1 / 10-K / 20-F / 10-Q | customers and concentration, contracted backlog, material contracts (EX-10) and counterparties, capacity (MW, accelerators), debt facilities and change-of-control provisions, principal stockholders table, voting control and dual-class structure, related-party transactions; for each investor or lender that is also a supplier or customer: warrant and vesting terms, use-of-proceeds or purchase conditions, capacity backstop commitments (inputs to the structure tag) |
| Candidate 10-K / 10-Q | passages mentioning the target: purchase commitments, investments, equity-method holdings, financing; capex guidance; statements about self-built capacity |
| SC 13D / SC 13G (and amendments) | filer, ownership %, date of event; for 13D, Item 4 purpose (plans regarding control, merger, board) |
| Form D | issuer, amount sold, date of first sale, investor count → `financing:equity_round` |
| 8-K Item 1.01 | material agreements: compute contracts, credit facilities, merger agreements (resolution-class) |
| 8-K Items 2.01, 3.02, 5.02 | completed acquisitions, unregistered equity sales, leadership changes |
| DEF 14A | ownership table, board composition |
| Press releases | contracts, investments, capacity, financing, strategic review, acquisition announcements |
| News | reported talks, denials, reported valuations, reported investments → `signals` and `uncertain` claims only |

## Deterministic impact rules

These rules are applied before the planner, and they can only add affected quantities (RFC-005 step 5). Examples:

| Evidence | Affected |
|---|---|
| Acquisition agreement or announcement naming the target (8-K Item 1.01 with "Agreement and Plan of Merger", or a press release "to acquire") | all (resolution-class) |
| SC 13D / SC 13G by a candidate on the target, or a primary disclosure of a candidate investment | `relationships`, `stake_probabilities`, `acquirer_distribution` (resolution-class for that candidate's stake if the threshold is met) |
| SC 13D Item 4 mentioning control, merger, acquisition, or board | `signals`, `acquirer_distribution` |
| Text matching "strategic alternatives", "exploring a sale", "financial advisor" | `signals`, `acquirer_distribution`, `expected_announcement_date` |
| S-1 filing, IPO pricing, or IPO withdrawal | `target_facts`, `signals`, `acquirer_distribution` |
| 8-K Item 1.01 compute contract with a candidate | `relationships`, `acquirer_distribution`, `stake_probabilities` |
| A supply, compute, or backstop agreement with a candidate within 90 days of that candidate's equity or debt (either order) | `relationships` (the structure tag may change), `acquirer_distribution`, `stake_probabilities` |
| Disclosure that milestone warrants vested | `relationships`, `stake_probabilities` (resolution-class for that candidate's stake if the threshold is met) |
| News naming the target and a candidate with "talks", "in discussions", "weighing", "nearing a deal" | `signals`, `acquirer_distribution`, `stake_probabilities` |
| Scheduled re-estimate | `acquirer_distribution`, `stake_probabilities`, `expected_announcement_date` |

## Scheduled re-estimate

Probabilities over a fixed horizon should fall as the horizon runs out with nothing happening. So this template requires a **scheduled re-estimate**: if no evaluation has run for `reestimate_days` (default 30), an evaluation runs with `trigger: scheduled`, `clock` = the scheduled time, and no new evidence. It re-estimates the time-sensitive quantities listed in the impact rules. A scheduled evaluation goes through the same gate as any other, so most end as `below_threshold` records. Its changes are justified by a `computed` elapsed-time claim plus the evidence the head already cited (RFC-005 step 8), since there is no new evidence to cite. (This is unrelated to the worker lease heartbeat in RFC-003.)

> Trade-off: a scheduled re-estimate costs one estimator call per thesis per month with no new information. Without it, the approved head would keep a 12-month probability unchanged until month 11, and RFC-007 would score that stale number at every checkpoint.

## Budget degrade order

Under budget or latency pressure (RFC-005): drop `low`-reliability secondary evidence → skip dependency-only re-estimates → drop `normal`-reliability news not behind a `talks:*` signal the head relies on → hold the job. `high`-reliability news is never dropped.

## Default material-change thresholds

Base rates are low, so absolute probability thresholds either page on noise near 0.5 or never page near 0.02. This template uses a **log-odds** threshold with an absolute floor. A probability is material if `|logit(new) − logit(head)| ≥ logit_abs` **and** `|new − head| ≥ prob_abs_min`. `logit_abs: 0.7` is roughly a doubling or halving of the odds.

These are **starting points**, to be tuned on replay (RFC-007). They are not validated values.

```yaml
material_change:
  acquirer_distribution:      { logit_abs: 0.7, prob_abs_min: 0.02, on_top_rank_change: true }  # per key, incl. other and none
  p_acquired:                 { logit_abs: 0.7, prob_abs_min: 0.02 }
  stake_probabilities:        { logit_abs: 0.7, prob_abs_min: 0.02 }
  expected_announcement_date: { days: 45 }
  relationships:              { on: [added, removed, status_changed, value_changed, structure_changed] }
  signals:                    { on: [added, status_changed] }
  target_facts:               { on: [listing, control, customer_concentration] }
prior_gap_flag: 3.0      # odds ratio between agent and reference prior on p_acquired, or a different top candidate
stake_min_pct: 0.05
stake_min_usd: 1000000000
reestimate_days: 30
```

`on_top_rank_change`: a change in which candidate (excluding `none`) has the highest probability is material, even when no single probability crosses the threshold.

## Routing

| Role | Work | Model constraint |
|---|---|---|
| planner | impact mapping, needs_input questions | strongest available model |
| estimator | re-estimate distributions, date, and signals; reconcile conflicts; self-check review pass | strongest available model (same route as planner by default) |
| extractor | contracts, ownership, financing, and capacity facts from filings and releases | low-cost model |
| auditor | citation support, provenance labels, stated-date checks | low-cost model **from a different provider than the estimator** |

```yaml
routing:                                   # capability tiers resolved at runtime (README §Role-based model routing)
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

**Conflict of interest.** Several candidates in this template are model providers. Routing records the provider of every role, and the ReviewPacket header shows a `provider_is_candidate` flag whenever a role's provider is also a named candidate in the thesis. It does not block the route. RFC-007 reports results split by that flag.

> Trade-off: putting the strongest model on the planner and estimator concentrates cost where judgment happens. Extraction is high-volume and checkable, so a cheap model is enough there. RFC-007 ablation A1 tests whether the strong estimator earns its cost. Provider diversity for the auditor is argued in RFC-006. Flagging rather than blocking provider-candidate overlap keeps the strongest models available, and the split results show whether the overlap biases anything.

## Reference prior

Before an announcement there is no deal spread to back out a market-implied probability from. The comparison figure is instead a **reference prior**: a transparent, rule-based estimate of what a practitioner's default heuristic ("the biggest customer or investor is the likeliest buyer") would say.

It is computed by code at every evaluation's `clock`, stored in `ThesisVersion.reference_prior` and `EvaluationRecord.reference_prior`, and shown next to the agent's estimates in the ReviewPacket. It is also baseline B1 in RFC-007. It is **not** a tracked quantity, never triggers the gate, and is never shown to the estimator.

**Inputs.** Only shared, document-local **extractions** (RFC-001) with `as_of ≤ clock`, never the estimator's `relationships` quantity. The prior therefore stays independent of the agent's judgment. It still depends on the extractor, which RFC-007 isolates with an oracle variant.

**Formula (version `rp-1`).**

```
T        = years from clock to horizon.end
P_acq    = 1 − (1 − b_listing)^T                  b_listing: annual acquisition rate, reference set, by listing status
w_k      = 1 + Σ weights of k's active relationships and signals (table below)
w_other  = constant, fit on the reference set
P(k)     = P_acq × w_k / (Σ_candidates w + w_other)
P(other) = P_acq × w_other / (Σ_candidates w + w_other)
P(none)  = 1 − P_acq

s_k      = 1 − (1 − min(1, b_stake(type_k) × m_k))^T   b_stake: annual stake rate by candidate type; m_k: multiplier
s_k      = max(s_k, P(k))                          an acquisition by k is also a stake event
```

| Relationship or signal (extracted, active at `clock`) | `w_k` weight | `m_k` multiplier |
|---|---|---|
| `equity`, `pure_equity` or `undetermined`, ownership ≥ 5% | 4 | 3 |
| `equity`, `pure_equity` or `undetermined`, smaller or undisclosed | 2 | 2 |
| `equity`, `vendor_financing`, `capacity_backstop`, or `customer_equity_kicker` (any size) | 1.5 | 2 |
| `concentration:k` (≥ 20% of revenue or backlog) | 3 | 2 |
| other `compute_contract` or `capacity_backstop` | 1 | 1.5 |
| `gpu_supply` or `debt` | 0.5 | 1.5 |
| `strategic_review` (applies to every candidate) | ×1.5 on `b_listing` | — |

The prior computes structure tags itself, from extractions, using the rules in *Stake structure*. The supplier and customer links and the 90-day window are mechanical; the use-of-proceeds and purchase conditions are extraction targets. It never reads the estimator's tags.

**The weight values above are placeholders.** They are fit once on the RFC-007 reference set (never on the eval set), published with the template's minor version, and frozen for the run.

**Assumptions** (all shown in the packet):

1. Acquisition timing is a constant hazard over the horizon. Real deal timing clusters around financing and IPO events.
2. A candidate's pull is additive in its relationships. Real relationships interact (a large customer that is also an investor is more than the sum).
3. `other` has a fixed weight, so the prior can't represent a target that is plainly headed for a financial buyer.
4. Secondary evidence (reported talks) is ignored entirely.

> Trade-off: `rp-1` is deliberately crude. It is reproducible from shared extractions and a published weight table, so anyone can check it, and it encodes the one heuristic a skeptic would propose first. An agent that can't beat it isn't worth running. A fitted model (logistic regression on relationship features) would be a stronger baseline, but it would need more labeled cases than the dataset has.

## ReviewPacket layout

Sections in order:

1. Header, audit status, degradations, `provider_is_candidate` flags
2. Acquirer table: per key (candidates, `other`, `none`), old → new probability, rank, and reference prior; derived `p_acquired` beneath
3. Stake table: per candidate, old → new probability, resolved flag and structure tag, reference prior
4. Signals: added and status changes, then unchanged signals collapsed; `secondary_only` signals marked
5. Relationships: added, removed, and changed (including structure-tag changes, with the linked relationships), then unchanged collapsed; candidates with no relationship found are listed explicitly
6. Expected announcement date: old → new, interval, drivers, days left in the horizon
7. Target facts: changed fields only, then full facts collapsed
8. Conflicts
9. Uncertain items (including every `secondary_only` change)
10. Investor judgment items
11. Self-check and recoveries
12. Evidence appendix

**Standard investor-judgment prompts.** The estimator raises these when they apply:

- Is this candidate more likely to keep buying capacity by contract than to buy the company?
- Would antitrust or foreign-investment review plausibly block this candidate from acquiring a key supplier or customer?
- Does founder or dual-class control make a sale unlikely at any price?
- Is a reported-talks item credible, given the outlet's record and any denial?
- Can this candidate fund an acquisition of this size (especially private candidates that pay with newly raised capital or stock)?
- This candidate's equity is tagged `vendor_financing`, `capacity_backstop`, or `customer_equity_kicker`. Is it a way to sell product or secure capacity, or the first step toward owning the target?
- The agent's estimate and the reference prior disagree by more than `prior_gap_flag`. Which view do you hold?

## Self-check tolerances

| Check | Tolerance |
|---|---|
| Σ `acquirer_distribution` probabilities | 1e-6 |
| Derived `p_acquired` | exact (computed) |
| `stake_probabilities[k] ≥ acquirer_distribution[k]` for every candidate | 1e-6 |
| Resolved stakes have probability 1 | exact |
| `expected_announcement_date` in `[clock, horizon.end]` | exact |
| Every candidate appears exactly once in each distribution | exact |
| Every `equity` and `debt` relationship, and every resolved stake, has a `structure` tag; a tag other than `pure_equity`, `arms_length`, or `undetermined` lists ≥ 1 `linked_relationships` key of the required type (supply for `vendor_financing`, backstop for `capacity_backstop`, compute contract for `customer_equity_kicker`) | exact |

## Open questions

- **Candidate coverage.** A thesis that omits the eventual acquirer can only put mass on `other`. Should the template suggest candidates from extracted relationships, and should RFC-007 report how often the realized acquirer was not a named candidate?
- **Private-target stakes.** Ownership percentages are rarely disclosed for private targets, so the USD threshold does most of the work there. Is US$1bn the right line?
- **Structure tag edges.** Is 90 days the right window for linking equity to a commercial agreement? Circular deals can be spread over longer periods, and unrelated deals can fall inside the window by coincidence.
- **Several structures in one relationship.** A candidate might hold a pure-equity stake from years ago and later add vendor financing. Is one tag per relationship item enough, or should each tranche be its own item?
- **Partial asset deals.** A candidate buying one data-center campus from the target isn't control of the target. Should a large enough asset purchase be a third event type?
- **Scheduled re-estimate cadence.** Monthly is a guess. Should it tighten as the horizon end approaches?
- **Same target, different theses.** Two theses on the same target with different candidate lists can disagree about `p_acquired`. Judgment isolation (RFC-001) means nothing reconciles them. Is that acceptable to users?
