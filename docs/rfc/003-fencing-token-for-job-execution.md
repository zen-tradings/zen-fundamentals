# RFC-003: Add Fencing Tokens for Leased Job Execution

Status: Discussion

Date: 2026-07-23

## Problem

When a worker loses connectivity, its lease may expire and the reaper may reassign the job. If the old worker later recovers, it can still commit results or trigger duplicate delivery.

## Discussion

Each claim creates a monotonically increasing `attempt_no` and records `lease_owner` and `lease_expires_at`. The worker must periodically renew its lease with a heartbeat.

Every heartbeat, success, failure, and cancellation update must verify:

```sql
job_id = ?
AND attempt_no = ?
AND lease_owner = ?
AND lease_expires_at > now()
```

If the update affects zero rows, the worker is stale and must stop and discard its result.

When a lease expires, the reaper requeues the job. The next claim increments `attempt_no`. Workers must not call external delivery services directly; successful results are first written to an outbox and processed by a delivery worker.

## Example

Worker A starts job `J` with `attempt_no=1` and becomes disconnected. After the lease expires, Worker B claims `J` with `attempt_no=2` and completes it. When A recovers and tries to commit, its token no longer matches, so the update affects zero rows. A cannot overwrite B’s result or send another message.

## Guarantee

The system provides at-least-once execution with stale-attempt fencing. An expired attempt cannot commit a result or create a new delivery intent.
