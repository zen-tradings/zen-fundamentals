#!/usr/bin/env python3
"""Design conformance checks (RFC-009 §Conformance).

Checks:
  1. Every JSON schema parses, is a valid draft 2020-12 schema, and every $ref resolves.
  2. Each template manifest is consistent: quantity types exist in the core library, values_schema
     composes core types matching the manifest, and every quantity named in packet_layout,
     thresholds, dependencies, impact_rules, and scheduled_reestimate exists. Threshold rules use
     the core rule shape for the quantity's type. Outcomes have resolution evidence. eval.scores uses
     RFC-007 registry families valid for each type. YAML blocks in the rationale RFC match the manifest.
  3. Example theses validate in two stages (core thesis schema, then template subject/params).
  4. Core stays template-agnostic: no template id or template-specific term in schemas/core/, and
     in RFC-001..007 only inside labeled examples ("Example (`<id>`)").
  5. Relative markdown links resolve.

Usage: python3 design/check.py   (needs PyYAML and jsonschema)
"""
import glob
import json
import os
import re
import sys

import yaml
from jsonschema import Draft202012Validator

ROOT = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(ROOT)
CORE = os.path.join(ROOT, "schemas", "core")
TEMPLATES = os.path.join(ROOT, "templates")
QT_FILE = os.path.join(CORE, "quantity-types.schema.json")

errors = []


def err(msg):
    errors.append(msg)


def rel(p):
    return os.path.relpath(p, REPO)


# 1. Schemas ---------------------------------------------------------------

schema_files = sorted(glob.glob(os.path.join(CORE, "*.json")) + glob.glob(os.path.join(TEMPLATES, "*", "*.json")))
docs = {}
for f in schema_files:
    try:
        docs[os.path.abspath(f)] = json.load(open(f))
    except json.JSONDecodeError as e:
        err(f"{rel(f)}: invalid JSON: {e}")

for f, d in docs.items():
    try:
        Draft202012Validator.check_schema(d)
    except Exception as e:  # noqa: BLE001
        err(f"{rel(f)}: not a valid 2020-12 schema: {str(e).splitlines()[0]}")


def resolve(ref, src):
    path, _, ptr = ref.partition("#")
    target = os.path.abspath(os.path.join(os.path.dirname(src), path)) if path else src
    node = docs[target]
    for part in [p for p in ptr.split("/") if p]:
        node = node[part]
    return node


def walk_refs(node, src):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref":
                try:
                    resolve(v, src)
                except (KeyError, TypeError):
                    err(f"{rel(src)}: unresolved $ref {v}")
            else:
                walk_refs(v, src)
    elif isinstance(node, list):
        for v in node:
            walk_refs(v, src)


for f, d in docs.items():
    walk_refs(d, f)


def registry_validator(schema_path):
    """Validator that resolves relative $refs against the local files."""
    from referencing import Registry, Resource

    resources = []
    for f, d in docs.items():
        res = Resource.from_contents(d)
        resources.append(("file://" + f, res))
        if "$id" in d:
            resources.append((d["$id"], res))
    registry = Registry().with_resources(resources)
    schema = dict(docs[os.path.abspath(schema_path)])
    schema["$id"] = "file://" + os.path.abspath(schema_path)
    return Draft202012Validator(schema, registry=registry)


# 2. Template manifests -----------------------------------------------------

qt = docs.get(os.path.abspath(QT_FILE), {}).get("$defs", {})
CORE_TYPES = {"probability", "derived_probability", "outcome_distribution", "probability_map", "scenario_set",
              "date_estimate", "condition_list", "relationship_list", "signal_list", "facts"}
RULE_SHAPE = {
    "probability": "probability", "derived_probability": "probability",
    "outcome_distribution": "outcome_distribution", "probability_map": "probability",
    "scenario_set": "scenario_set", "date_estimate": "date_estimate",
    "condition_list": "list", "relationship_list": "list", "signal_list": "list", "facts": "facts",
}
SECTION_KINDS = {"distribution_table": "outcome_distribution", "map_table": "probability_map",
                 "scenario_table": "scenario_set", "list_changes": None, "date_change": "date_estimate",
                 "facts_changes": "facts"}
METRIC_FAMILIES = {  # RFC-007 §4.1
    "probability": {"brier", "bss", "log_loss", "calibration"},
    "derived_probability": {"brier", "bss", "log_loss", "calibration"},
    "outcome_distribution": {"multiclass_log_loss", "multiclass_brier", "rank_topk", "lead_time", "calibration"},
    "probability_map": {"brier", "bss", "log_loss", "rank_topk", "lead_time", "calibration"},
    "scenario_set": {"multiclass_brier", "value_error"},
    "date_estimate": {"abs_error", "bias"},
    "condition_list": {"recall_precision", "status_accuracy", "label_accuracy"},
    "relationship_list": {"recall_precision", "status_accuracy", "label_accuracy"},
    "signal_list": set(),
    "facts": {"field_accuracy"},
}
template_ids = []

for manifest_path in sorted(glob.glob(os.path.join(TEMPLATES, "*", "template.yaml"))):
    tdir = os.path.dirname(manifest_path)
    m = yaml.safe_load(open(manifest_path))
    tid = m.get("id")
    template_ids.append(tid)
    where = rel(manifest_path)
    if tid != os.path.basename(tdir):
        err(f"{where}: id '{tid}' does not match folder name")
    for key in ("subject_schema", "values_schema"):
        if not os.path.exists(os.path.join(tdir, m.get(key, "?"))):
            err(f"{where}: {key} file missing")
    for key in ("params_schema",):
        if key in m and not os.path.exists(os.path.join(tdir, m[key])):
            err(f"{where}: {key} file missing")
    for key in ("inputs_schema",):
        if not os.path.exists(os.path.join(tdir, m.get("baseline", {}).get(key, "?"))):
            err(f"{where}: baseline.{key} file missing")
    ev = m.get("eval", {})
    for key in ("spec", "metrics_schema"):
        if not os.path.exists(os.path.join(tdir, ev.get(key, "?"))):
            err(f"{where}: eval.{key} file missing")

    quantities = m.get("quantities", {})
    for q, spec in quantities.items():
        t = spec.get("type")
        if t not in CORE_TYPES or t not in qt:
            err(f"{where}: quantity {q} has unknown core type {t}")
        if "vocabulary" in spec and not os.path.exists(os.path.join(tdir, spec["vocabulary"])):
            err(f"{where}: quantity {q} vocabulary file missing")
        if t == "derived_probability" and spec.get("derived_from") not in quantities:
            err(f"{where}: {q} derived_from unknown quantity")

    # values_schema composes the matching core types
    vpath = os.path.abspath(os.path.join(tdir, m.get("values_schema", "")))
    vschema = docs.get(vpath, {})
    props = vschema.get("properties", {})
    if set(props) != set(quantities):
        err(f"{where}: values_schema properties {sorted(props)} != manifest quantities {sorted(quantities)}")
    for q, spec in quantities.items():
        refs = [s.get("$ref", "") for s in props.get(q, {}).get("allOf", [])] + [props.get(q, {}).get("$ref", "")]
        want = f"quantity-types.schema.json#/$defs/{spec.get('type')}"
        if not any(r.endswith(want) for r in refs):
            err(f"{where}: values_schema.{q} does not compose core type {spec.get('type')}")

    def need(name, ctx):
        if name != "all" and name not in quantities:
            err(f"{where}: {ctx} names unknown quantity '{name}'")

    for src, dsts in (m.get("dependencies") or {}).items():
        need(src, "dependencies")
        for d in dsts:
            need(d, "dependencies")
    for rule in m.get("impact_rules") or []:
        affects = rule.get("affects")
        for a in ([affects] if isinstance(affects, str) else affects or []):
            need(a, "impact_rules")
    for q in (m.get("scheduled_reestimate") or {}).get("quantities", []) or []:
        need(q, "scheduled_reestimate")
    for q in (m.get("baseline") or {}).get("values", []):
        need(q, "baseline.values")

    rules = qt.get("Rules", {}).get("$defs", {})
    for q, rule in (m.get("thresholds") or {}).items():
        need(q, "thresholds")
        if q in quantities:
            shape = rules.get(RULE_SHAPE[quantities[q]["type"]], {})
            bad = set(rule) - set(shape.get("properties", {}))
            if bad:
                err(f"{where}: thresholds.{q} has keys {sorted(bad)} not in core rule shape for {quantities[q]['type']}")

    for item in m.get("packet_layout") or []:
        if isinstance(item, dict):
            kind = next(k for k in item if k in SECTION_KINDS or k not in ("derived", "baseline", "labels", "show_parties_without_items"))
            if kind not in SECTION_KINDS:
                err(f"{where}: packet_layout kind '{kind}' is not a core section kind")
                continue
            q = item[kind]
            need(q, "packet_layout")
            want = SECTION_KINDS[kind]
            got = quantities.get(q, {}).get("type")
            if want and got and got != want and not (kind == "distribution_table" and got == "outcome_distribution"):
                err(f"{where}: packet_layout {kind} bound to {q} of type {got}")
            if kind == "list_changes" and got and not got.endswith("_list"):
                err(f"{where}: list_changes bound to non-list quantity {q}")
            for d in item.get("derived", []):
                need(d, "packet_layout.derived")

    # RFC-009 conformance rule 5: eval.scores uses registry families valid for each type (RFC-007 §4.1)
    scores = ev.get("scores") or {}
    if not scores:
        err(f"{where}: eval.scores is missing or empty")
    for q, families in scores.items():
        need(q, "eval.scores")
        t = quantities.get(q, {}).get("type")
        allowed = METRIC_FAMILIES.get(t, set()) | ({"vs_baseline"} if q in (m.get("baseline") or {}).get("values", []) else set())
        for fam in families:
            if fam not in allowed:
                err(f"{where}: eval.scores.{q} uses '{fam}', not a registry family for {t}")

    # Rationale RFC must not drift: YAML blocks that restate manifest keys must match the manifest
    if m.get("rationale"):
        rpath = os.path.normpath(os.path.join(tdir, m["rationale"]))
        if not os.path.exists(rpath):
            err(f"{where}: rationale file missing")
        else:
            for block in re.findall(r"```yaml\n(.*?)```", open(rpath).read(), re.S):
                try:
                    y = yaml.safe_load(block)
                except yaml.YAMLError:
                    continue
                if not isinstance(y, dict):
                    continue
                for k, v in y.items():
                    if k in ("thresholds", "params", "routing", "scheduled_reestimate") and k in m:
                        mv = m[k]
                        if isinstance(mv, dict) and isinstance(v, dict):
                            mv = {kk: vv for kk, vv in mv.items() if kk in v}
                        if v != mv:
                            err(f"{rel(rpath)}: YAML block '{k}' differs from {where}")

    outcomes = m.get("outcomes") or {}
    for name, o in outcomes.items():
        if isinstance(o, dict) and "resolves" in o:
            if not o.get("evidence"):
                err(f"{where}: outcome {name} has no resolution evidence")
            need(o.get("quantity"), f"outcome {name}")

    # 3. Example theses: two-stage validation
    for ex in sorted(glob.glob(os.path.join(tdir, "examples", "*.yaml"))):
        thesis = yaml.safe_load(open(ex))
        thesis = json.loads(json.dumps(thesis, default=str))
        for e in registry_validator(os.path.join(CORE, "thesis.schema.json")).iter_errors(thesis):
            err(f"{rel(ex)}: core stage: {e.message} at {list(e.absolute_path)}")
        if thesis.get("template", {}).get("id") != tid:
            err(f"{rel(ex)}: template id mismatch")
        for e in registry_validator(os.path.join(tdir, m["subject_schema"])).iter_errors(thesis.get("subject", {})):
            err(f"{rel(ex)}: subject stage: {e.message} at {list(e.absolute_path)}")
        if "params_schema" in m:
            params = thesis.get("policy", {}).get("template_params", {})
            for e in registry_validator(os.path.join(tdir, m["params_schema"])).iter_errors(params):
                err(f"{rel(ex)}: params stage: {e.message}")
        for src in thesis.get("sources", []):
            if src.get("type") not in m.get("sources_allowed", []):
                err(f"{rel(ex)}: source type {src.get('type')} not in sources_allowed")
        for q in (thesis.get("policy", {}).get("material_change") or {}):
            if q not in quantities:
                err(f"{rel(ex)}: material_change names unknown quantity {q}")

# 4. Core stays template-agnostic -------------------------------------------

TERMS = [re.escape(t) for t in template_ids] + [
    r"neocloud", r"acquirer_distribution", r"p_acquired", r"stake_probabilit", r"talks:", r"hyperscaler",
    r"\brp-1\b", r"\bmi-1\b", r"reference prior", r"close_probability", r"scenarios\b",
]
TERM_RE = re.compile("|".join(TERMS), re.IGNORECASE)
EXAMPLE_RE = re.compile(r"Example \(`[a-z_]+`\)")

for f in glob.glob(os.path.join(CORE, "*.json")):
    for i, line in enumerate(open(f), 1):
        if TERM_RE.search(line):
            err(f"{rel(f)}:{i}: template-specific term in core schema")

for f in sorted(glob.glob(os.path.join(ROOT, "rfc", "00[1-7]-*.md"))):
    lines = open(f).read().split("\n")
    in_example_block = False   # paragraph/code block that starts with an Example marker
    in_example_section = False  # heading containing an Example marker
    in_code = False
    for i, line in enumerate(lines, 1):
        if line.startswith("#"):
            in_example_section = bool(EXAMPLE_RE.search(line))
            in_example_block = False
        if line.strip().startswith("```"):
            in_code = not in_code
            if not in_code:
                continue
        if EXAMPLE_RE.search(line):
            in_example_block = True
        elif not line.strip() and not in_code:
            prev = lines[i - 2] if i >= 2 else ""
            nxt = lines[i] if i < len(lines) else ""
            if not (EXAMPLE_RE.search(prev) and nxt.strip().startswith("```")):
                in_example_block = False
        if line.startswith("Date:"):
            continue
        text = re.sub(r"\]\([^)]*\)", "]", line)  # link targets may name a template folder
        if TERM_RE.search(text) and not (in_example_block or in_example_section or EXAMPLE_RE.search(line)):
            err(f"{rel(f)}:{i}: template-specific term outside a labeled example")

# 5. Relative links -----------------------------------------------------------

LINK_RE = re.compile(r"\]\(([^)#\s]+)(#[^)]*)?\)")
for f in [os.path.join(REPO, "README.md")] + glob.glob(os.path.join(ROOT, "**", "*.md"), recursive=True):
    for i, line in enumerate(open(f), 1):
        for target, _ in LINK_RE.findall(line):
            if re.match(r"^[a-z]+://", target) or target.startswith("mailto:"):
                continue
            if not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(f), target))):
                err(f"{rel(f)}:{i}: broken link {target}")

# ---------------------------------------------------------------------------

if errors:
    print(f"{len(errors)} problem(s):")
    for e in errors:
        print("  " + e)
    sys.exit(1)
print(f"OK: {len(docs)} schemas, {len(template_ids)} templates ({', '.join(template_ids)}), core is template-agnostic, links resolve.")
