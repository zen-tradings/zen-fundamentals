# zen-fundamentals-agent

An open-source, long-running **fundamental analysis agent** exposed as an API. Point it at sources, describe the audience and cadence, pick channels — it continuously monitors, researches, writes, audits, and delivers.

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
PUT    /v1/newsletters/:id          revise config; supersedes any unpublished run
POST   /v1/newsletters/:id/run      trigger one issue now  (?dry_run=true → no publish)
POST   /v1/newsletters/:id/watch    start / stop the continuous loop
GET    /v1/issues/:id               content, sources, trace, audit report, cost
DELETE /v1/issues/:id               cancel; aborts in-flight work, refuses once publish began
POST   /v1/issues/:id/answer        resolve a needs_input question
POST   /v1/issues/:id/approve       release a needs_review issue to channels
POST   /v1/issues/:id/feedback      reader / editor signal for eval
GET    /v1/skills  ·  /v1/connectors  ·  /v1/channels
```

Streaming via SSE on `/run` for progressive drafts. OpenAPI spec in [`design/openapi.yaml`](design/openapi.yaml).

## Design

Ranked by priority.

1. **Source-agnostic.** One adapter interface (`discover → fetch → normalize`); priority, recency, and trust tier are config. Evidence is ranked before any model sees it.
2. **Skills & MCP.** `web_search`, `data_connector`, `academic_paper` ship as MCP servers; writing skills are versioned and model-independent.
3. **Context engineering.** `TaskContract → SearchPlan → EvidenceMatrix` — the writer sees ranked, deduplicated, quota-limited evidence, never raw results. Long runs compact instead of growing.
4. **Continuous loops.** A monitor agent diffs sources, scores novelty, and emits an issue on threshold — cron is the fallback.
5. **Latency as policy.** `max_latency_s` is enforced. Lanes fan out per source and section, audit overlaps writing, drafts stream over SSE. Under budget pressure the planner degrades deliberately and logs what it dropped.
6. **Dynamic model routing.** Each role routed at runtime against capability profiles (reasoning, tool-call reliability, long-context stability) vs. cost/latency budget. Separate reasoning and output token budgets.
7. **Subagent orchestration.** Lanes with own budget, timeout, and context; typed artifact hand-offs (`EvidenceMatrix`, `SectionDraft`, `AuditReport`); failed lanes isolated, not restarted.
8. **Durable execution.** Leased workers with fencing tokens ([RFC-003](design/rfc/003-fencing-token-for-job-execution.md)), separate lifecycle state machines ([RFC-002](design/rfc/002-job-lifecycle-state-machine.md)), idempotent delivery outbox.
9. **Closed-loop eval.** Correctness (labeled cases), auditor trust (defect-injection recall, kappa), value (reader feedback, edit distance). Per-newsletter rubrics feed back into routing.
10. **Safeguards & permissions.** Scoped API keys, per-lane tool allowlists, draft-only by default, staged audience rollout (`internal → pilot → full`), fail-closed gates — held, never silently degraded.
11. **Job lifecycle.** Issues move `queued → running → needs_input | needs_review | published | cancelled`. Revising config supersedes the unpublished run; cancel aborts in-flight calls and deletes artifacts but is refused once a channel write starts. Retries survive restarts and honor `Retry-After`; a terminal failure never rewrites a success. Cron runs key on business date with a bounded catch-up window, so restarts neither skip nor double-send. Terminal runs and traces expire by TTL.
12. **Observability.** Content-free per-call telemetry (model, tokens, cost, latency, finish reason); per-issue SLO rollups on the API.
13. **Multi-channel.** Adapters implement `render → publish → confirm` behind one template gate.

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

Early design. Open RFCs in [`design/rfc/`](design/rfc/):

- [001](design/rfc/001-research-report-separation.md) — shared research layer vs. per-user report layer
- [002](design/rfc/002-job-lifecycle-state-machine.md) — separate lifecycle state machines
- [003](design/rfc/003-fencing-token-for-job-execution.md) — fencing tokens for leased execution

Planned: subagent orchestration contract, model capability profiles and routing policy, continuous monitor loop spec.

## License

Apache-2.0
