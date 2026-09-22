# RFC-002: Separate Job Lifecycle State Machines for Research, Reporting, Delivery, and Evaluation

Status: Discussion

Date: 2026-07-23

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
report generated,
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

## Report Lifecycle

Example:

queued
↓
generating
↓
generated
↓
failed


Responsible for user-specific report creation

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
