# RFC-009: Template Contract

Status: Discussion

Date: 2026-09-24

Depends on: RFC-001, RFC-004, RFC-005, RFC-006, RFC-007

## Problem

The core (evidence layer, evaluation loop, gate, review, replay harness) should work for any kind of deal: who will buy a neocloud, whether an announced merger closes, whether an activist wins board seats. Everything specific to one kind of deal belongs in a **template**.

Before this RFC, the first template's details had leaked into the core. The core schemas only accepted `neocloud_deal`, the packet had acquirer and stake tables as fixed fields, and the eval spec mixed the generic harness with a neocloud dataset. Adding a second template would have meant editing every core schema and three core RFCs.

This RFC defines what a template must provide, and how the core uses it, so that a new template needs **no core edits**.

## Layout

```
design/
  rfc/                       core RFCs (001–007, 009) and per-template rationale RFCs (008, …)
  schemas/core/              template-agnostic schemas, including quantity-types.schema.json
  templates/<id>/
    template.yaml            the manifest (below)
    subject.schema.json      shape of thesis.subject
    values.schema.json       shape of ThesisVersion.values, built from core quantity types
    params.schema.json       template parameters in thesis.policy.template_params (optional)
    baseline.schema.json     inputs of the comparison baseline
    eval.md                  eval spec: dataset, labels, metrics, baselines, distractors
    eval-metrics.schema.json shape of EvalResultRow.template_metrics
    vocab/*.yaml             canonical key vocabularies (optional)
```

RFCs explain **why**. The template folder says **what**, in a form code can load.

## What a template provides

| Manifest field | What it is | Used by |
|---|---|---|
| `id`, `version` | Semver; a thesis pins both (see *Versioning*) | everywhere |
| `subject_schema` | Shape of `thesis.subject`, including the parties that can appear in outcome keys | thesis validation, routing, anonymization |
| `sources_allowed` | Which core source types a thesis may configure | thesis validation |
| `quantities` | Each tracked quantity: name, core type, required or optional, key source (for example "from `subject.candidates`, plus reserved `other`, `none`"), vocabulary, derivation formula for derived quantities | estimator contract, gate, packet |
| `values_schema` | JSON Schema for `values`, composed only from core quantity types plus template constraints | version validation |
| `outcomes` | Outcome definitions and **resolution rules**: which evidence resolves the thesis fully, which resolves one key partially, and what happens at `horizon.end` (if the template has a horizon) | loop (resolution-class evidence), replay (stop condition), feedback |
| `dependencies` | Edges between quantities; affected upstream implies affected downstream | impact mapping (RFC-005 step 5) |
| `impact_rules` | Deterministic evidence → affected-quantities rules; they can only add | impact mapping |
| `self_checks` | Template checks, each `code` or `model`, with tolerances. Core checks always run too. | self-check (RFC-005 step 8) |
| `audit` | Opt-ins to core audit checks, for example `secondary_only: true` | audit (RFC-006) |
| `degrade_order` | Budget-pressure steps, ending in `hold` | budget (RFC-005) |
| `scheduled_reestimate` | Cadence in days, or `null` for none, and which quantities it re-estimates | scheduler (RFC-005 step 3) |
| `thresholds` | Default material-change rules per quantity, using the core rule shape for its type | gate |
| `params` | Template parameters (for example stake thresholds), with defaults and a schema | template rules |
| `labels` | Descriptive label sets (see *Descriptive labels*) | values, packet, eval |
| `baseline` | The comparison baseline: id, formula version, inputs schema. Never shown to the estimator, never gates. | packet, replay |
| `routing` | Role tiers and constraints; `provider_must_differ_from` can't be removed | router |
| `packet_layout` | Ordered list of core section kinds bound to quantities | packet rendering (RFC-006) |
| `judgment_prompts` | Standard investor-judgment questions and when they fire | estimator, packet |
| `extraction_targets` | Per document type, versioned (`<id>.<target>@<n>`) | evidence layer (RFC-001) |
| `eval` | Eval spec, metrics schema, and `scores`: the RFC-007 metric families used per scored quantity | replay (RFC-007) |
| `on_resolution` | Optional hand-off: start a thesis of another template when this one resolves in a given way | lifecycle (see *Chaining*) |

## What the core provides

**Quantity types** ([`quantity-types.schema.json`](../schemas/core/quantity-types.schema.json)). Every template quantity uses one of these, and the gate, packet, and metrics know how to handle each:

| Type | Shape | Default material rule | Packet section | Metric family |
|---|---|---|---|---|
| `probability` | number in [0, 1] | log-odds + floor, or absolute | inside a table | Brier, log loss |
| `derived_probability` | value computed by code from another quantity | as `probability` | beneath its source | as `probability` |
| `outcome_distribution` | one probability per key, summing to 1 | log-odds + floor per key, optional top-rank rule | `distribution_table` | multi-class log loss and Brier, rank / top-k |
| `probability_map` | one independent probability per key, with resolution | log-odds + floor per key; resolution | `map_table` | binary Brier per key, rank / top-k |
| `scenario_set` | outcomes with probability and a value (for example a price) | per-outcome probability and relative value move | `scenario_table` | multi-class Brier, value error |
| `date_estimate` | date with optional 80% interval | days | `date_change` | absolute error, bias |
| `condition_list` | keyed conditions with status | added, removed, status change | `list_changes` | recall / precision by key, status accuracy |
| `relationship_list` | keyed ties between parties, with labels | added, removed, status, value, label change | `list_changes` | recall / precision by key, label accuracy |
| `signal_list` | keyed signals with direction and basis | added, status change | `list_changes` | not scored by default |
| `facts` | template-shaped object with named field groups | change in listed groups | `facts_changes` | field accuracy |

**Core mechanisms** every template gets: point-in-time enforcement, the gate against the approved head, full and partial resolution, scheduled re-estimates, the comparison baseline slot, the `secondary_only` audit opt-in, provider-conflict flags, core self-checks (citation coverage, `as_of ≤ clock`, the elapsed-time claim for scheduled re-estimates), failure recovery, and the replay harness.

## Validation

Validation happens in two stages:

1. The core schemas validate the envelope. `subject`, `values`, `template_params`, baseline `inputs`, and `template_metrics` are plain objects tagged with `template: {id, version}`.
2. A registry loads `templates/<id>@<version>/` and validates those objects against the template's schemas, and validates keys against the template's vocabularies and key sources.

> Trade-off: two-stage validation means a stock JSON Schema validator checks only the envelope. The alternative, an `if template.id == X then $ref …` chain in each core schema, would put every template's name into core files and require a core edit for every new template, which is exactly what this RFC exists to avoid.

## Versioning

Templates follow semver, and a thesis pins `{id, version}`:

- **major**: the quantity schema or the outcome definitions change (requires a new thesis or an explicit migration);
- **minor**: extraction targets, prompts, impact rules, vocabularies, or baseline weights change;
- **patch**: threshold defaults or packet layout change.

A replay result is valid only for the template version it ran on. The core's own schemas are versioned separately. A template declares the core version range it supports.

## Descriptive labels

Some classifications are useful but judgment-heavy, for example whether an equity stake is really vendor financing (RFC-008). A template can declare **label sets**: named vocabularies attached to `probability_map` entries or `relationship_list` items as `labels: {<set>: <value>}` and `label_flags: {<set>: [<values>]}`.

Labels **describe**; they never decide whether an outcome happened. Outcome rules must stay mechanical so replay labels can be rebuilt. The core provides label accuracy as a metric family and lets eval specs split metrics by label.

## Chaining

A template may declare `on_resolution`: when a thesis resolves with a given outcome, the core offers to create a thesis of another template, pre-filled from the resolved one. For example, when `neocloud_deal` resolves with an acquisition announcement, a `merger_arb` thesis can start from the announcement to track whether the deal closes. The new thesis is linked (`predecessor_thesis_id`) and has its own spec, versions, and evaluation.

## Conformance

A template conforms if:

1. every file in its folder parses, and every `$ref` resolves;
2. `values_schema` uses only core quantity types (plus constraints);
3. every quantity in `packet_layout`, `thresholds`, `dependencies`, and `impact_rules` exists in `quantities`;
4. every outcome in `outcomes` has a resolution rule, and every resolution rule names resolution-class evidence;
5. its manifest's `eval.scores` names, for every quantity it scores, only metric families that the RFC-007 §4.1 registry allows for that quantity's type.

The core conforms if **no template id or template-specific term appears in `schemas/core/` or in the normative text of RFC-001–007**. Examples are allowed only when labeled `Example (<template id>)`. `design/check.py` checks both.

The [`merger_arb`](../templates/merger_arb/) sketch is the standing proof: a second template with different quantity types (`scenario_set`, `condition_list`, `facts`) and a different baseline (market-implied), added with no core edits.

## Adding a template

1. Write the rationale RFC (outcomes, sources, why these quantities).
2. Create `templates/<id>/` with the manifest and schemas.
3. Write `eval.md`: dataset rules, labels, strata, metrics, baselines, distractors, injected errors.
4. Run `design/check.py`.
5. If you needed a new quantity type or core mechanism, stop: that is a core change and needs its own RFC.

## Open questions

- Should vocabularies be shared across templates (a relationship vocabulary used by several deal types), or always template-owned?
- Should a template be able to extend another (for example a `datacenter_deal` template that reuses most of `neocloud_deal`)?
