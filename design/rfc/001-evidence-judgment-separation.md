# RFC-001: Separate the Shared Evidence Layer from the Per-Thesis Judgment Layer

Status: Discussion

Date: 2026-07-23 (rewritten 2026-09-23)

Supersedes: the earlier "shared research layer vs. per-user report layer" draft of this RFC.

## Problem

One SEC filing is relevant to many theses. A DEFM14A for a target is read by every thesis that tracks that deal, and an 8-K from a serial acquirer may matter to several open deals at once. If each thesis fetched, parsed, and stored its own copy:

- the same document would be fetched and normalized N times;
- two theses could cite slightly different copies of "the same" filing, which breaks auditability;
- there would be no single place to enforce point-in-time (`as_of`) rules.

The opposite mistake is also possible. If per-thesis reasoning leaked into a shared store, one thesis's judgment could quietly shape another thesis's inputs, and replay evaluation (RFC-007) could no longer isolate what a thesis knew at a given clock.

## Proposal

Split the system into two layers with a one-way dependency: **judgment reads evidence; evidence never reads judgment.**

### 1. Evidence layer (shared, system-owned)

Responsibilities:

- run source adapters (`discover → fetch → normalize`) under the configured priority and trust tiers;
- assign every item an immutable `as_of` (the publication or filing timestamp, not the time it was retrieved) and a trust tier (`primary` / `secondary`);
- deduplicate by content hash; link amendments (`8-K/A`, revised press releases) as new items via `amends` rather than editing existing ones;
- run **document-local extraction**: extraction whose only inputs are one evidence item and a versioned extraction target from a template (for example `merger_arb.key_terms@1`);
- serve a **point-in-time view**: every read takes a `clock` and returns only items with `as_of ≤ clock`.

Objects: `EvidenceItem` ([schema](../schemas/evidence-item.schema.json)) and `Extraction` (an evidence-derived artifact that inherits the `as_of` of its source item).

Constraints. The evidence layer must not read:

- thesis state, versions, or estimates;
- thesis policy or material-change thresholds;
- review decisions or feedback;
- anything a user wrote about why they hold a thesis.

Evidence items are immutable and content-addressed. One item can be cited by any number of theses.

### 2. Judgment layer (per-thesis)

Responsibilities:

- decide which tracked quantities a new evidence item affects (impact mapping, RFC-005);
- re-estimate those quantities and reconcile conflicting signals;
- apply the material-change gate;
- produce `ThesisVersion`s and `ReviewPacket`s (RFC-004, RFC-006);
- record no-change decisions.

Properties of each judgment job:

- `thesis_id`
- `spec_revision` (the thesis config revision it ran under)
- `clock`
- `evidence_set` (the exact evidence IDs visible at `clock` and used)
- `parent_version_id`

Per-thesis concerns:

- budget and concurrency;
- permissions and tool allowlists;
- review;
- evaluation and feedback.

The judgment layer has **read-only** access to evidence, and only through the point-in-time view. It cannot create, edit, or annotate evidence items. When a thesis needs something that isn't in the store yet (for example a targeted search for a regulator's statement), it files a **discovery request**. The evidence layer handles it like any other adapter run, and the result is an ordinary shared evidence item, not a thesis-private artifact.

## What goes where

| Artifact | Layer | Why |
|---|---|---|
| Raw filing, press release, search hit | Evidence | Same bytes for every citer |
| `as_of`, tier, source, content hash | Evidence | Needed for point-in-time rules and auditing, and independent of any thesis |
| Extraction from one document against a template target | Evidence (cached) | Inputs are the document and target only, so it is safe to share and PIT-safe (it inherits the document's `as_of`) |
| Extraction that needs thesis context (for example "which of the three deals in this 8-K is ours?") | Judgment | Depends on thesis subject |
| Impact assessment, estimates, reconciliation | Judgment | Thesis-specific reasoning |
| ThesisVersion, ReviewPacket, no-change records | Judgment | Immutable per-thesis history |

## Lifecycles

Each layer has its own lifecycle, per RFC-002. Evidence ingest jobs use the research lifecycle (`queued → running → completed | failed`). Judgment work uses evaluation jobs and version review states (RFC-005, RFC-004). A failed ingest never marks a thesis version failed. It only means that evidence isn't visible yet.

Both layers use leased execution with fencing tokens (RFC-003).

## Visibility

Public-source evidence (EDGAR, public press releases, open web) sits in a global partition. Evidence from private or licensed sources (planned) sits in a tenant partition, and a thesis can only see partitions its owner is entitled to. Sharing happens within a visibility scope, never across one.

## Trade-offs

- **Shared extraction cache vs. per-thesis control.** Caching document-local extractions by `(evidence_id, target@version, model_route)` saves cost and makes two theses agree on what a filing says. The cost is that a thesis cannot tune extraction prompts for itself. Tuning belongs in the template, which is centrally maintained anyway (RFC-008).
- **One-way dependency vs. targeted fetch.** Because the evidence layer can't see thesis context, it can't prioritize fetches by how important they are to a given thesis. Discovery requests cover the common cases, and the loss of prioritization is accepted in exchange for clean replay isolation.
- **Immutability vs. storage.** Keeping every amendment and page revision as a separate item grows storage, but a version's evidence set stays exactly reproducible.

## Open questions

- Should the extraction cache key include the extractor model route, or should re-extraction by a newer model replace older extractions for new work while keeping them for replay?
- Retention: how long do we keep secondary-tier (web) items that no version cites?
