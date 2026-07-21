# Design — zen-newsletter-agent

> Initial design, v0.2. Covers multi-user architecture, data storage, result
> observability, and real-time market signal detection. Draft — refine as the
> project grows.

## 1. Goal

A market-research agent that turns market-data signals and user requests into
research reports / newsletters, delivered per-user via customer.io.

Two things trigger work:

1. **User requests** — a user (via the voice agent intake) asks a research
   question ("what's driving the move in semis this week?").
2. **Market signals** — the signal-monitoring pipeline detects something
   noteworthy (price move, volume spike, news event) and automatically spawns
   research for users subscribed to that signal.

**Success looks like:** multiple users can fire multiple concurrent requests;
each gets a well-researched, personalized report; nothing is lost on a crash;
and we can observe both *system health* (latency, cost, failures) and *result
quality* (was the report actually good?).

### Non-goals (v1)

- A web dashboard / UI — intake is the voice agent + API only.
- Sub-second signal latency — v1 targets minutes, not milliseconds (this is
  research, not execution).
- Fully autonomous trading actions. The agent researches and reports; it never
  places orders.

## 2. High-Level Architecture

```
 Users (voice agent)          Market data / news feeds
        │                              │
        ▼                              ▼
 ┌─────────────┐            ┌──────────────────────┐
 │   Intake    │            │  Signal Detection    │
 │ (auth, user │            │  Pipeline            │
 │  _id, quota)│            │  (rules → LLM class.)│
 └──────┬──────┘            └──────────┬───────────┘
        │  creates job                 │  creates jobs (per matched user,
        ▼                              ▼   deduped & coalesced)
 ┌──────────────────────────────────────────────┐
 │              Job Queue (Postgres)            │
 │  research_jobs: status, user_id, priority    │
 └──────────────────┬───────────────────────────┘
                    │  workers pull (SKIP LOCKED)
                    ▼
 ┌──────────────────────────────────────────────┐
 │        Research Agent — worker pool          │
 │  tools: github/code · papers · web search    │
 │  state: per-request ctx │ per-user memory    │
 │         │ global knowledge base              │
 └──────────────────┬───────────────────────────┘
                    ▼
 ┌──────────────────────────────────────────────┐
 │             Content Pipeline                 │
 │  render report → per-user personalization    │
 └───────┬──────────────────────┬───────────────┘
         ▼                      ▼
   customer.io          Result Observation
   (delivery,           & Evaluation
    per user)           (LLM judge + engagement
                         + user feedback)
```

## 3. Request Lifecycle

Every unit of work is a **job** with a stable ID and an owner:

```
queued → running → (succeeded | failed | cancelled)
```

1. **Create** — intake or signal pipeline inserts a `research_jobs` row
   (`user_id`, `trigger` = user|signal|scheduled, payload, priority).
2. **Claim** — a worker claims the oldest eligible job with
   `SELECT ... FOR UPDATE SKIP LOCKED`, respecting per-user concurrency caps.
3. **Research** — the worker runs the agent loop (tools + LLM) in an isolated
   per-request context; emits `job_events` at every stage.
4. **Produce** — the content pipeline renders the report, stores it in
   `reports`, and hands it to delivery.
5. **Deliver** — customer.io sends to the owning user; delivery result recorded.
6. **Evaluate** — the observation loop scores the report (async, non-blocking).

A crashed worker's job has a `claimed_at` lease; a reaper re-queues jobs whose
lease expired. Every step is idempotent on `job_id`, so retries are safe.

## 4. Multi-User Architecture

### Job queue instead of direct invocation

With many users (and one user firing several requests), intake never runs
research synchronously — it enqueues. This decouples arrival rate from
processing rate. **v1 uses Postgres as the queue** (`FOR UPDATE SKIP LOCKED`);
no Redis/Kafka until scale demands it — one fewer system to operate, and the
queue is transactional with the rest of our data.

### State is tiered — the key isolation rule

| Tier | Contents | Keyed by | Lifetime |
|---|---|---|---|
| **Per-request** | agent working context, tool-call scratch, intermediate notes | `job_id` | job duration |
| **Per-user** | preferences, watchlist, delivery settings, past reports, personal memory | `user_id` | persistent |
| **Global** | signals, cached sources (papers, repos, web pages), shared knowledge base | — | persistent, read-mostly |

Rules: parallel jobs never share per-request context (no cross-contamination);
agent code reaches per-user and global state only through a narrow interface
(`get/put/search`), never ad-hoc queries — so the backend stays swappable.

### Fairness & quotas

- **Per-user concurrency cap** (default 2 running jobs); excess requests queue.
- **Per-user daily token budget** — research is LLM-expensive; a runaway user
  must not exhaust the shared Claude API rate limits. Track token usage per job
  (the API returns it in `usage`) and roll up per user per day.
- **Global worker pool cap** sized to our API rate limits; one shared
  rate-limiter in front of LLM and tool calls.
- **Priority**: user-initiated > signal-initiated > scheduled digests.

### Deduplication & coalescing

- User requests: hash of normalized query + time bucket → if an equivalent job
  completed recently, serve the cached report (marked as such).
- Signal-initiated: N users subscribed to the same signal share **one** research
  job; only rendering/personalization fans out per user. Research once, deliver
  N times.

## 5. Data Storage

**Backend: Supabase (Postgres + pgvector).** Already in our stack, gives us the
job queue, relational data, and vector search for the knowledge base in one
system, plus row-level security if we later expose data to users directly.

Core tables (columns abridged):

```sql
users           (id, email, prefs jsonb, quota jsonb, created_at)
watchlists      (user_id, symbol, signal_types text[], min_severity)

research_jobs   (id, user_id, trigger, status, priority, payload jsonb,
                 signal_id, dedup_key, claimed_at, lease_expires_at,
                 started_at, finished_at, error, token_usage jsonb)

signals         (id, source, symbol, type, severity, payload jsonb,
                 dedup_key unique, detected_at)

source_cache    (id, url_hash unique, url, content, content_type,
                 fetched_at, expires_at)
knowledge_base  (id, content, embedding vector, metadata jsonb,
                 source_ref, created_at)          -- pgvector, global tier
user_memory     (id, user_id, kind, content, updated_at)  -- per-user tier

reports         (id, job_id, user_id, subject, body_md, body_html,
                 created_at)
deliveries      (id, report_id, user_id, channel, customerio_message_id,
                 status, delivered_at, opened_at, clicked_at)

job_events      (id, job_id, ts, stage, event, payload jsonb)  -- observability
evaluations     (id, report_id, evaluator, scores jsonb, feedback,
                 created_at)
```

Notes:

- **`job_events` is append-only** — the trace of everything a job did (tool
  calls, sources fetched, model calls with token counts). Cheap to write, and
  it *is* our audit trail and debugging surface.
- **`source_cache` is the cost lever**: every fetched paper/page/repo README is
  cached with a TTL so concurrent jobs about the same event don't re-fetch or
  re-summarize.
- **Knowledge base** entries are embedded (pgvector) for retrieval during
  research; entries carry `source_ref` so reports can cite provenance.
- Secrets are never stored in these tables; see §9.

## 6. Real-Time Market Signal Detection

### Sources

- **Market data** — price/volume via broker or market-data API (we have IBKR
  access; its price-snapshot/history endpoints are the v1 candidate).
- **News/feeds** — RSS/Atom from curated financial sources; macro calendar.
- Later: filings (EDGAR), social, GitHub activity for tech coverage.

### Two-stage detection (cost control by design)

**Stage 1 — deterministic rules, no LLM.** A poller evaluates cheap rules per
symbol on each tick: price move > X% in window, volume > N× average,
volatility spike, keyword match on headlines, calendar event imminent.
Output: *candidate events*. This stage handles the full firehose.

**Stage 2 — LLM classification, candidates only.** Each candidate is classified
and enriched by a small, fast model (Claude Haiku 4.5 — cheap, and the task is
single-turn classification): is this genuinely noteworthy, what type, severity
1–5, one-line rationale. Only survivors become `signals` rows.

This ordering means LLM spend scales with *interesting* events, not with tick
volume.

### From signal to work

```
tick/headline → rules → candidate → LLM classify → signal (deduped)
              → match user watchlists → coalesce → research job(s)
```

- **Dedup**: `dedup_key = (source, symbol, type, time_bucket)` with a unique
  constraint — the same underlying event from two feeds inserts once.
- **Coalescing**: related signals inside a window (same symbol, same story)
  merge into one research job rather than N.
- **Backpressure**: cap auto-spawned jobs per hour; below-threshold severity
  goes to the daily digest instead of immediate research.

### “Real-time” posture

v1 is a **polling loop** (configurable, e.g. 30–60s for prices, minutes for
feeds) — simple, testable, and fits “minutes not milliseconds.” The poller sits
behind a `SignalSource` interface, so a websocket/streaming consumer can
replace it later without touching rules or anything downstream.

## 7. Research Agent

- **LLM:** Claude API via the Anthropic SDK. Research/writing runs on
  **`claude-opus-4-8`** (adaptive thinking, effort tuned per trigger:
  `high` for user requests, `medium` for signal-initiated). Signal
  classification runs on **`claude-haiku-4-5`**. Model IDs live in config.
- **Agent loop:** the SDK **tool runner** (`client.beta.messages.tool_runner`)
  — we define tools as typed functions, the SDK drives the loop.
- **Tools** (each a public API per our interface conventions — typed schema,
  model-facing description, structured returns, errors as values):
  `search_web`, `fetch_url`, `search_papers`, `get_repo_readme` /
  `search_code`, `query_knowledge_base`, `get_market_data`.
- Every tool call and model call is logged to `job_events` with token usage.

## 8. Content Pipeline & Delivery

- Renders the agent's research into the report format (markdown → HTML
  template), applies per-user personalization (name, watchlist framing,
  verbosity preference).
- **Delivery via customer.io** (transactional API). `deliveries` stores the
  customer.io message ID so webhook callbacks (delivered/opened/clicked) can be
  joined back — that's the engagement half of observability.
- **`--dry-run` is the default in development**: render to file/stdout, never
  send. A half-built report is never delivered — the pipeline only picks up
  jobs in `succeeded` state.

## 9. Result Observability

Two layers, deliberately separate:

### 9a. System observability — "is the pipeline healthy?"

- **Per-job tracing** via `job_events`: every stage transition, tool call,
  model call (with tokens/cost), and error, keyed by `job_id`. A job's full
  history is one indexed query.
- **Metrics derived from tables** (v1: SQL views; later: dashboards/alerts):
  queue depth & age, job latency by stage, failure rate by error class, token
  cost per job / per user / per day, signal counts by type, cache hit rate.
- **Alerts** (v1: simple threshold checks → Slack): queue age > N min, failure
  rate spike, daily token budget nearing limit, signal poller silent > M min
  (a silent poller looks like "no signals" — it must alarm, not just idle).

### 9b. Result quality — "was the report actually good?"

The **Result Observation & Evaluation** loop, three inputs written to
`evaluations`:

1. **LLM-as-judge** (async, after delivery): a rubric-scored pass over each
   report — accuracy vs. cited sources, relevance to the trigger, timeliness,
   actionability, hallucination check (are all claims traceable to a
   `job_events` source fetch?). Scores 1–5 per axis + rationale.
2. **Engagement signals** from customer.io webhooks: opens, clicks,
   unsubscribes — joined via `deliveries`.
3. **Explicit user feedback**: the voice agent can ask "was that useful?";
   thumbs-up/down links in the report footer.

**Closing the loop:** evaluation scores aggregate per source, per signal type,
and per prompt version — low-scoring sources get down-weighted in curation,
and prompt changes are judged against the eval baseline before rollout. Prompt
versions are recorded on each job so scores are attributable.

## 10. Failure Handling

- **Signal pipeline**: a failing source is logged and skipped — one dead feed
  never stops detection; the silent-poller alert (§9a) catches total stalls.
- **Research jobs**: transient LLM/tool errors retry with backoff (the SDK
  retries 429/5xx itself); after N job-level retries → `failed` with the error
  recorded, user notified only for user-initiated jobs.
- **Worker crash**: lease expiry re-queues the job (§3); idempotency on
  `job_id` prevents double delivery.
- **Delivery**: never send twice — `deliveries` insert is keyed by
  (`report_id`, `channel`); customer.io failures retry, then mark failed.
- **The queue is the safety net**: nothing is in-memory-only; a full process
  restart loses no accepted work.

## 11. Configuration & Secrets

- Non-secret config (sources, rule thresholds, model IDs, effort levels,
  quotas, polling intervals) in versioned config files.
- Secrets (Anthropic API key, customer.io key, market-data credentials,
  Supabase service key) via env / `.env` (git-ignored); `.env.example`
  documents required vars. Secrets never enter prompts, logs, or the DB.

## 12. Roadmap

**v1 (MVP)**
- [ ] Schema migration for §5 tables (Supabase)
- [ ] Job queue + single worker + lease/reaper
- [ ] Research agent with web-search + fetch tools (tool runner, Opus 4.8)
- [ ] Rule-based signal poller (prices via IBKR, one RSS source) + Haiku classification
- [ ] Content pipeline with `--dry-run`; customer.io delivery behind a flag
- [ ] `job_events` tracing + basic SQL metric views
- [ ] Per-user concurrency cap + daily token budget

**v2**
- [ ] LLM-as-judge evaluation pass + engagement webhook ingestion
- [ ] Knowledge base with pgvector retrieval + source caching
- [ ] Paper-search and code-search tools; watchlist-driven signal routing
- [ ] Dedup/coalescing of signal jobs; scheduled digests

**Later**
- [ ] Streaming market-data consumer (replace poller behind `SignalSource`)
- [ ] Eval-driven source weighting and prompt-version gating
- [ ] Multi-worker autoscaling; move queue off Postgres only if measurements demand it
