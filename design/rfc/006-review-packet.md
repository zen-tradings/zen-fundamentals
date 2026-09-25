# RFC-006: ReviewPacket

Status: Discussion

Date: 2026-09-23

Depends on: RFC-004, RFC-005

## Problem

The old audit step was a fact and style check on prose. A reviewer approving a change to an acquisition-probability estimate needs something else. They need to see what changed, which evidence caused it, how trustworthy and how current that evidence is, and which parts a model actually read versus reasoned its way to. The reviewer should be able to approve or reject in minutes without re-reading the filings.

## Proposal

Every ThesisVersion has exactly one ReviewPacket, and it is immutable. Its layout comes from the template (RFC-008). Its structure is fixed by [`review-packet.schema.json`](../schemas/review-packet.schema.json).

### Contents

**Header.** Thesis, version `seq`, parent version, `clock`, template version, `spec_revision`, trigger, routing (provider and model for each role), audit status (`passed | failed | overridden`), and any degradations the budget forced (RFC-005).

**Changes.** One entry per changed quantity:

- `quantity`, `old_value`, `new_value`, typed `delta`, `material`, and the rule that fired;
- `claims[]`: the statements that justify the change (see below);
- `caused_by[]`: the evidence IDs that triggered re-estimation of this quantity. This comes from the ImpactAssessment and answers "the evidence that caused the change".

**Candidate tables.** For templates with a `candidate_distribution` or `probability_map` quantity (`neocloud_deal`), the packet shows per-candidate tables instead of only the headline probability. The acquirer table has one row per key (each candidate, `other`, `none`), with old and new probability, old and new rank, the absolute and log-odds deltas, and the claims behind each row. The derived `p_acquired` appears beneath it as a `computed` claim, with the formula shown. The stake table has one row per candidate with old and new probability and the resolved flag. A reviewer can then see *why* the headline moved. For example, `p_acquired` may have held steady while probability shifted from one AI lab to a hyperscaler.

**Reference-prior comparison.** Next to each agent probability, the packet shows the template's `reference_prior` at the same `clock`, the extracted relationships it used, and the formula version (RFC-008). An odds ratio on `p_acquired` beyond the template's `prior_gap_flag` (default 3.0, a starting point to be tuned), or a different top-ranked candidate, is listed automatically as an investor judgment item: "Agent and reference prior disagree; which view do you hold?" The prior is context for the reviewer. It is not a claim the agent makes, and it is not audited as one.

**Self-check.** The estimator's self-check result (RFC-005 step 8): each check, pass or fail, whether a revision happened, and what changed in the revision.

**Recoveries.** Every `RecoveryEvent` in this evaluation. A reviewer sees, for example, that an S-1 was extracted by the alternate extractor route after the primary one timed out, and can weight that section accordingly.

**Unchanged quantities.** Listed with `carried_forward: true` or "re-estimated, no change", so a reviewer can see the agent didn't silently skip anything.

**Conflicts.** For each reconciled disagreement: the claims on each side, their evidence, and how the estimator resolved it.

**Uncertain items.** Claims or quantities that the estimator, or the auditor, flagged as uncertain, each with a reason. Changes supported only by secondary evidence always appear here with reason `secondary_only` (RFC-008 *Rumor handling*).

**Investor judgment items.** Questions the model recommends a human decide. Each has `question`, `why` (why this is judgment rather than fact), `related_quantities`, and optional `considerations`. Examples from `neocloud_deal`: whether a reported-talks item is credible, and whether a candidate would rather keep buying capacity by contract than buy the company.

**Evidence appendix.** Every evidence item cited anywhere in the packet, with `source`, `tier` (`primary` / `secondary`), `doc_type`, `as_of`, URL or accession number, and content hash.

**Audit summary.** Checks run, failures, the repair attempt (if any), and whether the packet was selected for human spot-checking (RFC-007).

### Claims and provenance

A claim is one atomic statement, for example "The target's largest customer accounted for 41% of revenue in fiscal 2026" or "Given that concentration, the customer is the most likely acquirer among the candidates". Each claim carries:

| Field | Meaning |
|---|---|
| `text` | The statement |
| `quantity` | Which tracked quantity it supports |
| `provenance` | `extracted`, `computed`, or `inferred` (below) |
| `model` | `{provider, model_id, role}` that produced it; null for `computed` |
| `citations[]` | `{evidence_id, locator, quote}`. The locator is a section, page, or character span. The quote is the exact supporting text. |
| `audit` | `{citation: supported | partial | unsupported | not_checked, provenance_ok: bool, as_of_ok: bool, auditor: {provider, model_id}}` |
| `uncertain` | `{flagged: bool, by: estimator | auditor, reason}` |

Provenance definitions:

- **extracted**: read directly from evidence. The cited quote entails the claim with at most normalization (date formats, units, currency symbols). Produced by the extractor role, or by the estimator when it quotes directly.
- **computed**: produced by deterministic code from extracted claims, with no model involved. Examples: days left in the horizon, or a contract's value as a percentage of the target's backlog. The formula and its inputs are recorded.
- **inferred**: anything a model concluded beyond what the text says, including combining sources, forecasting, and judging likelihood. It always names the model and role.

The auditor checks the labels. A claim labeled `extracted` whose quote doesn't entail it is **downgraded** to `inferred` and flagged `uncertain` (`by: auditor`). It is never upgraded.

> Trade-off: a three-way label is coarser than a full argument graph, but a reviewer can scan it. A graph would show *how* inferences chain together, at the cost of a packet nobody reads in minutes. We store the claim → citation links needed to build a graph later, and don't render one.

### Audit checks

| Check | Who | On failure |
|---|---|---|
| Every cited `evidence_id` is in the version's `evidence_set` | code | hard fail, no commit |
| Every cited evidence `as_of ≤ clock` | code | hard fail: `point_in_time_violation` (RFC-005) |
| Dates *stated in* claims (for example "as of the June 5 10-Q") match the cited evidence's as_of or content | auditor model | claim flagged, `as_of_ok: false` |
| Quote exists verbatim at the locator | code | citation `unsupported` |
| Quote supports the claim | auditor model | `partial` / `unsupported`, one estimator repair, then flagged |
| `extracted` label justified | auditor model | downgrade to `inferred` |
| Every changed quantity has at least one claim with a primary-tier citation, or is flagged uncertain | code | packet `audit: failed` |
| A changed quantity whose claims cite only secondary-tier evidence is flagged `secondary_only` (templates that opt in, such as `neocloud_deal`) | code | flag added; packet `audit: failed`, so approval needs an override (RFC-008 *Rumor handling*) |

The auditor runs on a low-cost model **from a different provider than the estimator** (RFC-008). If no model satisfying that constraint is available, the job is held, fail-closed, rather than audited by the same provider.

> Trade-off: models from the same provider share training data and failure modes, so a same-provider auditor tends to agree with the estimator's mistakes. Using a different, cheaper provider buys independence at the cost of a weaker judge. We limit the auditor to narrow, checkable questions (does this quote support this claim) where a cheap model does well, and we measure auditor–human agreement in RFC-007.

### Approval rules

- `audit: passed` → `approve` allowed.
- `audit: failed` → `approve` requires an `override_reason`, recorded in `review_events`, and the packet shows `audit: overridden` in any later view.
- A point-in-time violation never reaches review, because the job fails before commit.

### Rendering

The packet is JSON. `GET /v1/versions/:id/review-packet?format=md` renders it with the template's layout, in the template's section order. Rendering is presentation only: it reads the stored JSON and never calls a model.

## Open questions

- Should `partial` citations block approval like `unsupported`, or only be flagged?
- How should the packet show evidence that is *absent*? For example, a candidate's 10-K no longer mentions the target as a supplier, and that absence is itself informative. Is "absence" a claim type with no citation?
