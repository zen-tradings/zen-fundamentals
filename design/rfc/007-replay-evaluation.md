# RFC-007: Replay Evaluation

Status: Discussion

Date: 2026-09-23

Depends on: RFC-004, RFC-005, RFC-006, RFC-008

## Problem

A merger-arb agent is only useful if its close probabilities are calibrated, its timing estimates are close, it finds the conditions that matter, and its citations hold up. None of that can be judged from one live deal, and live deals take months to resolve. Historical deals resolve instantly, but they have two traps:

1. **Look-ahead.** A replay that shows the agent a later filing, even through a cached extraction, measures nothing.
2. **Contamination.** The models may already know how a historical deal ended, from pretraining. A good score can mean the model remembered the answer rather than estimated it.

This RFC defines a dataset, a harness, contamination controls, metrics, baselines, and an output format. Together they let anyone rebuild the evaluation and check whether a reported number came from estimation.

No results exist yet. Every number below is a selection criterion, a configuration value, or a labeled **target**, never a measured result.

## 1. Dataset

### 1.1 Size and composition

40 US public-target deals with a known resolution.

| Stratum | Requirement |
|---|---|
| Terminated | ≥ 8 |
| Regulatory second request or equivalent | ≥ 8 |
| Completed | the remainder |
| Resolved after the latest evaluated model's stated training cutoff | **target:** ≥ 12 (see §3.1; may be infeasible for terminated deals, see open questions) |

The strata overlap: a terminated deal that received a second request counts toward both.

"Second request or equivalent" means any of:

- an FTC/DOJ HSR Second Request;
- European Commission Phase II;
- UK CMA Phase 2 reference;
- China SAMR simplified-procedure denial or extended review;
- a CFIUS investigation beyond initial review;

in each case as disclosed in the target's or acquirer's SEC filings or press releases.

### 1.2 Selection criteria (rebuildable)

The candidate pool is built only from free public data.

**Universe.** Targets that are SEC registrants listed on NYSE, NYSE American, or Nasdaq at announcement.

**Deal type.**

- Included: acquisition of 100% of the target's equity under a definitive agreement, by merger or tender offer, for cash, stock, or both.
- Excluded:
  - SPAC business combinations;
  - minority stake purchases;
  - mergers of equals where it is unclear which party is the target;
  - going-private transactions by a controlling holder (the dynamics differ);
  - bankruptcy §363 sales;
  - asset sales;
  - deals where a competing bid led to a different acquirer winning **and** the original agreement had not been terminated when the competing bid appeared. These are included instead as terminated deals for the original thesis, per RFC-008's definition.

**Size.** Transaction equity value ≥ US$500m at announcement, as stated in the announcement press release or 8-K.

> Trade-off: a size floor keeps deals with full proxy/S-4 disclosure and regulatory activity, at the cost of skewing toward deals the models are more likely to have seen discussed (a contamination risk; see §3).

**Window.** Announced between 2015-01-01 and the dataset freeze date. Resolved at least 30 days before the freeze.

**Enumeration.**

1. From EDGAR full-text search and the form-type indices, list every `PREM14A`, `DEFM14A`, `SC TO-T`, `SC 14D9`, and `S-4` (where the S-4 names a registrant target) filed in the window, plus every 8-K with Item 1.01 whose text contains "Agreement and Plan of Merger".
2. Group by target CIK and announcement 8-K accession number to get candidate deals.
3. Determine resolution from EDGAR. Completed = target 8-K Item 2.01, or Form 25 / Form 15 after closing. Terminated = 8-K Item 1.02 referencing the merger agreement.
4. Apply the inclusion and exclusion criteria above. Record each dropped candidate with a reason code in `pool_exclusions.csv`.

**Stratified sampling.**

- Label each pool deal: `resolution`, `second_request`, and `resolution_date` relative to each evaluated model's cutoff.
- Rank deals within each stratum by `sha256(seed || target_cik || announcement_accession)`, with the `seed` published in the manifest.
- Fill the stratum quotas in rank order, then fill the remainder from the rest of the pool in rank order.

> Trade-off: hash-ordered sampling is reproducible and hard to cherry-pick. It doesn't balance sector or era beyond the stated strata, so sector effects remain uncontrolled at n = 40.

**Reference set.** Pool deals that are **not** among the 40, and were resolved before the earliest announcement in the 40, form the reference set. Only this set is used to compute base rates (§5). The eval set's own outcomes never feed a baseline.

### 1.3 Per-deal record

Stored in `dataset/cases/<case_id>.json`:

| Field | Definition |
|---|---|
| `case_id` | Stable ID, `ma-<target_cik>-<announcement_accession>` |
| `target`, `acquirers` | Name, CIK, ticker |
| `announcement_as_of` | Earliest of: announcement press release wire timestamp, 8-K acceptance datetime |
| `timeline[]` | Every EDGAR filing by target or acquirer CIK from `announcement_as_of − 30d` through resolution, in the template's form set plus all 8-Ks: accession number, form, acceptance datetime, content hash |
| `press_releases[]` | Target and acquirer releases in the same window: source URL, archived copy hash, wire timestamp. Excluded if no verifiable timestamp. |
| `resolution` | `completed | terminated` |
| `resolution_date` | Completed: effective time per 8-K Item 2.01 or closing press release. Terminated: termination date per 8-K Item 1.02. |
| `resolution_evidence` | Accession number or URL of the resolving document |
| `final_conditions[]` | Canonical condition keys (RFC-008 vocabulary) with type and final status. Taken from the definitive proxy / S-4 / offer document, **plus** conditions added later (for example a consent decree or a CFIUS mitigation agreement). |
| `key_terms_at_signing`, `key_terms_final` | Consideration, per-share price, break fees, outside date (with extensions) |
| `second_request` | `{present, regime, disclosed_as_of}` |
| `labels_provenance` | Annotator IDs, adjudication notes |

**Labeling.** `final_conditions` and `key_terms_*` are labeled independently by two annotators following a written guide (`dataset/ANNOTATION.md`, planned). Disagreements are adjudicated by a third. Inter-annotator agreement is reported per field. No agreement figure is assumed in advance.

### 1.4 Frozen evidence corpus

The replay feeds a **frozen corpus**, never live sources: every `timeline` and `press_releases` document, normalized once by the production adapters, stored content-addressed with its `as_of`. The manifest lists every document hash, so a rebuilt corpus can be checked byte for byte.

- **Secondary web search is disabled in replay.** Historical web pages rarely have a trustworthy `as_of` and are often edited after the fact. The replay therefore measures the primary-source agent only. A live deployment that uses web search is not fully covered by this evaluation; that limitation is stated in every results table.
- **Amendments** are separate documents with their own `as_of`.

## 2. Replay harness

### 2.1 Procedure (per deal × configuration × repeat)

1. Create a thesis from the deal record (`subject`, `template: merger_arb@<pinned>`, `sources` pointing at the frozen corpus, `review: auto`).
2. Build the event stream: corpus documents sorted by `(as_of, accession)`. Documents with identical `as_of` form one event.
3. Set `clock = announcement_as_of`. Run the initial evaluation (`trigger: initial`) with everything with `as_of ≤ clock` visible.
4. For each subsequent event: advance `clock` to the event's `as_of`, apply the production debounce **in virtual time**, and run the evaluation job exactly as in production (RFC-005).
5. Stop after the event that contains `resolution_evidence`. Evaluations at or after that event are recorded but **not scored**.
6. Record every ThesisVersion, EvaluationRecord, ReviewPacket, and telemetry row.

> Trade-off: applying debounce in virtual time makes replay faithful to production batching, but it produces fewer checkpoints than scoring every single document. We score what production would have produced.

### 2.2 What is scored at a checkpoint

A **checkpoint** is the announcement plus every subsequent event before resolution.

- **Primary:** the head, i.e. the latest auto-approved ThesisVersion at that clock. This is what a user would have relied on.
- **Secondary:** the latest *proposed* values, including those in `below_threshold` EvaluationRecords. The gap between primary and secondary shows how much accuracy the material-change gate trades for less review load.

### 2.3 Point-in-time enforcement (three layers)

1. **Store:** the corpus view is queried with `as_of ≤ clock`.
2. **Context builder:** the RFC-005 assertion before every model call.
3. **Post-run audit:** for every version, re-check `max(as_of of evidence_set) ≤ clock` and every citation's `as_of ≤ clock`.

**Canaries.** Each deal's corpus contains ≥ 1 synthetic document with `as_of` after resolution, carrying a unique canary string. If a canary appears in any model input (checked in the harness, which can see content) or in any output, that is a violation.

A violation found by any layer invalidates the run for that configuration: it is marked `invalid` and excluded from every table, and the violation count is reported. The required count is **zero**.

### 2.4 Isolation and determinism

- No network access except model provider endpoints. No fetch or search tools in any lane.
- Model IDs, prompts, template versions, and the price table are pinned and hashed into the run manifest.
- Temperature 0 where the provider supports it. **target:** 3 repeats per deal per configuration. Report the mean and the between-repeat spread.
- The system prompt tells the model the current date is `clock` (named runs) or the shifted clock (anonymized runs, §3.2).

### 2.5 Run manifest

`run_id`, git SHA, template version, corpus manifest hash, dataset version, for each role `{provider, model_id, stated_training_cutoff, cutoff_source_url}`, seeds, repeats, price table, harness version.

## 3. Contamination

Models may already know how a historical deal resolved. All three mitigations are required, and the headline uses only runs that pass them.

### 3.1 Cutoff split

- For each configuration, `effective_cutoff = max(stated_training_cutoff)` over **every** model that sees deal-identifying content (planner, estimator, extractor, auditor).
- Each deal is `post_cutoff` if `resolution_date > effective_cutoff + guard_band`, `pre_cutoff` if `resolution_date < effective_cutoff − guard_band`, and `guard_band` otherwise. `guard_band` = 90 days (a configuration value).
- Results are reported separately for `pre_cutoff` and `post_cutoff`. Guard-band deals appear only in the exclusions list.

> Trade-off: taking the max cutoff across roles is conservative, since one model with a recent cutoff shrinks the post-cutoff set for the whole configuration. The guard band hedges against stated cutoffs being imprecise, at the cost of dropping deals near the boundary.

Limitation: splitting on *resolution* date controls outcome leakage. It does not control leakage of intermediate events, such as a model knowing a second request came before the replay reaches it. The anonymized variant (§3.2) partly addresses this.

### 3.2 Anonymized variant

Each deal's corpus is transformed into an anonymized twin, stored as a **separate evidence namespace** with its own IDs and its own extraction cache, so nothing from the named corpus leaks through cached extractions.

| Element | Transform |
|---|---|
| Company names, subsidiaries, brands, products | Consistent placeholders (`TARGET_CO`, `ACQUIRER_CO`, `ACQUIRER_SUB_1`, `PRODUCT_A`) |
| Tickers, CIKs, CUSIPs, LEIs, addresses, phone numbers, URLs | Placeholders |
| People (executives, advisors, law firms, banks) | Role placeholders (`TARGET_CEO`, `ACQUIRER_COUNSEL`) |
| Monetary amounts, share counts, per-share prices | Multiplied by a per-deal secret factor `k ∈ [0.5, 2.0]`. This keeps ratios intact: premium, break fee as a % of equity value, exchange ratios. |
| Dates | Shifted by a per-deal secret offset of whole weeks, which preserves weekdays and all intervals (HSR waiting periods, outside-date spacing) |
| Sector | Kept at GICS industry-group level (antitrust risk depends on it) |
| Regulators and statutes | Kept (HSR, EC, CMA, CFIUS). They are needed to reason about conditions. |

Pipeline: deterministic replacement from a per-deal entity table → a model-assisted pass to catch residual identifiers → a **leak check** that runs regexes for every original name, ticker, CIK, and exact original monetary figure. A document with any leak-check hit is dropped. If a dropped document is on the resolution path or in `final_conditions` sourcing, the deal's anonymized run is excluded.

Ground-truth labels are transformed with the same table. Scores are computed in the transformed space and dates are un-shifted before reporting.

> Trade-off: anonymization removes real signal. An acquirer's antitrust history, or a known political sensitivity, legitimately affects close probability, so anonymized scores are expected to understate true capability. Named post-cutoff runs keep that signal but have fewer deals. We report both, and neither alone is the whole picture.

### 3.3 Knowledge probe

For each deal and each model in the configuration, before any replay:

- **Named probe:** "The acquisition of `<target>` by `<acquirer>` was announced on `<date>`. Did it complete or terminate, and on what date? Answer `unknown` if you do not know." 5 samples at the provider's default temperature.
- **Re-identification probe** (anonymized variant): give the anonymized announcement press release and ask "Which real transaction is this, and how did it resolve?" 5 samples.

**Flagging.** A single "completed" answer is right by chance at roughly the completion base rate, so a correct outcome alone is weak evidence. A deal is flagged `known_outcome` for a model if a majority of samples:

- correctly say `terminated` for a terminated deal; or
- correctly say `completed` **and** give a completion date within ±31 days; or
- name a specific resolution detail that appears in the resolution evidence (for example the stated reason for termination).

The anonymized twin is flagged `reidentified` if a majority of samples name the correct target or acquirer.

Consequences:

- A `known_outcome` deal is excluded from **named** headline runs even if it is post-cutoff, because stated cutoffs can be wrong.
- A `reidentified` deal is excluded from **anonymized** headline runs.
- All flags are listed in the exclusions output.

### 3.4 Headline rule

Headline numbers come only from:

- **H-named:** named runs on `post_cutoff` deals that are not `known_outcome` for any model in the configuration;
- **H-anon:** anonymized runs on deals that are not `reidentified` for any model in the configuration.

H-named and H-anon are reported as **separate rows** and never pooled.

The `pre_cutoff` named row is reported as a **contamination diagnostic**. The paired difference between pre-cutoff named and anonymized scores on the same deals estimates how much memorization inflates named results.

## 4. Metrics

Unless stated otherwise, each deal is weighted equally: a metric is averaged over a deal's checkpoints first, then across deals. Confidence intervals are 95% deal-level bootstrap intervals (resampling deals, 10,000 resamples). Comparisons between configurations use **paired** bootstrap over the same deals.

> Trade-off: weighting deals equally stops long, filing-heavy deals from dominating. It also means one short deal counts as much as one with 60 checkpoints.

| Metric | Definition |
|---|---|
| **Brier@announcement** | `(p − y)²` at the initial version, where `y = 1` if completed. Mean over deals. |
| **Brier@checkpoints** | Mean `(p − y)²` over all scored checkpoints per deal, then across deals |
| **Brier by phase** | Brier at checkpoints bucketed by the fraction of deal life elapsed (0–25%, 25–50%, 50–75%, 75–100%), and at "first checkpoint after second-request disclosure" |
| **Brier skill score** | `1 − Brier / Brier(base rate)` |
| **Calibration table** | Pooled checkpoints, bins `[0, .5) [.5, .7) [.7, .85) [.85, .95) [.95, 1]`. Per bin: count of checkpoints, count of deals, mean p, observed completion rate. Uneven bins because estimates cluster high and 40 deals can't fill 10 equal bins. |
| **Close-date abs. error (days)** | `|expected_close_date − resolution_date|`, completed deals only. Median and mean, at announcement and over checkpoints, plus signed bias. |
| **Condition recall** | Share of `final_conditions` keys matched by the agent's `conditions` list, at announcement and at the last scored checkpoint. Matching is by canonical key (RFC-008). `other:*` conditions are matched by an annotator. Condition precision and status accuracy are reported alongside. |
| **Citation precision** | Share of ReviewPacket claims whose cited evidence supports them. Measured two ways: (a) an **eval judge** on all claims. This is a separate configuration from the pipeline auditor, so the pipeline never grades itself. (b) Humans on a stratified random sample, **target:** ≥ 150 claims per headline configuration, stratified by provenance. Judge–human agreement (Cohen's κ) is reported so readers can see how far to trust (a). |
| **PIT violations** | Count across the three layers plus canaries. Must be **0**. Any violation invalidates the run. |
| **Cost per version / per evaluation** | USD from content-free telemetry and the pinned price table. p50, p90. |
| **Latency per version** | Evaluation job start → commit, wall clock. p50, p90. |
| **Review load** | Versions per deal, and versions per deal-month |

The same definitions are used for `outcome_audit` feedback on live theses (RFC-008, feedback), so live and replay scores are comparable.

## 5. Baselines and ablations

All configurations run on the same dataset, the same corpus, the same seeds, and the same template version. Only the stated factor changes.

| ID | Configuration | Changes |
|---|---|---|
| B0 | Base rate | `close_probability` = the reference set's completion rate (constant). `expected_close_date` = announcement + the reference set's median announcement-to-close duration. `conditions` = the template default set (`vote:target_shareholders`, `regulatory:hsr`). No model calls. |
| F | Full system | Production routing (RFC-008) |
| A1 | Planner/estimator low-cost | Planner and estimator switched to the extractor-tier model; everything else as F |
| A2 | No auditor | Auditor role and repair loop disabled. Deterministic checks stay (they are code). Citation precision is still measured by the eval judge and humans. |
| G | Gate off (secondary scoring of F) | No new runs; scores F's proposed values (§2.2) |

B0 needs no contamination split, since it uses no model. It is reported against the same deal subsets as each headline row so the comparison is apples to apples.

**Power.** With 40 deals, ≥ 8 of them terminated, and exclusions shrinking the headline subsets further, CIs will be wide. Ablation differences may well not be distinguishable from zero. We report intervals and paired differences, and we make no significance claims beyond them.

## 6. Output

### 6.1 Results table

One table per evaluation run. Each row is one `(configuration, subset)`, and the subsets are `H-named`, `H-anon`, and `pre-cutoff-named (diagnostic)`. The row schema is [`eval-result-row.schema.json`](../schemas/eval-result-row.schema.json).

| config | subset | n_deals | n_checkpoints | Brier@ann [CI] | Brier@ckpt [CI] | BSS | date MAE@ann (d) | date MAE@ckpt (d) | cond recall@ann | cond recall@last | cite prec (judge) | cite prec (human, n) | κ judge–human | PIT viol. | $/version p50/p90 | latency p50/p90 | versions/deal |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B0 | H-named | | | | | | | | | | — | — | — | 0 | 0 | — | — |
| F | H-named | | | | | | | | | | | | | | | | |
| … | | | | | | | | | | | | | | | | | |

Calibration tables are attached to each row (`calibration[]` in the row schema).

### 6.2 Exclusions and flags

`exclusions.csv` has one line per `(case_id, configuration, variant)` with `reason`:

| reason | meaning |
|---|---|
| `guard_band` | resolution within ±90d of effective cutoff |
| `pre_cutoff` | excluded from headline, kept in diagnostic |
| `known_outcome:<model>` | named probe flagged |
| `reidentified:<model>` | anonymized probe flagged |
| `anonymization_leak` | a leak-check hit dropped a document the deal needed |
| `missing_as_of` | a timeline document had no verifiable timestamp and was needed |
| `corpus_incomplete` | a filing referenced in labels is missing from the corpus |
| `run_invalid:pit_violation` | the run was invalidated |
| `run_failed:<error>` | the harness could not complete the run |

`pool_exclusions.csv` (§1.2) lists every candidate dropped before sampling, with its reason.

## Open questions

- **Post-cutoff terminated deals may be scarce.** Frontier models' stated cutoffs are recent, terminations are rare, and deals take months to resolve. Meeting ≥ 8 terminated deals *within* H-named may be impossible, in which case the headline Brier on terminations rests mainly on H-anon. Should we let the dataset grow beyond 40 in the terminated stratum?
- **Market data.** Should replay add daily prices (spread-implied probability) as a baseline? It is the obvious practitioner benchmark, but it needs a licensed or reliably free historical price source.
- **Anonymization strength.** Is scaling monetary amounts by `k` enough, or will the combination of sector and relative size still re-identify famous deals often enough to hollow out H-anon? The re-identification probe will tell us, but only after the corpus is built.
- **Eval judge independence.** Should the eval judge come from a third provider, distinct from both the estimator and the auditor?
