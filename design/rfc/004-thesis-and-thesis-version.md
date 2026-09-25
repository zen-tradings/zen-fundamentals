# RFC-004: Thesis and ThesisVersion Model

Status: Discussion

Date: 2026-09-23 (revised 2026-09-24: template-agnostic, RFC-009)

Depends on: RFC-001 (evidence vs. judgment), RFC-002 (lifecycles), RFC-003 (fencing)

## Problem

The product's core object used to be a newsletter: an audience, a cadence, and channels, producing articles. That doesn't fit a research agent whose job is to hold a view about a deal and keep it current. What we need to audit is **what the agent believed, when, and why**: what it estimated after a given filing, what evidence moved that, and whether a human approved it. (Example (`neocloud_deal`): which candidate it ranked as the likeliest acquirer of a neocloud after an SC 13D.) The prose around it matters much less.

## Proposal

### Thesis

A thesis is a long-lived, declarative spec for a view the agent maintains about one subject. It has five parts:

| Field | Meaning |
|---|---|
| `subject` | What the thesis is about, shaped by the template's subject schema (RFC-009). It names the parties that can appear as keys in outcome quantities. |
| `template` | `{id, version}` of the centrally maintained template it instantiates (RFC-009). |
| `tracked_quantities` | The quantities the agent estimates. They default to the template's list, and a thesis can only disable optional quantities; it cannot add new ones. |
| `sources` | Adapter configs (EDGAR, press releases, named-outlet news, web search, market data), limited to the template's `sources_allowed`, with priority and tier. |
| `policy` | Material-change thresholds (overriding template defaults), `template_params`, the scheduled re-estimate cadence, budget, latency, review mode, and routing overrides that stay within template constraints. |

Mutable metadata: `status` (`active | paused | resolved | archived`), `watching` (bool), `head_version_id`, `spec_revision`.

Every `PUT` to a thesis creates a new `spec_revision`, and the thesis records the full spec for each revision. Every version and evaluation records the `spec_revision` it ran under.

Schema: [`thesis.schema.json`](../schemas/core/thesis.schema.json).

Example (`neocloud_deal`):

```yaml
thesis: who-buys-gridcompute
template: { id: neocloud_deal, version: "1.0.0" }
subject:
  target: { name: "GridCompute Inc.", listing: private, cik: "0000000001" }
  candidates:
    - { key: anthropic, name: "Anthropic PBC",   type: ai_lab }
    - { key: openai,    name: "OpenAI",          type: ai_lab }
    - { key: microsoft, name: "Microsoft Corp.", ticker: MSFT, type: hyperscaler }
    - { key: nvidia,    name: "NVIDIA Corp.",    ticker: NVDA, type: chipmaker }
  horizon: { start: "2026-10-01T00:00:00Z", end: "2027-09-30" }
sources:
  - type: edgar            # primary; candidate 10-K/10-Q routed only if they mention the target
    ciks: ["0000000001"]
    related_tickers: [MSFT, NVDA]   # candidates' filings, routed only if they mention the target
    forms: ["8-K", "10-K", "10-Q", "S-1", "S-1/A", "SC 13D", "SC 13G", "D", "DEF 14A"]
  - type: press_release    # primary
    issuers: [gridcompute, anthropic, openai, microsoft, nvidia]
  - type: news             # secondary; named outlets
    outlets: [reuters, bloomberg, the-information]
  - type: web_search       # secondary; live only
    queries: ["GridCompute acquisition", "GridCompute investment"]
policy:
  material_change:          # overrides template defaults (example values)
    acquirer_distribution: { logit_abs: 0.7, prob_abs_min: 0.02 }   # p_acquired is derived from it
    stake_probabilities:   { logit_abs: 0.7, prob_abs_min: 0.02 }
  budget_usd_per_evaluation: 1.00   # example value
  max_latency_s: 600               # example value
  debounce_s: 900
  review: required
delivery:
  webhook: { url: "https://example.com/hook", secret_ref: "HOOK_SECRET", on: [version_approved] }
```

### ThesisVersion

A ThesisVersion is an **immutable** snapshot of every tracked quantity at a given `clock`, with its provenance.

| Field | Meaning |
|---|---|
| `id`, `thesis_id`, `seq` | `seq` is monotonic per thesis, allocated at commit |
| `parent_version_id` | The approved head this version was diffed against (null for the initial version) |
| `spec_revision`, `template` | The config and template version it ran under |
| `clock` | Point-in-time bound. No evidence with `as_of > clock` influenced this version. |
| `trigger` | `initial | evidence | scheduled | manual | spec_revision | resolution`, plus the triggering evidence IDs (empty for `scheduled`) |
| `evidence_set` | Every evidence ID visible to and used by the estimator, with a hash of the sorted set |
| `values` | The new value of every tracked quantity, typed by the template |
| `deltas` | Per-quantity change against the parent: `changed`, the typed delta, and whether it is `material` and which rule fired |
| `carried_forward` | Quantities not re-estimated in this evaluation, copied from the parent |
| `comparison_baseline` | The template's comparison baseline at `clock`, with its inputs (RFC-009), for example a market-implied probability or a rule-based prior (Example (`neocloud_deal`): the reference prior, RFC-008). Shown next to the agent's estimate. It is **not** a tracked quantity, never triggers the gate, and is not an input to the estimator. |
| `self_check` | Result of the estimator's pre-emit self-check (RFC-005 step 8) |
| `recoveries` | Tool or extraction failures in this evaluation and how each was handled: retry, alternate path, or degraded (RFC-005) |
| `review_packet_id` | Link to the ReviewPacket (RFC-006) |
| `routing` | The provider and model used for each role |
| `cost`, `latency` | From content-free telemetry |
| `content_hash` | Hash over everything above |

Schema: [`thesis-version.schema.json`](../schemas/core/thesis-version.schema.json).

**What is immutable.** Everything covered by `content_hash`. The review state is **not** part of the version's content. It is kept in a separate append-only `review_events` log: `needs_review → approved | rejected | superseded`. The API shows it as `review_state` on the version.

> Trade-off: keeping review state out of the hash lets a version stay byte-identical from creation through approval, so the hash a reviewer approved is the hash that was produced. The cost is that "the version" and "its status" are two reads, not one.

### Head

`thesis.head_version_id` is the latest **approved** version. It is the only version anyone should rely on, and the baseline that the material-change gate compares against (RFC-005). A version in `needs_review` is a candidate, not the head.

### When is a version created

A version is created only when the material-change gate says yes (RFC-005), and also:

- on the initial evaluation after a thesis is created (`trigger: initial`);
- on resolution evidence (`trigger: resolution`, always material), including partial resolutions that resolve one key of a quantity (Example (`neocloud_deal`): a candidate's stake event);
- on a manual `run`, a spec revision, or a template's scheduled re-estimate when some quantity changes materially.

Non-material evaluations produce an **EvaluationRecord**, not a version (RFC-005). EvaluationRecords are immutable too, but nobody is notified about them and they never become the head.

> Trade-off: not versioning sub-threshold changes keeps the version history meaningful and review load bounded. Because the gate always compares against the approved head, and not against the last evaluation, slow drift still accumulates and eventually crosses the threshold. The fine-grained trajectory is kept in EvaluationRecords for evaluation (RFC-007).

### Version review states

```
            ┌──────────────► approved   (becomes head; enqueues webhook via outbox)
needs_review┼──────────────► rejected   (head unchanged; reason required)
            └──────────────► superseded (a newer candidate replaced it before review)
```

- Only one candidate is pending per thesis at a time. A newer material candidate supersedes the pending one. The newer one's deltas and ReviewPacket are computed against the approved head, so a reviewer always sees the cumulative change since the last approved view. Superseded versions are kept and linked (`supersedes`).
- If a newer candidate is within the material-change threshold of the pending candidate, it does **not** supersede. It is recorded as an EvaluationRecord with decision `consistent_with_pending`. This stops reviewers from being interrupted mid-review by noise.
- `approved` requires the audit to have passed, or an explicit override reason (RFC-006).
- In replay evaluation only, `review: auto` approves each version at commit so the timeline can be scored without humans (RFC-007). Live theses reject `review: auto`. Auto-approval follows the same audit rule as a human, with one scripted exception: for templates that opt in to the `secondary_only` audit, a version whose **only** audit failure is that check is approved with the override reason `replay_auto`. This stands in for a reviewer who accepts the rumor. Without it, rumor-driven moves could never reach the head in replay, and timing metrics would measure nothing. Any other audit failure leaves the version unapproved and the head unchanged. RFC-007 reports `replay_auto` overrides per case.

> Trade-off: superseding means a reviewer never signs off on intermediate candidates, so some intermediate reasoning gets less human scrutiny. We accept that because the alternative, a review queue that grows with filing frequency, would make human review a bottleneck exactly when a subject is busiest (Example (`neocloud_deal`): a financing, an IPO filing, and a wave of reported talks in the same week).

### Thesis status

`active` (being monitored or runnable) → `resolved` (full-resolution evidence approved, or the template's horizon ended; no further evaluations; outcome_audit feedback created; any `on_resolution` hand-off offered, RFC-009) → `archived`. A partial resolution leaves the thesis `active`. `paused` stops the watch loop but keeps `run` available.

## Feedback

Feedback is structured, typed, and append-only. There are three kinds:

| Kind | Attached to | Payload | Who |
|---|---|---|---|
| `user_rating` | version (optionally one quantity or claim) | `rating` (−2..+2), `dimension` (`accuracy | usefulness | citation_quality | packet_clarity`), optional `comment` | reviewer or thesis owner |
| `outcome_audit` | thesis | the template's outcome labels, `resolution_date`, point-in-time labels for scored list quantities (RFC-007 §1.3), plus computed per-version scores using the **RFC-007 §4 metric definitions** and an `eval_case_ref` when the thesis is promoted into the replay dataset | created automatically on `resolved` from the resolution evidence (or the horizon end), then confirmed by a human |
| `tool_execution_quality` | evaluation (optionally one call) | `tool_or_route`, `error_class`, `outcome` (`ok | wrong_result | malformed | timeout | recovered | failed`), `details` | emitted automatically from `RecoveryEvent`s (RFC-005); humans can add `wrong_result` reports |

Resolved live theses are post-cutoff for every model already deployed, which makes them the best future source of uncontaminated replay cases. `outcome_audit` records the fields RFC-007 §1.3 needs, so promoting a thesis into the dataset is a copy, not a re-annotation (it still gets second-annotator review).

> Trade-off: fixed feedback kinds are less expressive than free text, but they can be aggregated and fed back into routing and threshold tuning. Free text survives only as the optional `comment`.

## Mapping to RFC-002 / RFC-003

| RFC-002 lifecycle | Here |
|---|---|
| Evidence ingest | Filings, releases, news, and prices fetched for the subject's parties (RFC-001) |
| Evaluation | Evaluation job (`queued → running ⇄ needs_input → completed | failed | cancelled | superseded`), producing a ThesisVersion or an EvaluationRecord |
| Version review | `needs_review → approved | rejected | superseded`, in `review_events` |
| Delivery | Optional webhook on `approved` or `thesis_resolved`, via the outbox |
| Replay run | Replay evaluation (RFC-007); live outcome audits reuse its metrics |

The version, its ReviewPacket, and any outbox intent are written in a single transaction guarded by the RFC-003 fencing predicate (`job_id, attempt_no, lease_owner, lease_expires_at > now()`). `seq` is allocated inside that transaction. A stale attempt affects zero rows and can't create a version.

## Open questions

- Should a template be allowed to change mid-thesis, or must a change always close the thesis and hand off to a new one (RFC-009 *Chaining*)?
- Should adding a subject party mid-thesis be allowed as a spec revision, given that the new party's probabilities have no history to diff against and replay scores only fixed party lists? (Example (`neocloud_deal`): adding a candidate mid-horizon.)
