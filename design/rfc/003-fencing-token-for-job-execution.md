# RFC-003: Add Fencing Tokens for Leased Job Execution

Status: Discussion

Date: 2026-07-23 (examples updated 2026-09-24 for `neocloud_deal`)

## Problem

When a worker loses connectivity, its lease may expire and the reaper may reassign the job. If the old worker later recovers, it can still commit results or trigger duplicate delivery. For a thesis, that means two ThesisVersions for the same filing, a stake probability resolved twice, or the same webhook sent twice.

## Discussion

Each claim creates a monotonically increasing `attempt_no` and records `lease_owner` and `lease_expires_at`. The worker must periodically renew its lease (the **lease heartbeat**; unrelated to the template's scheduled re-estimate in RFC-008).

Every lease renewal, success, failure, and cancellation update must verify:

```sql
job_id = ?
AND attempt_no = ?
AND lease_owner = ?
AND lease_expires_at > now()
```

If the update affects zero rows, the worker is stale and must stop and discard its result.

When a lease expires, the reaper requeues the job. The next claim increments `attempt_no`. Workers must not call external delivery services directly; successful results are first written to an outbox and processed by a delivery worker.

The commit of an evaluation (ThesisVersion or EvaluationRecord, ReviewPacket, and any outbox intent) is one transaction guarded by this predicate, and the version `seq` is allocated inside it (RFC-004). The evaluation idempotency key `(thesis_id, spec_revision, clock, hash(evidence_set))` is a second line of defense: even a correctly fenced retry can't create a second version for the same inputs (RFC-005).

## Example

A candidate files an SC 13D on the target, crossing the 5% stake threshold. That is resolution-class evidence for the candidate's stake (RFC-008), so evaluation job `J` for thesis `who-buys-gridcompute` is created at once.

Worker A claims `J` with `attempt_no=1`, runs the estimator, and loses connectivity before committing. After the lease expires, Worker B claims `J` with `attempt_no=2`, commits a version with the stake resolved and its structure tag set, and writes the outbox intent. When A recovers and tries to commit, its token no longer matches, so the update affects zero rows. A cannot create a second version, resolve the stake again, or queue another webhook.

## Guarantee

The system provides at-least-once execution with stale-attempt fencing. An expired attempt cannot commit a result or create a new delivery intent.
