# RFC-004: Thesis and ThesisVersion Model

Status: Discussion

Date: 2026-09-23

Depends on: RFC-001 (evidence vs. judgment), RFC-002 (lifecycles), RFC-003 (fencing)

## Problem

The product's core object used to be a newsletter: an audience, a cadence, and channels, producing articles. That doesn't fit a research agent whose job is to hold a view on something and keep that view current. What we need to audit is **what the agent believed, when, and why**. The prose around it matters much less.

## Proposal

### Thesis

A thesis is a long-lived, declarative spec for a view the agent maintains about one subject. It has five parts:

| Field | Meaning |
|---|---|
| `subject` | What the thesis is about. It is template-typed; for `neocloud_deal` it names the target, the candidate acquirers and investors, and the horizon. |
| `template` | `{id, version}` of the centrally maintained template it instantiates (RFC-008). |
| `tracked_quantities` | The quantities the agent estimates. They default to the template's list, and a thesis can only disable optional quantities; it cannot add new ones. |
| `sources` | Adapter configs (EDGAR, press releases, web search) with priority and tier. |
| `policy` | Material-change thresholds (overriding template defaults), budget, latency, review mode, and routing overrides that stay within template constraints. |

Mutable metadata: `status` (`active | paused | resolved | archived`), `watching` (bool), `head_version_id`, `spec_revision`.

Every `PUT` to a thesis creates a new `spec_revision`, and the thesis records the full spec for each revision. Every version and evaluation records the `spec_revision` it ran under.

Schema: [`thesis.schema.json`](../schemas/thesis.schema.json).

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
    candidate_tickers: [MSFT, NVDA]
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
| `trigger` | `initial | evidence | heartbeat | manual | spec_revision | resolution`, plus the triggering evidence IDs (empty for `heartbeat`) |
| `evidence_set` | Every evidence ID visible to and used by the estimator, with a hash of the sorted set |
| `values` | The new value of every tracked quantity, typed by the template |
| `deltas` | Per-quantity change against the parent: `changed`, the typed delta, and whether it is `material` and which rule fired |
| `carried_forward` | Quantities not re-estimated in this evaluation, copied from the parent |
| `reference_prior` | The template's rule-based reference prior at `clock`, with its inputs (RFC-008 §Reference prior). Shown next to the agent's estimate. It is **not** a tracked quantity, never triggers the gate, and is not an input to the estimator. |
| `self_check` | Result of the estimator's pre-emit self-check (RFC-005 step 8) |
| `recoveries` | Tool or extraction failures in this evaluation and how each was handled: retry, alternate path, or degraded (RFC-005) |
| `review_packet_id` | Link to the ReviewPacket (RFC-006) |
| `routing` | The provider and model used for each role |
| `cost`, `latency` | From content-free telemetry |
| `content_hash` | Hash over everything above |

Schema: [`thesis-version.schema.json`](../schemas/thesis-version.schema.json).

**What is immutable.** Everything covered by `content_hash`. The review state is **not** part of the version's content. It is kept in a separate append-only `review_events` log: `needs_review → approved | rejected | superseded`. The API shows it as `review_state` on the version.

> Trade-off: keeping review state out of the hash lets a version stay byte-identical from creation through approval, so the hash a reviewer approved is the hash that was produced. The cost is that "the version" and "its status" are two reads, not one.

### Head

`thesis.head_version_id` is the latest **approved** version. It is the only version anyone should rely on, and the baseline that the material-change gate compares against (RFC-005). A version in `needs_review` is a candidate, not the head.

### When is a version created

A version is created only when the material-change gate says yes (RFC-005), and also:

- on the initial evaluation after a thesis is created (`trigger: initial`);
- on resolution evidence (`trigger: resolution`, always material), including partial resolutions such as a candidate's stake event (RFC-008);
- on a manual `run`, a spec revision, or a template heartbeat when some quantity changes materially.

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
- In replay evaluation only, `review: auto` approves each version at commit so the timeline can be scored without humans (RFC-007). Live theses reject `review: auto`.

> Trade-off: superseding means a reviewer never signs off on intermediate candidates, so some intermediate reasoning gets less human scrutiny. We accept that because the alternative, a review queue that grows with filing frequency, would make human review a bottleneck exactly when a target is busiest (a financing, an IPO filing, and a wave of reported talks in the same week).

### Thesis status

`active` (being monitored or runnable) → `resolved` (final resolution evidence approved, or the template horizon ended; no further evaluations; outcome_audit feedback created) → `archived`. A partial resolution (a candidate's stake event) leaves the thesis `active`. `paused` stops the watch loop but keeps `run` available.

## Feedback

Feedback is structured, typed, and append-only. There are three kinds:

| Kind | Attached to | Payload | Who |
|---|---|---|---|
| `user_rating` | version (optionally one quantity or claim) | `rating` (−2..+2), `dimension` (`accuracy | usefulness | citation_quality | packet_clarity`), optional `comment` | reviewer or thesis owner |
| `outcome_audit` | thesis | `acquisition_outcome`, `stake_outcomes`, `resolution_date`, `relationships_timeline`, plus computed per-version scores using the **RFC-007 §4 metric definitions** and an `eval_case_ref` when the thesis is promoted into the replay dataset | created automatically on `resolved` from the resolution evidence (or the horizon end), then confirmed by a human |
| `tool_execution_quality` | evaluation (optionally one call) | `tool_or_route`, `error_class`, `outcome` (`ok | wrong_result | malformed | timeout | recovered | failed`), `details` | emitted automatically from `RecoveryEvent`s (RFC-005); humans can add `wrong_result` reports |

Resolved live theses are post-cutoff for every model already deployed, which makes them the best future source of uncontaminated replay cases. `outcome_audit` records the fields RFC-007 §1.3 needs, so promoting a thesis into the dataset is a copy, not a re-annotation (it still gets second-annotator review).

> Trade-off: fixed feedback kinds are less expressive than free text, but they can be aggregated and fed back into routing and threshold tuning. Free text survives only as the optional `comment`.

## Mapping to RFC-002 / RFC-003

| RFC-002 lifecycle | Here |
|---|---|
| Research | Evidence ingest job (RFC-001) |
| Thesis version | Evaluation job (`queued → running → needs_input → running → completed | failed | cancelled | superseded`), producing a ThesisVersion or an EvaluationRecord |
| Delivery | Optional webhook on `approved`, via the outbox |
| Evaluation | Outcome audits and replay (RFC-007) |

The version, its ReviewPacket, and any outbox intent are written in a single transaction guarded by the RFC-003 fencing predicate (`job_id, attempt_no, lease_owner, lease_expires_at > now()`). `seq` is allocated inside that transaction. A stale attempt affects zero rows and can't create a version.

## Open questions

- When an acquisition is announced, should the resolved thesis link to a follow-on thesis that tracks whether the deal closes, or is that out of scope?
- Should adding a candidate mid-horizon be allowed as a spec revision, given that the new candidate's probabilities have no history to diff against and RFC-007 scores only fixed candidate lists?
