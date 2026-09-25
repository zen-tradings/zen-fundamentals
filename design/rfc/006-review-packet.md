# RFC-006: ReviewPacket

Status: Discussion

Date: 2026-09-23 (revised 2026-09-24: template-agnostic, RFC-009)

Depends on: RFC-004, RFC-005

## Problem

The old audit step was a fact and style check on prose. A reviewer approving a change to a probability estimate needs something else. They need to see what changed, which evidence caused it, how trustworthy and how current that evidence is, and which parts a model actually read versus reasoned its way to. The reviewer should be able to approve or reject in minutes without re-reading the filings.

## Proposal

Every ThesisVersion has exactly one ReviewPacket, and it is immutable. Its layout comes from the template's `packet_layout` (RFC-009). Its structure is fixed by [`review-packet.schema.json`](../schemas/core/review-packet.schema.json).

### Contents

**Header.** Thesis, version `seq`, parent version, `clock`, template version, `spec_revision`, trigger, routing (provider and model for each role, and a `provider_conflicts` entry for any role whose provider is also a party named in the subject, RFC-009), audit status (`passed | failed | overridden`), and any degradations the budget forced (RFC-005).

**Changes.** One entry per changed quantity:

- `quantity`, `old_value`, `new_value`, typed `delta`, `material`, and the rule that fired;
- `claims[]`: the statements that justify the change (see below);
- `caused_by[]`: the evidence IDs that triggered re-estimation of this quantity. This comes from the ImpactAssessment and answers "the evidence that caused the change".

**Sections.** Template-specific tables are **sections** from a fixed core list, bound to quantities and ordered by the template's `packet_layout` (RFC-009):

| Section kind | For quantity type | Shows |
|---|---|---|
| `distribution_table` | `outcome_distribution` | one row per key: old and new probability, old and new rank, absolute and log-odds deltas, baseline value, claims; derived quantities beneath as `computed` claims with the formula |
| `map_table` | `probability_map` | one row per key: old and new probability, resolved flag, labels, baseline value, claims |
| `scenario_table` | `scenario_set` | one row per outcome: old and new probability and value, claims |
| `list_changes` | `condition_list`, `relationship_list`, `signal_list` | added, removed, and changed items (status, value, labels, with the linked items that justify a label), then unchanged items collapsed; `secondary_only` items marked; subject parties with no item listed explicitly |
| `date_change` | `date_estimate` | old → new, interval, drivers |
| `facts_changes` | `facts` | changed fields only, then full facts collapsed |

A reviewer can then see *why* a headline moved, not just that it did. Example (`neocloud_deal`): `p_acquired` held steady while probability shifted from one AI lab to a hyperscaler; or an equity stake was re-labeled `vendor_financing` once a linked GPU supply agreement was disclosed.

**Baseline comparison.** Next to the agent's values, the packet shows the template's comparison baseline at the same `clock`, its inputs, and its formula version. A gap beyond the template's `gap_flag` is listed automatically as an investor judgment item: "Agent and baseline disagree; which view do you hold?" The baseline is context for the reviewer. It is not a claim the agent makes, and it is not audited as one. Example (`neocloud_deal`): the rule-based reference prior, flagged at an odds ratio of 3 on `p_acquired` or a different top-ranked candidate.

**Self-check.** The estimator's self-check result (RFC-005 step 8): each check, pass or fail, whether a revision happened, and what changed in the revision.

**Recoveries.** Every `RecoveryEvent` in this evaluation. A reviewer sees, for example, that an S-1 was extracted by the alternate extractor route after the primary one timed out, and can weight that section accordingly.

**Unchanged quantities.** Listed with `carried_forward: true` or "re-estimated, no change", so a reviewer can see the agent didn't silently skip anything.

**Conflicts.** For each reconciled disagreement: the claims on each side, their evidence, and how the estimator resolved it.

**Uncertain items.** Claims or quantities that the estimator, or the auditor, flagged as uncertain, each with a reason. For templates that opt in, changes supported only by secondary evidence always appear here with reason `secondary_only`.

**Investor judgment items.** Questions the model recommends a human decide. Each has `question`, `why` (why this is judgment rather than fact), `related_quantities`, and optional `considerations`. Templates add standard prompts (`judgment_prompts`, RFC-009). Example (`neocloud_deal`): whether a reported-talks item is credible, and whether a candidate would rather keep buying capacity by contract than buy the company.

**Evidence appendix.** Every evidence item cited anywhere in the packet, with `source` (including the outlet and its reliability for news), `tier` (`primary` / `secondary`), `doc_type`, `as_of` and how it was determined, URL or accession number, and content hash.

**Audit summary.** Checks run, failures, the repair attempt (if any), and whether the packet was selected for human spot-checking (RFC-007).

### Claims and provenance

A claim is one atomic statement. Example (`neocloud_deal`): "The target's largest customer accounted for 41% of revenue in fiscal 2026" or "Given that concentration, the customer is the most likely acquirer among the candidates". Each claim carries:

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
- **computed**: produced by deterministic code from extracted claims, with no model involved. Examples: days between two dates, or one extracted amount as a percentage of another. The formula and its inputs are recorded.
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
| Every changed quantity has at least one claim with a primary-tier citation, or is flagged uncertain. A change from a `scheduled` re-estimate satisfies this with the elapsed-time `computed` claim plus primary citations carried from the head (RFC-005 step 8) | code | packet `audit: failed` |
| A changed quantity whose claims cite only secondary-tier evidence is flagged `secondary_only` (templates that opt in via `audit.secondary_only`) | code | flag added; packet `audit: failed`, so approval needs an override |

The auditor runs on a low-cost model **from a different provider than the estimator**, a routing constraint every template keeps (RFC-009). If no model satisfying that constraint is available, the job is held, fail-closed, rather than audited by the same provider.

> Trade-off: models from the same provider share training data and failure modes, so a same-provider auditor tends to agree with the estimator's mistakes. Using a different, cheaper provider buys independence at the cost of a weaker judge. We limit the auditor to narrow, checkable questions (does this quote support this claim) where a cheap model does well, and we measure auditor–human agreement in RFC-007.

### Approval rules

- `audit: passed` → `approve` allowed.
- `audit: failed` → `approve` requires an `override_reason`, recorded in `review_events`, and the packet shows `audit: overridden` in any later view.
- In replay only, a version whose sole audit failure is `secondary_only` is auto-approved with `override_reason: replay_auto` (RFC-004).
- A point-in-time violation never reaches review, because the job fails before commit.

### Rendering

The packet is JSON. `GET /v1/versions/:id/review-packet?format=md` renders it with the template's layout, in the template's section order. Rendering is presentation only: it reads the stored JSON and never calls a model.

## Open questions

- Should `partial` citations block approval like `unsupported`, or only be flagged?
- How should the packet show evidence that is *absent*? For example, a filing no longer mentions a relationship it used to, and that absence is itself informative. Is "absence" a claim type with no citation? `list_changes` already lists parties with no item found; should that generalize?
