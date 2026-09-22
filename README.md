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

**Skills & MCP as the toolset.** Research capabilities are MCP servers or skill packages, not hard-wired code: `web_search`, `data_connector`, `academic_paper` ship by default; add your own. Writing skills are versioned, model-independent, and injected at runtime.

**Source-agnostic with priority.** Every source implements one adapter interface (`discover → fetch → normalize`). Priority, recency window, and trust tier are per-newsletter config. Evidence is ranked before any model sees it.

**Dynamic model routing.** Each role — plan, search, write, audit, translate — is routed at runtime by cost, latency, and quality signals against the newsletter's budget. No fixed model IDs; providers via OpenRouter or direct.

**Continuous loops, not cron.** A newsletter in `continuous` mode keeps a monitor agent alive: diff sources, score novelty, accumulate evidence, and emit an issue when the threshold is met — or on schedule as a fallback.

**Parallel, multi-agent execution.** Search lanes, section writers, and auditors run concurrently; latency is a first-class policy knob alongside cost and evidence quality.

**Client-aligned eval.** Built-in harness for correctness (labeled cases), auditor trust (defect-injection recall, FN/FP), and value (reader feedback, editor edit distance). Rubrics are per-newsletter.

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

Early design. See [`docs/`](docs/) for the roadmap.

## License

Apache-2.0
