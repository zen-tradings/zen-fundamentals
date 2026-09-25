# RFC-007: Replay Evaluation

Status: Discussion

Date: 2026-09-23 (revised 2026-09-24: split into this core harness and per-template eval specs)

Depends on: RFC-004, RFC-005, RFC-006, RFC-009

## Problem

A template's estimates are only useful if they are calibrated, rank the eventual outcome well before it happens, find the facts that matter, and cite evidence that holds up. None of that can be judged from one live thesis, and live theses take months to resolve. Historical cases resolve instantly, but they have two traps that apply to every template:

1. **Look-ahead.** A replay that shows the agent a later document, even through a cached extraction, measures nothing.
2. **Contamination.** The models may already know how a historical case ended, from pretraining. A good score can mean the model remembered the answer rather than estimated it.

This RFC defines the **core harness**: what every template's eval spec must provide, how cases are replayed, how look-ahead and contamination are controlled, the core metrics, the core configurations, the robustness mechanics, and the output format. Each template's `eval.md` fills in the dataset, labels, metrics, and baselines (RFC-009). The first is [`templates/neocloud_deal/eval.md`](../templates/neocloud_deal/eval.md).

No results exist yet.

## 1. Dataset requirements

Every template eval spec defines its dataset. The core requires:

### 1.1 Case and cluster unit

A **case** is one thesis subject over one replay span: a start (the initial clock) and a full-resolution rule, taken from the template's `outcomes`. The spec names a **cluster unit** (for example a target company or a deal). Confidence intervals resample cluster units, because cases of the same unit are correlated.

### 1.2 Rebuildable selection

- The candidate pool is built only from public data, by published queries or rules, with every dropped candidate recorded with a reason in `pool_exclusions.csv`.
- Membership must be decidable from documents dated **before** the case starts, so the pool can't favor cases because of how they ended.
- Stratified sampling ranks pool cases within each stratum by `sha256(seed || case_key)`, with the `seed` published in the manifest, then fills stratum quotas in rank order.
- A **reference set** of pool cases that are not in the eval set, and that resolved before the earliest eval case starts, is the only source for base rates and for fitting any baseline weights. The eval set's own outcomes never feed a baseline.

> Trade-off: hash-ordered sampling is reproducible and hard to cherry-pick. It balances only the stated strata, so other effects (sector, era) remain uncontrolled at small n.

### 1.3 Per-case record

Stored in `dataset/cases/<case_id>.json`. Core fields: `case_id`, `subject`, the replay span, `timeline[]` (every document in the corpus with its `as_of` and content hash), `resolution` and `resolution_date` with `resolution_evidence`, the template's outcome labels, point-in-time labels for any list quantity the spec scores (so "active at clock `t`" can be computed), and `labels_provenance`.

**Labeling.** Scored labels are labeled independently by two annotators following a written guide, adjudicated by a third. Inter-annotator agreement is reported per field (and per label set, for descriptive labels). No agreement figure is assumed in advance.

### 1.4 Frozen evidence corpus

The replay feeds a **frozen corpus**, never live sources: every case document, normalized once by the production adapters, stored content-addressed with its `as_of`. The manifest lists every document hash, so a rebuilt corpus can be checked byte for byte.

- **News `as_of`.** A news item's `as_of` is the **later** of its stated publication time and its first capture in a public web archive, and the corpus stores the earliest captured version of the text. An article with no capture before resolution is dropped.
- **Open web search is disabled in replay.** Historical web pages rarely have a trustworthy `as_of`. A live deployment that uses web search is not fully covered by any replay; every results table says so.
- **Amendments** are separate documents with their own `as_of`.
- **Prices**, for templates that use market data, enter as one evidence item per ticker per trading day with `as_of` = that session's official close. A filing accepted at 10:00 therefore sees the previous day's close.

> Trade-off: the archive rule can make an article visible later than it really appeared, which biases timing metrics against the agent. We accept that because the opposite error, a re-dated article leaking the future, would invalidate the run.

## 2. Replay harness

### 2.1 Procedure (per case × configuration × repeat)

1. Create a thesis from the case record (`subject`, `template: <id>@<pinned>`, `sources` pointing at the frozen corpus, `review: auto`). Auto-approval follows RFC-004: for templates that opt in to the `secondary_only` audit, rumor-only audit failures are approved as `replay_auto` overrides; any other audit failure leaves the head unchanged.
2. Build the event stream: corpus documents sorted by `(as_of, id)`. Documents with identical `as_of` form one event. Add the template's scheduled re-estimates **in virtual time**, skipping any within the cadence of a real evaluation.
3. Set `clock` to the case start. Run the initial evaluation (`trigger: initial`) with everything with `as_of ≤ clock` visible.
4. For each subsequent event: advance `clock` to the event's `as_of`, apply the production debounce in virtual time, and run the evaluation job exactly as in production (RFC-005).
5. Partial resolutions (template-defined) are committed and the replay continues.
6. Stop after the event that contains full-resolution evidence, or at the end of the span. Evaluations at or after the resolving event are recorded but **not scored**.
7. Record every ThesisVersion, EvaluationRecord, ReviewPacket, and telemetry row.

> Trade-off: applying debounce and scheduled re-estimates in virtual time makes replay faithful to production, but it produces fewer checkpoints than scoring every document. We score what production would have produced.

### 2.2 What is scored at a checkpoint

A **checkpoint** is the initial evaluation plus every subsequent event and scheduled re-estimate before resolution.

- **Primary:** the head, i.e. the latest auto-approved ThesisVersion at that clock. This is what a user would have relied on.
- **Secondary:** the latest *proposed* values, including those in `below_threshold` EvaluationRecords. The gap between primary and secondary shows how much accuracy the material-change gate trades for less review load.

A key of a `probability_map` quantity stops being scored once it resolves.

### 2.3 Point-in-time enforcement (three layers)

1. **Store:** the corpus view is queried with `as_of ≤ clock`.
2. **Context builder:** the RFC-005 assertion before every model call.
3. **Post-run audit:** for every version, re-check `max(as_of of evidence_set) ≤ clock` and every citation's `as_of ≤ clock`.

**Canaries.** Each case's corpus contains ≥ 1 synthetic document with `as_of` after resolution, carrying a unique canary string (the eval spec gives a realistic example). If a canary appears in any model input (checked in the harness, which can see content) or in any output, that is a violation.

A violation found by any layer invalidates the run for that configuration: it is marked `invalid` and excluded from every table, and the violation count is reported. The required count is **zero**.

### 2.4 Isolation and determinism

- No network access except model provider endpoints. No fetch or search tools in any lane.
- Model IDs, prompts, template versions, baseline weights, and the price table are pinned and hashed into the run manifest.
- Temperature 0 where the provider supports it. **target:** 3 repeats per case per configuration. Report the mean and the between-repeat spread.
- The system prompt tells the model the current date is `clock` (named runs) or the shifted clock (anonymized runs, §3.2).

### 2.5 Run manifest

`run_id`, git SHA, template id and version, corpus manifest hash, dataset version, the spec's pinned extras (for example a candidate list or a weight table hash), for each role `{provider, model_id, stated_training_cutoff, cutoff_source_url}`, seeds, repeats, price table, harness version.

## 3. Contamination

All three mitigations are required, and headline numbers use only runs that pass them.

### 3.1 Cutoff split

- For each configuration, `effective_cutoff = max(stated_training_cutoff)` over **every** model that sees case-identifying content (planner, estimator, extractor, auditor).
- Each template eval spec defines the case's **outcome-revealing interval**: the span in which any event could reveal the outcome (for example the whole horizon window, or announcement to resolution). A case is `post_cutoff` if that interval starts after `effective_cutoff + guard_band`, `pre_cutoff` if it ends before `effective_cutoff − guard_band`, and excluded from headline rows otherwise. `guard_band` = 90 days (a configuration value).
- Results are reported separately for `pre_cutoff` and `post_cutoff`.

> Trade-off: taking the max cutoff across roles is conservative, since one model with a recent cutoff shrinks the post-cutoff set for the whole configuration. The guard band hedges against stated cutoffs being imprecise.

### 3.2 Anonymized variant

Each case's corpus is transformed into an anonymized twin, stored as a **separate evidence namespace** with its own IDs and its own extraction cache, so nothing leaks through cached extractions.

Core transforms, which every template applies: subject parties, other companies, people, identifiers (tickers, CIKs, CUSIPs, addresses, URLs) → consistent placeholders; monetary amounts and other scale figures → multiplied by a per-case secret factor `k ∈ [0.5, 2.0]` (ratios preserved); dates → shifted by a per-case secret whole number of weeks (weekdays and intervals preserved). The eval spec gives the full table, including what it deliberately **keeps** because the question depends on it (for example a sector, a regulator, or a party's type).

Pipeline: deterministic replacement from a per-case entity table → a model-assisted pass to catch residual identifiers → a **leak check** that runs regexes for every original name, identifier, and exact original figure. A document with any leak-check hit is dropped. If a dropped document is on the resolution path or supports a scored label, the case's anonymized run is excluded. Labels are transformed with the same table, scores are computed in the transformed space, and dates are un-shifted before reporting.

> Trade-off: anonymization removes real signal (a party's history legitimately affects the estimate), so anonymized scores are expected to understate capability. Named post-cutoff runs keep that signal but have fewer cases. We report both.

### 3.3 Knowledge probe

For each case and each model, before any replay:

- **Named probe:** the eval spec's question about how the case resolved, with "answer `unknown` if you do not know". 5 samples at the provider's default temperature.
- **Re-identification probe** (anonymized variant): give an anonymized document from early in the case and ask which real case it is. 5 samples.

The eval spec defines when a majority of samples counts as `known_outcome` (named) or `reidentified` (anonymized). A correct answer that could be right by chance (for example the most common outcome) must require a specific supporting detail to count.

Consequences:

- A `known_outcome` case is excluded from **named** headline runs even if it is post-cutoff, because stated cutoffs can be wrong.
- A `reidentified` case is excluded from **anonymized** headline runs.
- All flags are listed in the exclusions output.

### 3.4 Headline rule

Headline numbers come only from:

- **H-named:** named runs on `post_cutoff` cases that are not `known_outcome` for any model in the configuration;
- **H-anon:** anonymized runs on cases that are not `reidentified` for any model in the configuration.

H-named and H-anon are reported as **separate rows** and never pooled. The `pre_cutoff` named row is a **contamination diagnostic**: the paired difference between pre-cutoff named and anonymized scores on the same cases estimates how much memorization inflates named results.

## 4. Metrics

Unless stated otherwise, each case is weighted equally: a metric is averaged over a case's checkpoints first, then across cases. Confidence intervals are 95% bootstrap intervals **clustered by the spec's cluster unit** (10,000 resamples). Comparisons between configurations use **paired** bootstrap over the same units.

### 4.1 Metric registry (by quantity type)

Eval specs pick from these families, one or more per scored quantity (RFC-009 quantity types):

| Quantity type | Metric families |
|---|---|
| `probability`, `derived_probability` | Brier, Brier skill score vs. a base-rate baseline, log loss (probabilities floored at 0.001), calibration table |
| `outcome_distribution` | multi-class log loss and Brier; rank of the realized key, top-k hit rate; lead time with false-alarm rate |
| `probability_map` | binary Brier and log loss per scored key; rank and top-k among keys; lead time with false-alarm rate |
| `scenario_set` | multi-class Brier over outcomes; relative value error for the realized outcome |
| `date_estimate` | absolute error (days), signed bias; reported without a CI when fewer than 5 cases qualify |
| `condition_list`, `relationship_list` | recall and precision by canonical key against point-in-time labels; status accuracy; label accuracy (reported next to annotator agreement) |
| any quantity with a comparison baseline | paired difference, agent minus baseline, on the same checkpoints |

Calibration bins are set by the spec, because the useful range differs by template (low, uneven bins for rare events; high bins for mostly-completing outcomes).

**Lead time** always comes with its **false-alarm rate**, since lead time alone rewards alarming on everything.

### 4.2 Core metrics (every template)

| Metric | Definition |
|---|---|
| **Citation precision** | Share of ReviewPacket claims whose cited evidence supports them. Measured two ways: (a) an **eval judge** on all claims, a separate configuration from the pipeline auditor so the pipeline never grades itself; (b) humans on a stratified random sample, **target:** ≥ 150 claims per headline configuration, stratified by provenance and tier. Judge–human agreement (Cohen's κ) is reported. |
| **PIT violations** | Count across the three layers plus canaries. Must be **0**. Any violation invalidates the run. |
| **Cost per version / per evaluation** | USD from content-free telemetry and the pinned price table. p50, p90. Scheduled re-estimates reported separately. |
| **Latency per version** | Evaluation job start → commit, wall clock. p50, p90. |
| **Review load** | Versions per case, versions per case-month, overrides per case (including `replay_auto`, each of which would be a human decision live), and versions left unapproved because of other audit failures |

**Provider-conflict split.** Every row is also reported split by whether any role's provider is a party named in the subject (RFC-009), for the quantities involving that party.

The same definitions score `outcome_audit` feedback on live theses (RFC-004 §Feedback), so live and replay scores are comparable.

## 5. Configurations

All configurations run on the same dataset, the same corpus, the same seeds, and the same template version. Only the stated factor changes.

| ID | Configuration | Changes |
|---|---|---|
| F | Full system | The template's production routing |
| A1 | Planner/estimator low-cost | Planner and estimator switched to the extractor-tier model; everything else as F |
| A2 | No auditor | Auditor role and repair loop disabled. Deterministic checks stay. Citation precision is still measured by the eval judge and humans. |
| G | Gate off (secondary scoring of F) | No new runs; scores F's proposed values (§2.2) |

Every eval spec adds at least a **base-rate baseline** (B0, no model calls, from the reference set) and its **comparison baseline** (B1, the template's baseline formula), and may add further ablations. A baseline that uses model extractions is reported against the same case subsets as each headline row.

**Power.** Eval sets are small. We report intervals and paired differences and make no significance claims beyond them.

## 6. Robustness variants

These variants reuse the F configuration and the headline subsets. Each noisy or faulty run is **paired** with the clean F run that has the same seed. Their scores are separate rows (`variant` column), never mixed into clean headline rows.

### 6.1 Noise robustness (distractor evidence)

Distractors are injected into the replay event stream at seeded random positions. Each gets `as_of` equal to its injection point, so point-in-time rules still hold. The harness knows every distractor ID; the agent does not. The eval spec defines the distractor types (at least an irrelevant primary document, a stale item re-dated as news, and a false material rumor), per-case targets, and **collision rules** that keep a distractor away from a real event of the same kind, so ground truth stays unambiguous.

| Metric | Definition |
|---|---|
| **Distractor-induced change rate** | Share of distractor events after which the noisy run's head differs **materially** (template thresholds) from the paired clean head at the same clock, counted only when the next checkpoint's ImpactAssessment or `caused_by` includes the distractor |
| **Distractor-induced drift** | The same comparison with no materiality threshold, using the spec's drift measures, over the 3 checkpoints after the distractor |
| **Distractor citation rate** | Share of ReviewPackets after a distractor that cite it: (a) in support of a change, (b) only in `uncertain_items` or `conflicts`. For templates that opt in to `secondary_only`, (a) without the flag must be **0**. |
| **Noisy − clean** | Paired difference in the spec's primary metric |

> Trade-off: synthetic distractors are only as realistic as their templates. A low induced-change rate shows robustness to *our* distractors, not to every one. Distractor templates are published with the dataset.

### 6.2 Self-check catch rate (injected errors)

A mutation hook alters the estimator's candidate **after** estimation and **before** self-check, invisibly to the model. Each mutated evaluation gets exactly one error; the clean paired run is the reference.

Core error classes, every template:

| Error class | Mutation | Expected catcher |
|---|---|---|
| `type_invariant` | Break a quantity-type invariant (a distribution no longer sums to 1, a derived value no longer matches its source, a resolved key not at 0 or 1) | self-check (code) |
| `missing_citation` | Remove all citations from one changed quantity | self-check (code) |
| `future_citation` | Add a citation to a canary document with `as_of > clock` | self-check (code). Recorded as `injected`; it does **not** count as a PIT violation **provided it is caught before commit**. If it reaches commit, it is a real violation. |
| `wrong_citation` | Swap a citation's `evidence_id` for an unrelated item in the evidence set | self-check (model), then auditor |
| `unflagged_secondary` | Remove the `secondary_only` flag from a change supported only by secondary evidence (opt-in templates) | audit (code) |

The eval spec adds template classes for its own self-checks. Metrics:

- **Self-check catch rate** = errors detected by self-check / errors injected, per class and overall.
- **Downstream catch rate** = errors the self-check missed but the auditor caught / errors the self-check missed.
- **Escape rate** = errors that reached a committed version without being flagged / errors injected. Target **0** for code-checkable classes.

Code-checkable classes are regression tests of the harness and checks, not evidence of model quality.

### 6.3 Recovery rate (injected tool failures)

A fault-injection layer in the MCP tool proxy and the model router injects failures at seeded points. **Target:** ≥ 1 fault per case per class.

| Fault class | Injection |
|---|---|
| `fetch_5xx` / `fetch_timeout` | Source adapter returns 503 or hangs past its timeout for N attempts (N drawn from {1, 2, 5}, so some faults exceed the retry budget) |
| `rate_limited` | 429 with `Retry-After` |
| `malformed_document` | Truncated or corrupted HTML for a document |
| `extractor_malformed` | Extractor returns non-schema JSON |
| `extractor_timeout` | Extractor route times out |
| `route_outage` | A role's primary provider is unavailable for the whole evaluation |

Metrics:

- **Recovery rate** = faults after which the evaluation completed **and** the head matches the paired clean run within the template's material thresholds / faults injected.
- **Safe-failure rate** = unrecovered faults where the system failed closed (job held or failed, or the quantity flagged `extraction_unavailable`) / unrecovered faults.
- **Unsafe rate** = faults after which a version was committed that differs materially from clean **without** a recovery or uncertainty flag / faults injected. Target **0**.
- **Recording completeness** = injected faults that appear as `RecoveryEvent`s / faults injected. Target **1.0**.
- Added latency and cost per recovered fault, p50 / p90.

## 7. Output

### 7.1 Results table

One table per evaluation run. Each row is one `(configuration, variant, subset)`, with subsets `H-named`, `H-anon`, and `pre-cutoff-named (diagnostic)`. The row schema is [`eval-result-row.schema.json`](../schemas/core/eval-result-row.schema.json): core columns in `metrics`, template columns in `template_metrics` (validated against the template's metrics schema), calibration tables in `calibration[]`, and robustness results in `robustness`. A column that doesn't apply is `—` (`null` in JSON).

Core columns:

| config | variant | subset | n_units | n_cases | n_ckpt | *template columns* | cite prec judge / human (n) | κ | PIT viol. | $/version p50/p90 | latency p50/p90 | versions/case | overrides/case |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

Robustness columns (variant rows only): distractor change rate and citation rate by type, noisy − clean, self-check catch rate by class, downstream catch, escape rate, recovery rate, safe-failure, unsafe rate, recording completeness.

### 7.2 Exclusions and flags

`exclusions.csv` has one line per `(case_id, key?, configuration, variant)` with `reason`. Core reasons:

| reason | meaning |
|---|---|
| `guard_band` | the outcome-revealing interval overlaps `effective_cutoff ± guard_band` (a spec may name this differently) |
| `pre_cutoff` | excluded from headline, kept in diagnostic |
| `known_outcome:<model>` | named probe flagged |
| `reidentified:<model>` | anonymized probe flagged |
| `anonymization_leak` | a leak-check hit dropped a document the case needed |
| `missing_as_of` | a document had no verifiable timestamp and was needed |
| `corpus_incomplete` | a document referenced in labels is missing from the corpus |
| `run_invalid:pit_violation` | the run was invalidated |
| `run_failed:<error>` | the harness could not complete the run |
| `distractor_collision` | no collision-free slot for a required distractor type; the case is excluded from the noise variant |

Eval specs add template reasons. `pool_exclusions.csv` (§1.2) lists every candidate dropped before sampling, with its reason.

## Open questions

- **Eval judge independence.** Should the eval judge come from a third provider, distinct from both the estimator and the auditor?
- **Cross-template reporting.** When several templates ship, should there be a combined table of core metrics (citations, PIT, cost, review load) across templates, given that their headline metrics aren't comparable?
