# `merger_arb` Eval Spec (sketch)

Template: [`merger_arb`](template.yaml) (sketch, not shipped) · Harness: [RFC-007](../../rfc/007-replay-evaluation.md)

This outline shows that a post-announcement template fits the RFC-007 hooks without core changes. It is not a full spec.

| RFC-007 hook | Value for `merger_arb` |
|---|---|
| Case | one announced US public-target deal, from the announcement to completion or termination |
| Cluster unit | the deal |
| Selection | EDGAR full-text and form-type indices (`PREM14A`, `DEFM14A`, `SC TO-T`, `SC 14D9`, `S-4`, 8-K 1.01 "Agreement and Plan of Merger"); equity value ≥ US$500m |
| Strata | terminated; regulatory second request or equivalent; completed |
| Outcome-revealing interval | announcement to resolution |
| Probe | "Did the acquisition of `<target>` by `<acquirer>`, announced on `<date>`, complete or terminate, and when?" A correct "completed" counts only with a date within ±31 days or a specific detail. |
| Anonymization keeps | GICS industry group, regulators and statutes |
| Metrics (registry) | `scenarios`: multi-class Brier, value error; `close_probability`: Brier, BSS, calibration (bins `[0, .5) [.5, .7) [.7, .85) [.85, .95) [.95, 1]`); `expected_close_date`: absolute error; `conditions`: recall, precision, status accuracy; paired difference vs. market-implied |
| Baselines | B0 base rate (reference-set completion rate, median duration, default conditions); B1 market-implied `mi-1` |
| Distractors | irrelevant releases; stale items re-dated as news; false rumors ("DOJ preparing a suit", "rival bidder circling"), not within ±7 days of a real event of the same kind |
| Template error classes | `term_arithmetic`, `completed_value_vs_consideration`, `date_before_outside_date`, `condition_consistency` |
| Template exclusions | `missing_prices` (excluded from B1 and value error) |
