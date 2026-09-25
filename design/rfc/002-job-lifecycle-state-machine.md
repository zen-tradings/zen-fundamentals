# RFC-002: Separate Lifecycle State Machines for Evidence Ingest, Evaluation, Version Review, Delivery, and Replay

Status: Discussion

Date: 2026-07-23 (rewritten 2026-09-24; template-agnostic, examples from `neocloud_deal`)

Depends on: RFC-001, RFC-003

## Problem

One thesis touches several kinds of work that fail independently: fetching a filing, evaluating the thesis after it (impact, extraction, estimate, self-check, audit), a human reviewing the resulting version, sending the webhook once it is approved, and replaying historical cases for evaluation.

If a single job with one status (`queued → running → succeeded | failed`) tracked all of that, it couldn't represent common mixed outcomes:

- The filing was ingested, the evaluation produced a version, but the webhook failed. Is the job failed?
- The evaluation is waiting for the thesis owner to answer a question (`needs_input`). Is the job running?
- Newer evidence arrived while a version was waiting for review. What happens to the pending version?
- The thesis owner revised the spec. What happens to evaluations already running under the old spec?

Example (`neocloud_deal`): a candidate's 10-K mentioning the target is ingested; the owner is asked which "GridCompute" a news article means; a newer SC 13D arrives while a version awaits review; the owner adds a candidate mid-horizon.

A single status also makes recovery unsafe: retrying "the job" after a webhook failure would re-run the estimator and could create a second version from the same evidence.

## Proposal

Give each kind of work its own lifecycle, owned by its own layer. Every job uses leased execution with fencing tokens (RFC-003), so a stale attempt can't move any lifecycle forward.

### 1. Evidence ingest (evidence layer, RFC-001)

```
queued → running → completed
                 ↘ failed
```

One ingest job per adapter run (for example "EDGAR filings for the subject's CIKs since the last cursor", or "news from the configured outlets"). `failed` means the evidence isn't visible yet. It never fails a thesis or a version. Retries honor `Retry-After`, and a document that can't be normalized is stored as `normalize_failed` and isn't citable (RFC-005 *Failure recovery*).

### 2. Evaluation (judgment layer, RFC-005)

```
queued → running ⇄ needs_input
            │
            ├──→ completed    (commits a ThesisVersion or an EvaluationRecord)
            ├──→ failed       (self_check_failed, point_in_time_violation, budget_exceeded, rate_limited, …)
            ├──→ cancelled    (DELETE /v1/evaluations/:id before commit)
            └──→ superseded   (a spec revision made this job's inputs stale)
```

- One evaluation job per batch of routed evidence, per scheduled re-estimate (`trigger: scheduled`), per manual run, or per resolution event (full or partial, from the template's `outcomes`).
- `clock` is fixed at creation (RFC-005 step 4). Evidence that arrives later waits for the next job.
- `needs_input` pauses the job for a question to the thesis owner, for example which of two similarly named companies is meant. It resumes via `POST /v1/evaluations/:id/answer`.
- A spec revision (for example adding or removing a subject party) supersedes every queued or running job from older revisions.
- Idempotency key: `(thesis_id, spec_revision, clock, hash(evidence_set))`. A re-delivered batch or a reclaimed job can't produce a second version for the same inputs.
- A terminal failure never rewrites a committed version.

### 3. Version review (judgment layer, RFC-004)

```
needs_review ──→ approved    (becomes head; enqueues delivery via the outbox)
             ├─→ rejected    (reason required; head unchanged)
             └─→ superseded  (a newer material candidate replaced it before review)
```

- Review state lives in an append-only `review_events` log, outside the version's `content_hash`.
- Only one candidate is pending per thesis. A newer material candidate supersedes it and is diffed against the approved head, so a reviewer always sees the cumulative change since the last approved view.
- Approving a version whose audit failed, for example a change supported only by secondary evidence, requires an `override_reason` (RFC-006).
- Evaluation and review are separate lifecycles: an evaluation is `completed` as soon as its version is committed, whatever the reviewer later decides.

### 4. Delivery (outbox, RFC-003)

```
pending → sending → sent
                  ↘ failed → pending (retry with backoff)
                  ↘ dead      (retry budget exhausted; visible on the thesis)
```

One delivery per approved version (or per `thesis_resolved` event), created in the same fenced transaction as the approval. A delivery failure never touches the version or the evaluation. Retrying it re-sends the same signed payload; it never re-runs any estimation.

### 5. Replay evaluation run (RFC-007)

```
queued → preparing → running → scoring → completed
                  ↘          ↘         ↘ failed
                                          invalid (any point-in-time violation)
```

- `preparing` builds the frozen corpus view, the anonymized namespaces, and the knowledge probes.
- `running` replays every `(case, configuration, repeat)` as ordinary evaluation jobs in virtual time, with their own lifecycle (§2) and `review: auto`.
- `invalid` is terminal and separate from `failed`: the run finished, but a point-in-time violation means none of its numbers may be reported (RFC-007 §2.3).

## Mapping

| Work | Lifecycle | Commits | Retried how |
|---|---|---|---|
| Fetch and normalize filings, releases, news | Evidence ingest | EvidenceItems | Next adapter run |
| Re-estimate a thesis | Evaluation | ThesisVersion or EvaluationRecord (+ ReviewPacket) | Reclaimed by lease; idempotency key blocks duplicates |
| Human decision | Version review | `review_events` row | Not retried; a human acts |
| Webhook | Delivery | Delivery attempt rows | Outbox backoff |
| Historical evaluation | Replay run | Results table, exclusions | Whole run re-queued; cached agent calls reused where inputs are unchanged |

## Trade-offs

- **More states to reason about.** Five lifecycles are harder to explain than one job status. In return, every mixed outcome above has an unambiguous state, and every retry repeats exactly one kind of work.
- **Cross-lifecycle queries.** "What happened after that filing?" now joins the ingest job, the evaluation job, the version's review events, and any delivery. The API exposes that join on `GET /v1/theses/:id` and `GET /v1/versions/:id`, so clients don't have to.

## Open questions

- Should `needs_input` time out, and if so, should the evaluation fail or continue without the answer (flagging the affected quantities uncertain)?
- Should a `dead` delivery raise an alert on the thesis, or only appear in its status?
