# RFC-002: Separate Job Lifecycle State Machines for Research, Thesis Versions, Delivery, and Evaluation

Status: Discussion

Date: 2026-07-23

Entity rename (2026-09-23): "report" / "issue" → **thesis version** (see RFC-004). RFC-005 maps these lifecycles onto evaluation jobs and version review states.

## Problem

The current design defines a research job as the unit of work.

The lifecycle includes:

1. Create
2. Claim
3. Research
4. Produce
5. Deliver
6. Evaluate


The same job tracks work across the entire pipeline.


## Potential Issue

A single job state:

queued → running → succeeded/failed

cannot clearly represent:

Example:

Research succeeded,
thesis version generated,
delivery failed.

What should the job status be?

The current model may make failure recovery harder

## Proposal for Discussion

Consider separating lifecycle ownership:


## Research Lifecycle

Example:

queued
↓
running
↓
completed
↓
failed


Responsible for research execution and evidence collection

## Thesis Version Lifecycle

Example:

queued
↓
generating
↓
generated
↓
failed


Responsible for per-thesis version creation

## Delivery Lifecycle

Example:

pending
↓
sending
↓
sent
↓
failed


Responsible for external delivery

## Evaluation Lifecycle

Example:

pending
↓
running
↓
completed
↓
failed


Responsible for quality evaluation
