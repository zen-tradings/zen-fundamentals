# zen-fundamentals-agent

An open-source, long-running **newsletter agent** exposed as an API. Point it at sources, describe the audience and cadence, pick channels — it continuously monitors, researches, writes, audits, and delivers.

Market-agnostic. Source-agnostic. Model-agnostic.

## What it does

```
sources ──▶ monitor loop ──▶ research ──▶ write ──▶ audit ──▶ deliver
 (web, data,   (continuous,     (parallel   (skill-    (fact,     (email, chat,
  papers, APIs) change-aware)    agents)     guided)    style)     webhook, feed)
```

A **newsletter** is a declarative config, not a workflow:

```yaml
newsletter: ai-infra-weekly
audience: "engineers evaluating inference hardware"
cadence: continuous            # or cron / on-demand
sources:
  - type: web_search           # priority order
    queries: ["inference chips", "GPU pricing"]
  - type: academic_paper
    venues: ["arxiv:cs.AR", "arxiv:cs.LG"]
  - type: data_connector
    connector: github
    repos: ["vllm-project/vllm"]
channels:
  - email:   { provider: resend, list: subscribers }
  - discord: { webhook: $DISCORD_URL }
  - webhook: { url: https://example.com/ingest }
policy:
  budget_usd_per_issue: 0.50
  max_latency_s: 120
  min_primary_sources: 2
```

## API

```
POST   /v1/newsletters              create from config
GET    /v1/newsletters/:id          status, last issue, monitor state
POST   /v1/newsletters/:id/run      trigger one issue now
POST   /v1/newsletters/:id/watch    start / stop the continuous loop
GET    /v1/issues/:id               issue content, sources, audit report, cost
POST   /v1/issues/:id/feedback      reader / editor signal for eval
GET    /v1/skills  ·  /v1/connectors  ·  /v1/channels
```

Streaming via SSE on `/run` for progressive drafts. OpenAPI spec in [`docs/openapi.yaml`](docs/openapi.yaml).

## Design

Ranked by priority.

**Source-agnostic with priority.** Every source implements one adapter interface (`discover → fetch → normalize`). Priority, recency window, and trust tier are per-newsletter config. Evidence is ranked before any model sees it.

**Skills & MCP as the toolset.** Research capabilities are MCP servers or skill packages, not hard-wired code: `web_search`, `data_connector`, `academic_paper` ship by default; add your own. Writing skills are versioned, model-independent, and injected at runtime.

**Context engineering over prompt engineering.** The writer never sees raw search results. A `TaskContract` freezes intent, a `SearchPlan` fans out queries, and an `EvidenceMatrix` ranks, deduplicates, and quota-limits sources by tier before anything enters a context window. Long runs compact accumulated evidence into structured summaries rather than letting the window grow.

**Continuous loops, not cron.** A newsletter in `continuous` mode keeps a monitor agent alive: diff sources, score novelty against prior issues, accumulate evidence, and emit an issue when the threshold is met — or on schedule as a fallback. State persists between cycles.

**Latency as a policy, not a side effect.** `max_latency_s` is enforced, not advisory. Search lanes fan out per source, sections are written concurrently, and audit overlaps with writing; concurrency limits are per-provider and per-tenant rather than one global cap. Speculative drafts stream over SSE while the audit finishes. When the budget is tight, the planner degrades deliberately — fewer sources, lighter reasoning effort, shorter sections — and records what it dropped. Horizontal scaling comes from leased workers ([RFC-003](docs/rfc/003-fencing-token-for-job-execution.md)), not a bigger box.

**Dynamic model routing.** Each role — plan, search, write, audit, translate — is routed at runtime against a per-model capability profile (reasoning depth, tool-call reliability, long-context stability, truncation behavior) scored against the newsletter's cost and latency budget. Reasoning and output token budgets are separate so reasoning can't starve visible output. No fixed model IDs; providers via OpenRouter or direct.

**Subagent orchestration.** A planner partitions an issue into lanes — search per source, one writer per section, an independent auditor — each with its own budget, timeout, and context. Hand-offs are typed artifacts (`EvidenceMatrix`, `SectionDraft`, `AuditReport`), not chat transcripts; a failed lane is isolated and retried or dropped without restarting the issue.

**Durable execution.** Jobs are leased with heartbeats and fencing tokens so a stalled worker can't commit stale results ([RFC-003](docs/rfc/003-fencing-token-for-job-execution.md)). Research, reporting, delivery, and evaluation have separate lifecycle state machines ([RFC-002](docs/rfc/002-job-lifecycle-state-machine.md)). Delivery goes through an idempotent outbox.

**Client-aligned eval, closed loop.** Built-in harness for correctness (labeled cases), auditor trust (defect-injection recall, FN/FP, kappa), and value (reader feedback, editor edit distance). Rubrics are per-newsletter; results feed back into model routing and skill selection.

**Safeguards and permissions.** Every API key is scoped to newsletters, connectors, and channels it may touch; agents get tool-level allowlists per lane. Channels are draft-only unless explicitly granted send. Fail-closed gates on templates, credentials, private-network egress, and unsupported claims — an issue that can't pass is held, never degraded silently.

**Observability.** Per-call telemetry — model, provider, tokens, reasoning tokens, cost, latency, finish reason — with prompts and completions never logged. Per-issue cost and latency roll up against policy; SLO breaches surface on `/v1/newsletters/:id`.

**Multi-channel.** Channel adapters share one template gate; add a channel by implementing `render → publish → confirm`.

## Quick start

```bash
git clone https://github.com/zen-tradings/zen-newsletter-agent
cd zen-newsletter-agent && cp .env.example .env
docker compose up          # api + worker + postgres
curl -X POST localhost:8080/v1/newsletters -d @examples/ai-infra-weekly.yaml
```

## Hosting & monetization

Self-host free under the OSS license. A managed tier is planned:

- **Hosted API** — metered by issues, sources, and latency tier
- **Premium connectors** — paid data feeds, private-doc access
- **Managed newsletters** — we run the loop, you own the list

## Reference

Design lessons draw on [zen-tradings/internal-marketing-agent](https://github.com/zen-tradings/internal-marketing-agent): evidence tiers, role-split models, fail-closed template gates, idempotent delivery, and offline eval.

## Status

Early design. Open RFCs in [`docs/rfc/`](docs/rfc/):

- [001](docs/rfc/001-research-report-separation.md) — shared research layer vs. per-user report layer
- [002](docs/rfc/002-job-lifecycle-state-machine.md) — separate lifecycle state machines
- [003](docs/rfc/003-fencing-token-for-job-execution.md) — fencing tokens for leased execution

Planned: subagent orchestration contract, model capability profiles and routing policy, continuous monitor loop spec.

## License

Apache-2.0
