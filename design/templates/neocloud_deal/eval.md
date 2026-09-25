# `neocloud_deal` Eval Spec

Template: [`neocloud_deal`](template.yaml) · Rationale: [RFC-008](../../rfc/008-neocloud-deal-template.md) · Harness: [RFC-007](../../rfc/007-replay-evaluation.md)

This spec plugs `neocloud_deal` into the core replay harness. RFC-007 defines everything generic: the virtual clock, point-in-time enforcement, canaries, isolation, the contamination procedure, the core metrics, core configurations, robustness mechanics, and the output format. This file defines what is specific to this template: the dataset, the labels, the outcome-revealing interval, the anonymization table, the probe wording, the template metrics, the baselines, the distractor types, and the extra error classes. Section numbers mirror RFC-007.

No results exist yet. Every number below is a selection criterion, a configuration value, or a labeled **target**, never a measured result.

## Why this template is hard to evaluate

- **Contamination.** AI-infrastructure deals are recent and heavily covered, so models may already know which neocloud got bought or funded by whom.
- **Rare events.** Most target-windows end with nothing happening. A model that always says "no deal" scores well on raw Brier and is useless, so log loss, ranking, and lead time carry the headline.

## 1. Dataset

### 1.1 Unit, size, and composition

The unit is a **case**: one target over one 12-month window, `(target, window)`. A target can contribute several non-overlapping windows. The statistical unit for confidence intervals is the **target**, because windows of the same target are correlated (§4).

| Stratum | Requirement (**targets**) |
|---|---|
| Distinct targets | ≥ 30 |
| Cases | ≥ 60 |
| Cases with an acquisition | ≥ 6 (may be infeasible; see open questions) |
| Cases with ≥ 1 candidate stake event | ≥ 15 |
| Cases with no event | the remainder |
| Cases whose window starts after the latest evaluated model's stated training cutoff | ≥ 20 (see §3.1) |

Strata overlap: a case with both a stake and a later acquisition counts toward both.

### 1.2 Selection criteria (rebuildable)

**Universe (point-in-time).** A company is in the universe at date `d` if, before `d`, at least one primary-source document (its own SEC filing or press release) describes its main business, current or planned, as renting GPU or accelerator compute, or providing AI-dedicated data-center capacity. This includes crypto miners that disclose AI/HPC hosting as a main or planned main business. Private and public companies both qualify.

> Trade-off: deciding membership only from documents dated before the window starts stops the dataset from favoring companies because they later became famous. It admits marginal companies (a miner that announced an AI pivot and never delivered), which lowers the base rate and makes the problem harder. That is closer to what a live user faces.

**Candidates.** One fixed list of ≤ 12 candidates, the same for every case, frozen in the manifest **before** any outcome labeling. It covers the RFC-008 candidate types (AI labs, hyperscalers, chipmakers, neoclouds). Everything else is `other`.

**Window.** Windows start on a calendar-quarter boundary between 2020-01-01 and `freeze − 12 months − 30 days`. Each target's first window starts at a seeded quarter offset, and later windows follow back to back. A target's windows stop after the first acquisition.

**Enumeration.**

1. Run published full-text queries ("GPU cloud", "AI cloud", "accelerated computing infrastructure", "HPC hosting", "AI data center") over EDGAR (`S-1`, `F-1`, `10-K`, `20-F`, `8-K`) and over the wire-service press-release archives, for the whole window range.
2. An annotator applies the universe definition to each hit, following the written guide (`dataset/ANNOTATION.md`, planned), and records the first qualifying document and its `as_of`. A second annotator checks every inclusion and a random 20% of exclusions.
3. Cut each included target into windows, keeping only windows that start after its first qualifying document.
4. Label outcomes (§1.3) from primary sources.
5. Record every dropped company and window with a reason code in `pool_exclusions.csv`.

**Stratified sampling.**

- Label each pool case: `acquisition_outcome`, `any_stake_event`, and window position relative to each evaluated model's cutoff.
- Rank cases within each stratum by `sha256(seed || target_id || window_start)`, with the `seed` published in the manifest.
- Fill the stratum quotas in rank order, then fill the remainder from the rest of the pool in rank order. A target's windows can be drawn independently.

**Reference set.** Pool cases that are **not** in the eval set and whose windows end before the earliest eval window starts form the reference set. It is used for base rates (§5) and to fit the RFC-008 `rp-1` weights, and nothing else. Neocloud history is short, so the reference set may be broadened to compute-adjacent companies (data-center operators, hosting providers) from before 2020. Any broadening is stated in the manifest.

### 1.3 Per-case record

Stored in `dataset/cases/<case_id>.json`:

| Field | Definition |
|---|---|
| `case_id` | Stable ID, `nd-<target_id>-<window_start>` |
| `target` | Name, CIK and ticker when applicable, `listing` at window start |
| `candidates` | The manifest candidate list (by reference) |
| `window` | `{start, end}` |
| `timeline[]` | EDGAR filings by the target, and candidate filings that mention the target, from `window.start − 365d` through resolution: accession number, form, acceptance datetime, content hash |
| `press_releases[]` | Target and candidate releases that mention the target, same period: source URL, archived copy hash, wire timestamp. Excluded if no verifiable timestamp. |
| `news[]` | Named-outlet articles mentioning the target, same period: URL, outlet, stated publication time, first archive capture time, archived copy hash (§1.4) |
| `acquisition_outcome` | `{key: <candidate> | other | none, announcement_date?, evidence?}` |
| `stake_outcomes[]` | One per candidate: `{candidate, occurred, date?, basis: pct | usd | acquisition, labels?, label_flags?, evidence?, confirmation: primary | unconfirmed}`. `labels.structure` follows the RFC-008 tag rules. |
| `resolution_date` | The acquisition announcement date if there is one, else `window.end` |
| `relationships_timeline[]` | Every RFC-008 relationship key between the target and a candidate, with `first_disclosed_as_of`, status changes and their `as_of`, structure tags (and tag changes) for `equity` and `debt` items, and the supporting evidence. This makes relationship labels point-in-time: the set "active at clock `t`" can be computed for any checkpoint. |
| `target_facts_at_start` | Listing, control, capital, and concentration facts at `window.start` |
| `labels_provenance` | Annotator IDs, adjudication notes |

**Event confirmation.** An acquisition or stake event counts only if a **primary** source from either party confirms it. An event reported only by news is labeled `unconfirmed`. The case stays in the dataset, but that `(case, candidate)` pair is excluded from stake metrics (§7.2). Acquisitions are always primary-confirmed, because an acquisition without an announcement doesn't exist under RFC-008.

**Labeling.** `stake_outcomes` and `relationships_timeline` are labeled independently by two annotators following the written guide. Disagreements are adjudicated by a third. Inter-annotator agreement is reported per field, and separately for structure tags, which are the most judgment-heavy labels. No agreement figure is assumed in advance. `signals` are not labeled or scored; they are too subjective to have a ground truth.

### 1.4 Frozen evidence corpus

The corpus follows RFC-007 §1.4, including the archive-capture `as_of` rule for news. Template notes:

- **News is required**, not optional: private targets have few primary documents, and reported talks are often the earliest signal. The archive rule biases lead time (§4) against the agent, which we accept.
- **No prices.** The template has no market-data source (RFC-008).
- The corpus covers `window.start − 365 days` through resolution, so the initial evaluation has a year of context.

## 2. Harness settings

| RFC-007 hook | Value for `neocloud_deal` |
|---|---|
| Case → thesis | `subject` = target plus the manifest candidates; `horizon = window` |
| Initial clock | `window.start` (with the one-year lookback visible) |
| Full resolution (stop) | the event containing the acquisition evidence, or `window.end` |
| Partial resolutions (continue) | stake events; a `(case, candidate)` pair stops being scored for stakes once its stake event happens |
| Scheduled re-estimates | every 30 days in virtual time (template default) |
| Canary example | a fake announcement, dated after resolution, that a candidate acquired the target |
| Pinned extras in the run manifest | candidate list, universe queries, `rp-1` weight table hash |
| Cluster unit for the bootstrap | the **target** (windows of one target are correlated) |

## 3. Contamination settings

### 3.1 Outcome-revealing interval

The whole window. A case is `post_cutoff` if `window.start > effective_cutoff + guard_band`, `pre_cutoff` if `window.end < effective_cutoff − guard_band`, and `straddle` otherwise (excluded from headline rows). The outcome can leak through any event inside the window, such as a stake announced in month 3 that foreshadows an acquisition in month 9. A model that knows facts from before the window leaks nothing, since the agent can see those facts at `clock` anyway.

> Trade-off: this is the strictest rule that still makes sense, and it will leave very few post-cutoff cases for recent models (see open questions).

### 3.2 Anonymization table

Applied with the RFC-007 §3.2 pipeline (entity table, model-assisted pass, leak check).

| Element | Transform |
|---|---|
| Target name, subsidiaries, brands, data-center site names | Consistent placeholders (`TARGET_CO`, `TARGET_SITE_1`) |
| Candidate names | `CANDIDATE_<type>_<n>` (for example `CANDIDATE_AI_LAB_1`). The candidate type is kept because it matters to the question. |
| Other companies (customers that aren't candidates, peers, lenders) | Placeholders with a coarse role (`CUSTOMER_1`, `LENDER_2`) |
| Tickers, CIKs, CUSIPs, addresses, URLs | Placeholders |
| People (executives, founders, advisors, reporters) | Role placeholders (`TARGET_CEO`, `REPORTER_1`) |
| Monetary amounts, share counts, valuations, contract values | Multiplied by a per-case secret factor `k ∈ [0.5, 2.0]`. This keeps ratios intact (concentration, ownership %, contract value vs. valuation). |
| Capacity (MW, accelerator counts) | Multiplied by the same `k` |
| Accelerator product names | Generation-level placeholders (`GPU_GEN_N`) |
| Dates | Shifted by a per-case secret offset of whole weeks, which preserves weekdays and all intervals |
| Outlet names | `OUTLET_HIGH_n` / `OUTLET_NORMAL_n` by configured reliability |


> Trade-off: anonymization removes real signal. A candidate's known appetite for acquisitions, or a founder's public stance on selling, legitimately affects the estimate, so anonymized scores are expected to understate true capability. The universe is also small and famous, so re-identification rates will likely be high (see open questions). We report named post-cutoff and anonymized results separately, and neither alone is the whole picture.

### 3.3 Probe wording and flag rules

For each case and each model in the configuration, before any replay:

- **Named probe:** "Between `<window.start>` and `<window.end>`, was `<target>` acquired, and by whom? Did any of `<candidates>` take an equity stake of 5% or more, or invest US$1bn or more? Answer `unknown` for anything you do not know." 5 samples at the provider's default temperature.
- **Re-identification probe** (anonymized variant): give the anonymized target's earliest primary document in the window and ask "Which real company is this, and which real companies are the candidates?" 5 samples.

**Flagging.** "No deal" is right by chance most of the time, so a correct negative alone is weak evidence. A case is flagged `known_outcome` for a model if a majority of samples:

- correctly name the acquirer of an acquired target; or
- correctly name a candidate that took a stake, with a date within ±31 days; or
- for a no-event case, state the target's status at window end with a specific, correct detail (for example an IPO or a named financing round in the window).

The anonymized twin is flagged `reidentified` if a majority of samples name the correct target, or name two or more candidates correctly.

Consequences and the headline rule follow RFC-007 §3.3–3.4.

## 4. Template metrics

Core metrics (citation precision, PIT violations, cost, latency, review load, provider-conflict split) are defined in RFC-007 §4. Confidence intervals are clustered by target. The row schema for the metrics below is [`eval-metrics.schema.json`](eval-metrics.schema.json).

**Acquisition**

| Metric | Definition |
|---|---|
| **Acquirer log loss @start / @checkpoints** | `−log p(realized key)` over the `acquirer_distribution` keys (candidates, `other`, `none`), with probabilities floored at 0.001 for scoring. This is the primary acquisition metric, because it punishes a confident "none" on a case that was acquired far more than Brier does. |
| **Acquirer multi-class Brier** | `Σ_k (p_k − 1[k = realized])²`, at start and over checkpoints |
| **`p_acquired` Brier and BSS** | Binary Brier of `p_acquired` vs. "acquired in window", and `1 − Brier / Brier(B0)` |
| **Announcement-date abs. error (days)** | `|expected_announcement_date − announcement_date|`, acquired cases only. Median and mean at start and over checkpoints. Reported without a CI when fewer than 5 cases qualify. |

**Stakes**

| Metric | Definition |
|---|---|
| **Stake Brier and BSS** | Binary Brier over every scored `(case, candidate)` pair and checkpoint, then averaged per case, then across cases. BSS vs. B0. |
| **Stake log loss** | Same pairs, floored at 0.001 |

**Ranking and timing** (positive events only: every acquisition and every confirmed stake)

| Metric | Definition |
|---|---|
| **Rank of realized party** | Rank of the eventual acquirer (among candidates and `other`) or stake-taker (among candidates), at the initial checkpoint and at the last checkpoints ≥ 90 and ≥ 30 days before the event |
| **Top-1 / top-3 hit rate** | Share of positive events whose realized party is ranked 1st / in the top 3 at those checkpoints |
| **Lead time** | Days between the first checkpoint where the agent's probability for the realized party is ≥ 0.10 **and** ≥ 2× its reference prior, and the event. Events that never cross count as lead time 0. Median and mean. |
| **False-alarm rate** | Share of negative `(case, candidate)` pairs that ever cross the same line. Always reported next to lead time, since lead time alone rewards alarming on everyone. |

**By stake structure.** Rank, top-k, and lead time for stake events are also reported split by the labeled structure of the realized stake (`pure_equity`, the three commercial tags pooled, `undetermined`). Stake Brier can't be split this way, because negatives have no structure. The split shows whether the agent anticipates strategic bets or only commercial equity, which is usually announced alongside a contract it already knows about.

| Metric | Definition |
|---|---|
| **Structure tag accuracy** | Share of the agent's tags on resolved stakes and on labeled `equity`/`debt` relationships that match the adjudicated label, at the last scored checkpoint. Reported with the inter-annotator agreement on the same items, since the agent can't be expected to beat the annotators. |
| **Stake-before-acquisition rate** (reference set, descriptive) | Share of acquisitions preceded by a stake by the same acquirer, split by structure. Not an agent metric; it informs the `rp-1` weights and tells readers how much a commercial stake has historically meant. |

**Calibration**

Pooled over every candidate probability (acquisition and stake) at every checkpoint, bins `[0, .02) [.02, .05) [.05, .10) [.10, .25) [.25, .50) [.50, 1]`. Per bin: count of probabilities, count of cases, mean p, observed rate. The bins are low and uneven because nearly all probabilities are small. Acquisition and stake tables are also reported separately.

**Evidence**

| Metric | Definition |
|---|---|
| **Relationship recall / precision** | Share of labeled relationship keys active at the checkpoint's clock (`relationships_timeline`) that the agent's `relationships` lists, and the reverse. At the initial and last scored checkpoints. `other:*` keys are matched by an annotator. |
| **Secondary-only change rate** | Share of versions whose material change was `secondary_only`. |
| **Rumor hit rate** | Of `talks:<candidate>` signals the agent relied on, the share where that candidate had a confirmed acquisition or stake event in the window |
| **Δ vs reference prior** | Paired difference in acquirer log loss and stake Brier, agent minus B1, on the same checkpoints |

**Provider conflicts.** For this template, a provider conflict means a role's provider is a named candidate (RFC-008 *Conflict of interest*); the RFC-007 split applies to the probabilities involving that candidate.

The same definitions are used for `outcome_audit` feedback on live theses (RFC-004 §Feedback), so live and replay scores are comparable.

## 5. Baselines and extra ablations

Core configurations F, A1, A2, and G are defined in RFC-007 §5. This template adds:

| ID | Configuration | Changes |
|---|---|---|
| B0 | Base rate | `P(none) = (1 − b_listing)^T` from the reference set. The acquisition mass is split across candidates and `other` by the reference set's share of acquirer types. Stake probabilities from the reference set's annual stake rate by candidate type. `expected_announcement_date` = the horizon midpoint. No model calls. |
| B1 | Reference prior | RFC-008 `rp-1` at each checkpoint, computed from shared extractions with `as_of ≤ clock`. Probability and ranking metrics only. No estimator calls. |
| B1-oracle | Reference prior on labels (diagnostic) | `rp-1` computed from the annotated `relationships_timeline` instead of extractions. It separates extractor errors from the heuristic itself. Never compared against the agent as a headline. |
| A3 | Primary only | News removed from the corpus. Measures what secondary evidence (reported talks) adds, and what it costs in false alarms and overrides. |

B0, B1, and B1-oracle need no contamination split for the estimate itself, since no estimator model is involved. B1 still uses model extractions, so it is reported against the same case subsets as each headline row so the comparison is apples to apples.

**Power.** With about 30 targets, a handful of acquisitions, and exclusions shrinking the headline subsets further, CIs will be very wide. Acquisition metrics in particular may rest on single-digit events. We report intervals and paired differences, make no significance claims beyond them, and treat stake metrics as the main calibration evidence.

## 6. Robustness settings

Mechanics, pairing, and metric definitions are in RFC-007 §6. This template supplies the distractor types, collision rules, drift measures, and error classes below.

### 6.1 Distractor types

| Distractor type | Construction | Tier | Target per case |
|---|---|---|---|
| `irrelevant_release` | Real press releases from the target, a candidate, or a peer neocloud, annotated as unrelated to any deal (product launches, region openings, personnel changes) | primary | ≥ 3 |
| `stale_redated` | An earlier real evidence item from the same case (for example an old compute-contract announcement), re-packaged as a secondary news item with a new `as_of` and no new facts | secondary | ≥ 2 |
| `false_rumor` | A synthetic news-style item with a plausible, material, **false** claim: "sources say `<candidate>` is in talks to acquire `<target>`", "`<target>` has hired bankers to explore a sale", "`<candidate>` weighing a multibillion-dollar stake". Generated from a template with slots filled from the case, and checked against the ground-truth record to confirm the event never happened. Marked `secondary` with `source.reliability: low`. | secondary | ≥ 2 |

(Per-case counts are **targets**.)

A `false_rumor` naming a candidate is added only if that candidate has no real acquisition or stake event with the target in the window, and no real reported talks within ±30 days. Otherwise the ground truth would be ambiguous.

Metrics are the RFC-007 §6.1 set. Template specializations:

- **Drift measures:** mean absolute log-odds difference vs. clean in `p_acquired` and in the named candidate's probabilities, over the 3 checkpoints after the distractor.
- **Noisy − clean:** acquirer log loss @checkpoints and stake Brier.
- **Unflagged support:** a rumor cited in support of a change without the `secondary_only` flag must be **0** (the template opts in to that audit).

> Trade-off: synthetic rumors test the failure mode that matters most for this template, over-reacting to low-trust talk. But the rumors are only as realistic as their template, so a low induced-change rate shows robustness to *our* rumors, not to every rumor. The templates are published with the dataset so others can criticize and extend them.

### 6.2 Template error classes

Core error classes (RFC-007 §6.2) apply as well. `distribution_sum` and `derivation_mismatch` are this template's instances of the core `type_invariant` class, and `unflagged_rumor` is its instance of `unflagged_secondary`.

| Error class | Mutation | Expected catcher |
|---|---|---|
| `distribution_sum` | Scale one `acquirer_distribution` probability so the sum ≠ 1 | self-check (code) |
| `derivation_mismatch` | Change `p_acquired` without changing the distribution | self-check (code) |
| `stake_below_acquisition` | Set a candidate's stake probability below its acquisition probability | self-check (code) |
| `date_outside_horizon` | Move `expected_announcement_date` past `horizon.end` | self-check (code) |
| `relationship_inconsistency` | Mark the top candidate's main relationship `terminated` while its rationale still treats it as active | self-check (model) |
| `structure_unlinked` | Remove `linked_relationships` from an item tagged `vendor_financing`, `capacity_backstop`, or `customer_equity_kicker` | self-check (code) |
| `unflagged_rumor` | Remove the `secondary_only` flag from a rumor-driven change | audit (code, secondary-only check) |

Metrics follow RFC-007 §6.2. The code-checkable classes are regression tests; the informative template number is `relationship_inconsistency`.

### 6.3 Faults

Core fault classes and metrics (RFC-007 §6.3), unchanged.

## 7. Output additions

### 7.1 Results table

Configurations: B0, B1, B1-oracle, A3 (this spec) plus the core F, A1, A2, G. Variants and subsets are the RFC-007 ones. Template columns come from [`eval-metrics.schema.json`](eval-metrics.schema.json):

| n_targets | n_events (acq / stake) | acq log loss @start / @ckpt [CI] | p_acq Brier [CI] | BSS | stake Brier [CI] | stake BSS | top-1 / top-3 @90d | lead time / false alarm | Δ vs prior | date MAE (d) | rel. recall @start / @last | structure tag acc. |
|---|---|---|---|---|---|---|---|---|---|---|---|---|

Calibration bins: `[0, .02) [.02, .05) [.05, .10) [.10, .25) [.25, .50) [.50, 1]`, kinds `pooled`, `acquirer_distribution`, `stake_probabilities`.

### 7.2 Exclusions and flags

Core exclusion reasons are in RFC-007 §7.2. This template adds:

| reason | meaning |
|---|---|
| `straddle` | window overlaps `effective_cutoff ± 90d` (§3.1) |
| `thin_corpus` | no primary-source document about the target before `window.start` (the initial evaluation would end in `needs_input`) |
| `unconfirmed_event` | a stake reported only by news; that `(case, candidate)` pair is excluded from stake metrics |

`pool_exclusions.csv` (§1.2) lists every company and window dropped before sampling, with its reason.

## Open questions

- **Acquisitions are scarce.** Control acquisitions of neoclouds by AI labs or big tech are rare, and even rarer after recent model cutoffs. The acquisition stratum may never reach 6 cases in H-named. Should the universe widen to all AI-infrastructure targets (chip startups, data-center operators), at the cost of a less specific question?
- **Window length.** The whole-window cutoff rule leaves few post-cutoff 12-month windows. Would 6-month windows give more usable cases, or just more correlated ones?
- **News archive coverage.** Private targets depend on news, and archive capture of trade outlets is patchy. How many relevant articles will the archive rule drop, and does that bias the corpus toward heavily covered (and so more famous, more contaminated) targets?
- **Anonymization strength.** The universe is small and famous. A GPU cloud whose biggest customer is `CANDIDATE_HYPERSCALER_1` may be re-identified almost every time, which would hollow out H-anon. The probe will tell us only after the corpus is built.
- **Structure tags at private targets.** Use-of-proceeds and purchase conditions are rarely disclosed by private companies, so many private-target stakes may end up `undetermined`. If so, the structure split will say little about exactly the targets where vendor financing is most common.
- **Provider as candidate.** If a model's provider is a candidate, is a split report enough, or should those probabilities be excluded from headline rows entirely?
