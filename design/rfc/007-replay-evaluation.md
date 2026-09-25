# RFC-007: Replay Evaluation

Status: Discussion

Date: 2026-09-23 (revised 2026-09-24 for `neocloud_deal`)

Depends on: RFC-004, RFC-005, RFC-006, RFC-008

## Problem

A `neocloud_deal` agent is only useful if its probabilities are calibrated at low base rates, it ranks the eventual acquirer or investor near the top **before** the announcement, its relationship map is complete, and its citations hold up. None of that can be judged from one live thesis, and a 12-month horizon takes 12 months to resolve. Historical windows resolve instantly, but they have three traps:

1. **Look-ahead.** A replay that shows the agent a later filing or article, even through a cached extraction, measures nothing.
2. **Contamination.** The models may already know which neocloud got bought or funded by whom. AI-infrastructure deals are recent and heavily covered, so this risk is higher here than for almost any other domain.
3. **Rare events.** Most target-windows end with nothing happening. A model that always says "no deal" scores well on raw Brier and is useless.

This RFC defines a dataset, a harness, contamination controls, metrics, baselines, and an output format. Together they let anyone rebuild the evaluation and check whether a reported number came from estimation.

No results exist yet. Every number below is a selection criterion, a configuration value, or a labeled **target**, never a measured result.

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
| `stake_outcomes[]` | One per candidate: `{candidate, occurred, date?, basis: pct | usd | acquisition, structure?, structure_flags?, evidence?, confirmation: primary | unconfirmed}`. `structure` follows the RFC-008 tag rules. |
| `resolution_date` | The acquisition announcement date if there is one, else `window.end` |
| `relationships_timeline[]` | Every RFC-008 relationship key between the target and a candidate, with `first_disclosed_as_of`, status changes and their `as_of`, structure tags (and tag changes) for `equity` and `debt` items, and the supporting evidence. This makes relationship labels point-in-time: the set "active at clock `t`" can be computed for any checkpoint. |
| `target_facts_at_start` | Listing, control, capital, and concentration facts at `window.start` |
| `labels_provenance` | Annotator IDs, adjudication notes |

**Event confirmation.** An acquisition or stake event counts only if a **primary** source from either party confirms it. An event reported only by news is labeled `unconfirmed`. The case stays in the dataset, but that `(case, candidate)` pair is excluded from stake metrics (§7.2). Acquisitions are always primary-confirmed, because an acquisition without an announcement doesn't exist under RFC-008.

**Labeling.** `stake_outcomes` and `relationships_timeline` are labeled independently by two annotators following the written guide. Disagreements are adjudicated by a third. Inter-annotator agreement is reported per field, and separately for structure tags, which are the most judgment-heavy labels. No agreement figure is assumed in advance. `signals` are not labeled or scored; they are too subjective to have a ground truth.

### 1.4 Frozen evidence corpus

The replay feeds a **frozen corpus**, never live sources: every `timeline`, `press_releases`, and `news` document, normalized once by the production adapters, stored content-addressed with its `as_of`. The manifest lists every document hash, so a rebuilt corpus can be checked byte for byte.

- **News `as_of` rule.** News articles are needed because private targets have few primary documents. Their stated publication times can't be trusted alone, since pages are edited and re-dated. A news item's `as_of` is therefore the **later** of its stated publication time and its first capture in a public web archive, and the corpus stores the **earliest captured** version of the text. An article with no archive capture before resolution is dropped.
- **Open web search is disabled in replay.** Only the named-outlet news set above is used. A live deployment that uses open web search is not fully covered by this evaluation; that limitation is stated in every results table.
- **Amendments** are separate documents with their own `as_of`.
- **No prices.** The template has no market-data source (RFC-008).

> Trade-off: taking the later of publication and archive capture can make an article visible to the agent hours or days after it really appeared. That understates how early the agent could have reacted, which biases lead-time metrics (§4) against the agent. We accept that bias because the opposite error, a re-dated article leaking the future, would invalidate the run.

## 2. Replay harness

### 2.1 Procedure (per case × configuration × repeat)

1. Create a thesis from the case record (`subject` with the manifest candidates and `horizon = window`, `template: neocloud_deal@<pinned>`, `sources` pointing at the frozen corpus, `review: auto`). Auto-approval follows RFC-004: rumor-only audit failures are approved as `replay_auto` overrides; any other audit failure leaves the head unchanged.
2. Build the event stream: corpus documents with `as_of` in the window, sorted by `(as_of, id)`. Documents with identical `as_of` form one event. Add scheduled re-estimate events at the template cadence **in virtual time**, skipping any within `reestimate_days` of a real evaluation (RFC-008).
3. Set `clock = window.start`. Run the initial evaluation (`trigger: initial`) with everything with `as_of ≤ clock` visible, including the one-year lookback.
4. For each subsequent event: advance `clock` to the event's `as_of`, apply the production debounce in virtual time, and run the evaluation job exactly as in production (RFC-005).
5. Stake events are partial resolutions: the replay keeps running.
6. Stop after the event that contains the acquisition evidence, or at `window.end`. Evaluations at or after the resolving event are recorded but **not scored**.
7. Record every ThesisVersion, EvaluationRecord, ReviewPacket, and telemetry row.

> Trade-off: applying debounce and scheduled re-estimates in virtual time makes replay faithful to production batching and decay, but it produces fewer checkpoints than scoring every single document. We score what production would have produced.

### 2.2 What is scored at a checkpoint

A **checkpoint** is the initial evaluation plus every subsequent event and scheduled re-estimate before resolution.

- **Primary:** the head, i.e. the latest auto-approved ThesisVersion at that clock. This is what a user would have relied on.
- **Secondary:** the latest *proposed* values, including those in `below_threshold` EvaluationRecords. The gap between primary and secondary shows how much accuracy the material-change gate trades for less review load.

For stake metrics, a `(case, candidate)` pair stops being scored once that candidate's stake event happens.

### 2.3 Point-in-time enforcement (three layers)

1. **Store:** the corpus view is queried with `as_of ≤ clock`.
2. **Context builder:** the RFC-005 assertion before every model call.
3. **Post-run audit:** for every version, re-check `max(as_of of evidence_set) ≤ clock` and every citation's `as_of ≤ clock`.

**Canaries.** Each case's corpus contains ≥ 1 synthetic document with `as_of` after resolution, carrying a unique canary string (for example a fake announcement that a candidate acquired the target). If a canary appears in any model input (checked in the harness, which can see content) or in any output, that is a violation.

A violation found by any layer invalidates the run for that configuration: it is marked `invalid` and excluded from every table, and the violation count is reported. The required count is **zero**.

### 2.4 Isolation and determinism

- No network access except model provider endpoints. No fetch or search tools in any lane.
- Model IDs, prompts, template versions, `rp-1` weights, and the price table are pinned and hashed into the run manifest.
- Temperature 0 where the provider supports it. **target:** 3 repeats per case per configuration. Report the mean and the between-repeat spread.
- The system prompt tells the model the current date is `clock` (named runs) or the shifted clock (anonymized runs, §3.2).

### 2.5 Run manifest

`run_id`, git SHA, template version, corpus manifest hash, dataset version, candidate list, universe queries, `rp-1` weight table hash, for each role `{provider, model_id, stated_training_cutoff, cutoff_source_url}`, seeds, repeats, price table, harness version.

## 3. Contamination

Models may already know what happened to a neocloud. All three mitigations are required, and the headline uses only runs that pass them.

### 3.1 Cutoff split

- For each configuration, `effective_cutoff = max(stated_training_cutoff)` over **every** model that sees case-identifying content (planner, estimator, extractor, auditor).
- A case is `post_cutoff` if `window.start > effective_cutoff + guard_band`, `pre_cutoff` if `window.end < effective_cutoff − guard_band`, and `straddle` otherwise. `guard_band` = 90 days (a configuration value).
- Results are reported separately for `pre_cutoff` and `post_cutoff`. Straddle cases appear only in the exclusions list.

The split uses the whole window, not just the resolution date. In this template the outcome can leak through any event inside the window, such as a stake announced in month 3 that foreshadows an acquisition in month 9. A model that knows facts from before the window leaks nothing, since the agent can see those facts at `clock` anyway.

> Trade-off: splitting on the whole window is the strictest rule that still makes sense, and it will leave very few post-cutoff cases for recent models (see open questions). Taking the max cutoff across roles is conservative too, since one model with a recent cutoff shrinks the post-cutoff set for the whole configuration.

### 3.2 Anonymized variant

Each case's corpus is transformed into an anonymized twin, stored as a **separate evidence namespace** with its own IDs and its own extraction cache, so nothing from the named corpus leaks through cached extractions.

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

Pipeline: deterministic replacement from a per-case entity table → a model-assisted pass to catch residual identifiers → a **leak check** that runs regexes for every original name, ticker, CIK, product name, and exact original monetary or capacity figure. A document with any leak-check hit is dropped. If a dropped document is on the outcome path or supports a labeled relationship, the case's anonymized run is excluded.

Ground-truth labels are transformed with the same table. Scores are computed in the transformed space and dates are un-shifted before reporting.

> Trade-off: anonymization removes real signal. A candidate's known appetite for acquisitions, or a founder's public stance on selling, legitimately affects the estimate, so anonymized scores are expected to understate true capability. The universe is also small and famous, so re-identification rates will likely be high (see open questions). We report named post-cutoff and anonymized results separately, and neither alone is the whole picture.

### 3.3 Knowledge probe

For each case and each model in the configuration, before any replay:

- **Named probe:** "Between `<window.start>` and `<window.end>`, was `<target>` acquired, and by whom? Did any of `<candidates>` take an equity stake of 5% or more, or invest US$1bn or more? Answer `unknown` for anything you do not know." 5 samples at the provider's default temperature.
- **Re-identification probe** (anonymized variant): give the anonymized target's earliest primary document in the window and ask "Which real company is this, and which real companies are the candidates?" 5 samples.

**Flagging.** "No deal" is right by chance most of the time, so a correct negative alone is weak evidence. A case is flagged `known_outcome` for a model if a majority of samples:

- correctly name the acquirer of an acquired target; or
- correctly name a candidate that took a stake, with a date within ±31 days; or
- for a no-event case, state the target's status at window end with a specific, correct detail (for example an IPO or a named financing round in the window).

The anonymized twin is flagged `reidentified` if a majority of samples name the correct target, or name two or more candidates correctly.

Consequences:

- A `known_outcome` case is excluded from **named** headline runs even if it is post-cutoff, because stated cutoffs can be wrong.
- A `reidentified` case is excluded from **anonymized** headline runs.
- All flags are listed in the exclusions output.

### 3.4 Headline rule

Headline numbers come only from:

- **H-named:** named runs on `post_cutoff` cases that are not `known_outcome` for any model in the configuration;
- **H-anon:** anonymized runs on cases that are not `reidentified` for any model in the configuration.

H-named and H-anon are reported as **separate rows** and never pooled.

The `pre_cutoff` named row is reported as a **contamination diagnostic**. The paired difference between pre-cutoff named and anonymized scores on the same cases estimates how much memorization inflates named results.

## 4. Metrics

Unless stated otherwise, each case is weighted equally: a metric is averaged over a case's checkpoints first, then across cases. Confidence intervals are 95% **target-clustered** bootstrap intervals (resampling targets with all their cases, 10,000 resamples). Comparisons between configurations use **paired** bootstrap over the same targets.

> Trade-off: clustering by target is honest about how little independent information 30 targets carry, and it widens every interval. Weighting cases equally stops long, news-heavy windows from dominating.

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

**Evidence and review**

| Metric | Definition |
|---|---|
| **Relationship recall / precision** | Share of labeled relationship keys active at the checkpoint's clock (`relationships_timeline`) that the agent's `relationships` lists, and the reverse. At the initial and last scored checkpoints. `other:*` keys are matched by an annotator. |
| **Secondary-only change rate** | Share of versions whose material change was `secondary_only`. |
| **Rumor hit rate** | Of `talks:<candidate>` signals the agent relied on, the share where that candidate had a confirmed acquisition or stake event in the window |
| **Δ vs reference prior** | Paired difference in acquirer log loss and stake Brier, agent minus B1, on the same checkpoints |
| **Citation precision** | Share of ReviewPacket claims whose cited evidence supports them. Measured two ways: (a) an **eval judge** on all claims. This is a separate configuration from the pipeline auditor, so the pipeline never grades itself. (b) Humans on a stratified random sample, **target:** ≥ 150 claims per headline configuration, stratified by provenance and tier. Judge–human agreement (Cohen's κ) is reported so readers can see how far to trust (a). |
| **PIT violations** | Count across the three layers plus canaries. Must be **0**. Any violation invalidates the run. |
| **Cost per version / per evaluation** | USD from content-free telemetry and the pinned price table. p50, p90. Scheduled evaluations reported separately. |
| **Latency per version** | Evaluation job start → commit, wall clock. p50, p90. |
| **Review load** | Versions per case, versions per case-month, and overrides per case (`replay_auto` rumor approvals, RFC-004; each would be a human decision live). Versions left unapproved because of other audit failures are counted separately. |

**Provider-candidate split.** Every row is also reported split by whether any role's provider is a named candidate in the manifest (RFC-008 *Conflict of interest*), for the probabilities involving that candidate.

The same definitions are used for `outcome_audit` feedback on live theses (RFC-004 §Feedback), so live and replay scores are comparable.

## 5. Baselines and ablations

All configurations run on the same dataset, the same corpus, the same seeds, and the same template version. Only the stated factor changes.

| ID | Configuration | Changes |
|---|---|---|
| B0 | Base rate | `P(none) = (1 − b_listing)^T` from the reference set. The acquisition mass is split across candidates and `other` by the reference set's share of acquirer types. Stake probabilities from the reference set's annual stake rate by candidate type. `expected_announcement_date` = the horizon midpoint. No model calls. |
| B1 | Reference prior | RFC-008 `rp-1` at each checkpoint, computed from shared extractions with `as_of ≤ clock`. Probability and ranking metrics only. No estimator calls. |
| B1-oracle | Reference prior on labels (diagnostic) | `rp-1` computed from the annotated `relationships_timeline` instead of extractions. It separates extractor errors from the heuristic itself. Never compared against the agent as a headline. |
| F | Full system | Production routing (RFC-008) |
| A1 | Planner/estimator low-cost | Planner and estimator switched to the extractor-tier model; everything else as F |
| A2 | No auditor | Auditor role and repair loop disabled. Deterministic checks stay (they are code). Citation precision is still measured by the eval judge and humans. |
| A3 | Primary only | News removed from the corpus. Measures what secondary evidence (reported talks) adds, and what it costs in false alarms and overrides. |
| G | Gate off (secondary scoring of F) | No new runs; scores F's proposed values (§2.2) |

B0, B1, and B1-oracle need no contamination split for the estimate itself, since no estimator model is involved. B1 still uses model extractions, so it is reported against the same case subsets as each headline row so the comparison is apples to apples.

**Power.** With about 30 targets, a handful of acquisitions, and exclusions shrinking the headline subsets further, CIs will be very wide. Acquisition metrics in particular may rest on single-digit events. We report intervals and paired differences, make no significance claims beyond them, and treat stake metrics as the main calibration evidence.

## 6. Robustness variants

These variants reuse the F configuration and the headline subsets (H-named, H-anon). Each noisy or faulty run is **paired** with the clean F run that has the same seed. Their scores are reported as separate rows (`variant` column) and never mixed into clean headline rows.

### 6.1 Noise robustness (distractor evidence)

Distractors are injected into the replay event stream at seeded random positions in the window. Each distractor gets `as_of` equal to its injection point, so point-in-time rules still hold. The harness knows every distractor ID, but the agent does not.

| Distractor type | Construction | Tier | Target per case |
|---|---|---|---|
| `irrelevant_release` | Real press releases from the target, a candidate, or a peer neocloud, annotated as unrelated to any deal (product launches, region openings, personnel changes) | primary | ≥ 3 |
| `stale_redated` | An earlier real evidence item from the same case (for example an old compute-contract announcement), re-packaged as a secondary news item with a new `as_of` and no new facts | secondary | ≥ 2 |
| `false_rumor` | A synthetic news-style item with a plausible, material, **false** claim: "sources say `<candidate>` is in talks to acquire `<target>`", "`<target>` has hired bankers to explore a sale", "`<candidate>` weighing a multibillion-dollar stake". Generated from a template with slots filled from the case, and checked against the ground-truth record to confirm the event never happened. Marked `secondary` with `source.reliability: low`. | secondary | ≥ 2 |

(Per-case counts are **targets**.)

A `false_rumor` naming a candidate is added only if that candidate has no real acquisition or stake event with the target in the window, and no real reported talks within ±30 days. Otherwise the ground truth would be ambiguous.

Metrics, per distractor type:

| Metric | Definition |
|---|---|
| **Distractor-induced change rate** | Share of distractor events after which the noisy run's head differs **materially** (RFC-008 thresholds) from the paired clean run's head at the same clock. A change is counted only when the next checkpoint's ImpactAssessment or `caused_by` includes the distractor. This rules out ordinary run-to-run variance. |
| **Distractor-induced drift** | The same comparison with no materiality threshold: the mean absolute log-odds difference in `p_acquired` and in the named candidate's probabilities vs. clean, over the 3 checkpoints after the distractor |
| **Distractor citation rate** | Share of ReviewPackets produced after a distractor that cite it. Reported separately as (a) cited *in support of a change* and (b) cited only in `uncertain_items` or `conflicts`. For a rumor, (b) is acceptable; (a) is acceptable only with the `secondary_only` flag set, and the rate of (a) without the flag must be **0**. |
| **Noisy − clean log loss** | Paired difference in acquirer log loss @checkpoints and stake Brier |

> Trade-off: synthetic rumors test the failure mode that matters most for this template, over-reacting to low-trust talk. But the rumors are only as realistic as their template, so a low induced-change rate shows robustness to *our* rumors, not to every rumor. The templates are published with the dataset so others can criticize and extend them.

### 6.2 Self-check catch rate (injected errors)

A mutation hook in the harness alters the estimator's candidate **after** estimation and **before** self-check. The hook is not visible to the model. Each mutated evaluation gets exactly one error, and the clean paired run supplies the reference.

| Error class | Mutation | Expected catcher |
|---|---|---|
| `distribution_sum` | Scale one `acquirer_distribution` probability so the sum ≠ 1 | self-check (code) |
| `derivation_mismatch` | Change `p_acquired` without changing the distribution | self-check (code) |
| `stake_below_acquisition` | Set a candidate's stake probability below its acquisition probability | self-check (code) |
| `date_outside_horizon` | Move `expected_announcement_date` past `horizon.end` | self-check (code) |
| `missing_citation` | Remove all citations from one changed quantity | self-check (code) |
| `future_citation` | Add a citation to a canary document with `as_of > clock` | self-check (code). Recorded as `injected`, and it does **not** count toward §4 PIT violations **provided it is caught before commit**. If it reaches commit, it counts as a real violation. |
| `wrong_citation` | Swap a citation's `evidence_id` for an unrelated item in the evidence set | self-check (model), then auditor |
| `relationship_inconsistency` | Mark the top candidate's main relationship `terminated` while its rationale still treats it as active | self-check (model) |
| `structure_unlinked` | Remove `linked_relationships` from an item tagged `vendor_financing`, `capacity_backstop`, or `customer_equity_kicker` | self-check (code) |
| `unflagged_rumor` | Remove the `secondary_only` flag from a rumor-driven change | audit (code, secondary-only check) |

Metrics:

- **Self-check catch rate** = errors detected by self-check / errors injected, per class and overall.
- **Downstream catch rate** = errors the self-check missed but the auditor caught / errors the self-check missed.
- **Escape rate** = errors that reached a committed version without being flagged / errors injected. Target **0** for the code-checkable classes.

The code-checkable classes (including `unflagged_rumor` and `structure_unlinked`) are expected to be caught every time. They serve as a regression test of the harness and the checks, not as evidence of model quality. The informative numbers are those for `wrong_citation` and `relationship_inconsistency`.

### 6.3 Recovery rate (injected tool failures)

A fault-injection layer in the MCP tool proxy and the model router injects failures at seeded points. **Target:** ≥ 1 fault per case per class in the fault variant.

| Fault class | Injection |
|---|---|
| `fetch_5xx` / `fetch_timeout` | Source adapter returns 503 or hangs past its timeout for N attempts (N drawn from {1, 2, 5}, so some faults exceed the retry budget) |
| `rate_limited` | 429 with `Retry-After` |
| `malformed_document` | Truncated or corrupted HTML for a filing or article |
| `extractor_malformed` | Extractor returns non-schema JSON |
| `extractor_timeout` | Extractor route times out |
| `route_outage` | A role's primary provider is unavailable for the whole evaluation |

Metrics:

- **Recovery rate** = faults after which the evaluation completed **and** the resulting head matches the paired clean run within RFC-008 material thresholds / faults injected.
- **Safe-failure rate** = faults not recovered where the system failed closed (job held or failed, or the quantity was flagged `extraction_unavailable`) / faults not recovered.
- **Unsafe rate** = faults after which a version was committed that differs materially from clean **without** a recovery or uncertainty flag / faults injected. Target **0**.
- **Recording completeness** = injected faults that appear as `RecoveryEvent`s / faults injected. Target **1.0**.
- Added latency and cost per recovered fault, p50 / p90.

## 7. Output

### 7.1 Results table

One table per evaluation run. Each row is one `(configuration, variant, subset)`:

- configurations: B0, B1, B1-oracle, F, A1, A2, A3, G;
- variants: `clean`, `noise`, `injected_errors`, `faults`;
- subsets: `H-named`, `H-anon`, `pre-cutoff-named (diagnostic)`.

The row schema is [`eval-result-row.schema.json`](../schemas/eval-result-row.schema.json). A column that doesn't apply to a row is `—` (`null` in JSON).

Core columns (every row):

| config | variant | subset | n_targets | n_cases | n_events (acq / stake) | n_ckpt | acq log loss @start / @ckpt [CI] | p_acq Brier [CI] | BSS | stake Brier [CI] | stake BSS | top-1 / top-3 @90d | lead time / false alarm | Δ vs prior | date MAE (d) | rel. recall @start / @last | cite prec judge / human (n) | κ | PIT viol. | $/version p50/p90 | latency p50/p90 | versions/case | overrides/case |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 | clean | H-named | | | | | | | | | | | — | | | — | — | — | 0 | 0 | — | — | — |
| B1 | clean | H-named | | | | | | | | | | | | — | — | | — | — | 0 | | — | — | — |
| F | clean | H-named | | | | | | | | | | | | | | | | | | | | | |
| … | | | | | | | | | | | | | | | | | | | | | | | |

Robustness columns (filled only for variant rows):

| distractor change rate (by type) | distractor citation rate (support / uncertain / support-unflagged) | noisy − clean log loss | self-check catch rate (by class) | downstream catch | escape rate | recovery rate | safe-failure | unsafe rate | recording completeness |
|---|---|---|---|---|---|---|---|---|---|

Calibration tables are attached to each row (`calibration[]` in the row schema).

### 7.2 Exclusions and flags

`exclusions.csv` has one line per `(case_id, candidate?, configuration, variant)` with `reason`:

| reason | meaning |
|---|---|
| `straddle` | window overlaps `effective_cutoff ± 90d` |
| `pre_cutoff` | excluded from headline, kept in diagnostic |
| `known_outcome:<model>` | named probe flagged |
| `reidentified:<model>` | anonymized probe flagged |
| `anonymization_leak` | a leak-check hit dropped a document the case needed |
| `missing_as_of` | a document had no verifiable timestamp and was needed |
| `corpus_incomplete` | a document referenced in labels is missing from the corpus |
| `thin_corpus` | no primary-source document about the target before `window.start` (the initial evaluation would end in `needs_input`) |
| `unconfirmed_event` | a stake reported only by news; that `(case, candidate)` pair is excluded from stake metrics |
| `run_invalid:pit_violation` | the run was invalidated |
| `run_failed:<error>` | the harness could not complete the run |
| `distractor_collision` | no collision-free slot for a required distractor type. The case is excluded from the noise variant. |

`pool_exclusions.csv` (§1.2) lists every candidate company and window dropped before sampling, with its reason.

## Open questions

- **Acquisitions are scarce.** Control acquisitions of neoclouds by AI labs or big tech are rare, and even rarer after recent model cutoffs. The acquisition stratum may never reach 6 cases in H-named. Should the universe widen to all AI-infrastructure targets (chip startups, data-center operators), at the cost of a less specific question?
- **Window length.** The whole-window cutoff rule leaves few post-cutoff 12-month windows. Would 6-month windows give more usable cases, or just more correlated ones?
- **News archive coverage.** Private targets depend on news, and archive capture of trade outlets is patchy. How many relevant articles will the archive rule drop, and does that bias the corpus toward heavily covered (and so more famous, more contaminated) targets?
- **Anonymization strength.** The universe is small and famous. A GPU cloud whose biggest customer is `CANDIDATE_HYPERSCALER_1` may be re-identified almost every time, which would hollow out H-anon. The probe will tell us only after the corpus is built.
- **Structure tags at private targets.** Use-of-proceeds and purchase conditions are rarely disclosed by private companies, so many private-target stakes may end up `undetermined`. If so, the structure split will say little about exactly the targets where vendor financing is most common.
- **Provider as candidate.** If a model's provider is a candidate, is a split report enough, or should those probabilities be excluded from headline rows entirely?
- **Eval judge independence.** Should the eval judge come from a third provider, distinct from both the estimator and the auditor?
