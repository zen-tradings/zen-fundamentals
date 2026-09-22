# RFC-001: Separate Shared Research Layer from User Report Layer

Status: Discussion

Date: 2026-07-23

## Problem

The current design defines each research job as having:

- stable job ID
- owner
- user_id
- directive_version snapshot


This model works naturally for per-user research.


However, the deduplication design also proposes:

- multiple users matching the same signal
- one shared research job
- fan-out during rendering/personalization


This creates a potential model conflict.

## Proposal for Discussion

Separate two concepts:


## 1. Research Run

System-owned event dossier.

Responsibilities:

- consume canonical signal / signal cluster
- collect facts
- build timeline
- capture source evidence
- produce reusable research artifacts


Constraints:

Research Run should not access:

- user memory
- user directives
- user emails
- personal history


A Research Run can be reused by multiple users.

## 2. Report Job

Strictly per-user report generation.

Properties:

- user_id
- directive_version_id
- trigger_snapshot
- research_run_id


Responsibilities:

- select relevant facts
- perform user-specific enrichment if needed
- personalize
- write report
- render delivery
- run quality checks


User-specific:

- quota
- concurrency
- permissions
- evaluation
