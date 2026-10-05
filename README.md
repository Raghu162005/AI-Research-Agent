# AI Research Agent

An autonomous research agent that takes a topic, breaks it into subtopics, searches the
web, reads what it finds, cross-checks the evidence, and writes a cited report you can
export as Markdown or PDF.

Runs asynchronously with live progress streaming, so the UI shows the agent's reasoning
as it works instead of a blank spinner for three minutes.

```
Topic  ->  Plan  ->  Search  ->  Analyze  ->  Write  ->  Validated report
             LLM       Tavily      LLM         LLM        + PDF export
```

---

## What it does

- **Decomposes** a topic into subtopics and search queries with an LLM
- **Searches** the live web via Tavily, de-duplicating by URL across every query
- **Reads and analyses** each source against one subtopic, extracting claim/evidence pairs
  with source references, plus **conflicting evidence** and **evidence gaps**
- **Writes** a structured report: executive summary, sections, key takeaways, open questions
- **Validates every citation** against the sources actually retrieved, stripping any
  reference the agent cannot back up
- **Streams progress** over Server-Sent Events, persisting reports to SQLite
- **Exports** Markdown and PDF with clickable, resolvable citation links

Example output on a real run: 20 sources retrieved, 17 cited (85% coverage), 4 sections,
20 findings, 2 conflicts and 15 evidence gaps in ~175 seconds.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Next.js 16 dashboard  (localhost:3000)        │
│  topic input · live timeline · report tabs     │
│  history · .md / .pdf download                  │
└───────────────┬─────────────────────────────────┘
                │  POST /research  →  202 { id }
                │  GET  /research/{id}/events  →  SSE
                ▼
┌─────────────────────────────────────────────────┐
│  FastAPI  (localhost:8000)                      │
│  ┌────────────┐        ┌─────────────────────┐  │
│  │ JobManager │        │  ResearchAgent      │  │
│  │ thread pool│───────>│                     │  │
│  │ + event bus│        │  plan   → LLM       │  │
│  └────────────┘        │  search → Tavily    │  │
│        │               │  analyze → LLM      │  │
│        │               │  write   → LLM      │  │
│        │               │  validate citations │  │
│        ▼               └──────────┬──────────┘  │
│  ┌────────────┐                  │             │
│  │  SQLite    │◄─────────────────┘             │
│  │  reports   │        Groq (LLM)                │
│  └────────────┘                                │
│  ┌────────────┐                                │
│  │  reportlab │ → PDF w/ citation links        │
│  └────────────┘                                │
└─────────────────────────────────────────────────┘
```

### Design decisions worth knowing

**Jobs are asynchronous.** A full run makes six sequential LLM calls and takes ~3 minutes.
A synchronous request would time out and give the user no feedback. `POST /research`
returns `202` immediately with an ID; the frontend follows the ID over SSE.

**Job state is in-memory, report state is in SQLite.** Progress events are ephemeral and
per-process; finished reports are durable. Because that split means a restart can strand
rows in `running`, startup reconciliation marks them failed with an explanatory error
rather than leaving the dashboard spinning forever.

**Citations are validated against retrieved sources, not trusted.** LLMs fabricate
plausible-looking references. Every `[n]` in the output is checked against the set of
sources actually retrieved and removed if it doesn't correspond to one. Coverage
(cited / retrieved) is surfaced in the UI so you can see how well-sourced a report is.

**Prompts are budgeted.** Snippets are truncated and the assembled prompt is capped at
`MAX_PROMPT_CHARS`, because the free-tier token-per-minute limit rejects oversized
requests outright.

**Rate limits are retried, not surfaced.** See "Bugs found and fixed" below.

---

## Tech stack

| Layer     | Choice                                                        |
| --------- | ------------------------------------------------------------- |
| LLM       | Groq (`openai/gpt-oss-120b`)                                  |
| Search    | Tavily (`tavily-python`)                                      |
| API       | FastAPI + Uvicorn, Pydantic v2 schemas                        |
| Storage   | SQLite (stdlib `sqlite3`, no ORM)                             |
| PDF       | ReportLab                                                      |
| Frontend  | Next.js 16 (App Router), React 19, Tailwind 4                 |
| Markdown  | `react-markdown` + `remark-gfm`                               |
| Testing   | Plain assertion scripts (`stdlib` only, no test framework)    |

Runtime dependencies are pinned exactly in `backend/requirements.txt`.

---

## Setup

### Prerequisites

- Python 3.10+
- Node.js 20+
- A free-tier [Groq](https://console.groq.com) API key
- A free-tier [Tavily](https://tavily.com) API key

### 1. Backend

```bash
cd backend

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
pip install -r requirements-dev.txt   # needed only to run the tests

copy .env.example .env        # Windows
# cp .env.example .env        # macOS / Linux
```

Fill in your keys in `backend/.env`:

```ini
GROQ_API_KEY=gsk_...
TAVILY_API_KEY=tvly_...
```

Start it:

```bash
python -m uvicorn app.main:app --reload --port 8000
```

API docs at <http://localhost:8000/docs>.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard at <http://localhost:3000>.

If you serve the backend somewhere other than `127.0.0.1:8000`, set the frontend's
`NEXT_PUBLIC_API_URL` and add the frontend's origin to the backend's `CORS_ORIGINS`.

---

## Configuration

All backend settings are environment variables read from `backend/.env`.

| Variable                  | Default                     | Purpose                                            |
| ------------------------- | --------------------------- | -------------------------------------------------- |
| `GROQ_API_KEY`            | *required*                  | Groq credentials                                   |
| `GROQ_MODEL`              | `openai/gpt-oss-120b`       | LLM model                                          |
| `GROQ_TEMPERATURE`        | per-model                   | Defaults to `1.0` for `gpt-oss`, else `0.2`        |
| `LLM_MAX_RETRIES`         | `5`                         | Attempts per LLM call                              |
| `LLM_RETRY_BASE_DELAY`    | `2.0`                       | Exponential backoff base, seconds                  |
| `LLM_RETRY_MAX_DELAY`     | `45.0`                      | Backoff ceiling, seconds                           |
| `TAVILY_API_KEY`          | *required*                  | Tavily credentials                                 |
| `TAVILY_SEARCH_DEPTH`     | `advanced`                  | Tavily search depth                                |
| `MAX_SUBTOPICS`           | `4`                         | Subtopics per plan (also sets LLM call count)      |
| `MAX_QUERIES`             | `5`                         | Search queries per plan                            |
| `RESULTS_PER_QUERY`       | `4`                         | Tavily results per query                           |
| `MAX_SNIPPET_CHARS`       | `1200`                      | Per-source snippet cap                             |
| `MAX_PROMPT_CHARS`        | `14000`                     | Assembled prompt cap                               |
| `MAX_CONCURRENT_JOBS`     | `1`                         | Parallel jobs — keep at `1` on the free tier       |
| `CORS_ORIGINS`            | `localhost:3000,127.0.0.1:3000` | Comma-separated allowed origins                |

---

## API

| Method   | Path                          | Description                                    |
| -------- | ----------------------------- | ---------------------------------------------- |
| `GET`    | `/`                           | Service banner and endpoint list               |
| `GET`    | `/health`                     | Status and active model                        |
| `POST`   | `/research`                   | Start a job. `202` with `{ id, status }`       |
| `GET`    | `/research/{id}`              | Full report, plan, sections, sources, events   |
| `GET`    | `/research/{id}/events`       | SSE progress stream until a terminal event     |
| `GET`    | `/research/{id}/report.md`    | Download Markdown                              |
| `GET`    | `/research/{id}/report.pdf`   | Download PDF                                   |
| `GET`    | `/reports`                    | History, newest first (`?limit=`)              |
| `DELETE` | `/research/{id}`              | Delete a report                                |

Start a job:

```bash
curl -X POST http://localhost:8000/research \
  -H "Content-Type: application/json" \
  -d '{"topic":"Retrieval augmented generation for enterprise search"}'
# {"id":"3698dcb58da6","topic":"...","status":"queued","created_at":"..."}
```

Follow it:

```bash
curl -N http://localhost:8000/research/3698dcb58da6/events
# event: progress
# data: {"stage":"search","percent":29,"message":"Searching \"rag evaluation\"", ...}
```

---

## Tests

153 assertions across three suites. No API keys and no network access required — the LLM
and search layers are injected as fakes.

```bash
cd backend
python tests/test_llm.py      # 32  retry/backoff, attempt accounting, JSON fallback
python tests/test_agent.py    # 72  pipeline, citations, dedup, store recovery
python tests/test_api.py      # 49  API, SSE, downloads, restart recovery
```

Frontend:

```bash
cd frontend
npm run lint
npx tsc --noEmit
npm run build
```

---

## Bugs found and fixed

These were found by actually running the thing, and are the most interesting part of
the project.

**1. API keys committed to a tracked file.** `GROQ_API_KEY` had been pasted into
`.env.example`, which is the file you commit. Moved to `.env`, template restored to
placeholders.

**2. Decommissioned model.** `llama-3.3-70b-versatile` returns `404`. Switched to
`openai/gpt-oss-120b`, which requires `temperature=1.0`; the original `0.2` produced
degenerate output. `config.py:_resolve_temperature` now enforces this per model, so the
failure cannot silently reappear.

**3. Rate limits killed jobs outright.** The free tier allows 8,000 tokens/minute
*in total*. With `MAX_CONCURRENT_JOBS=2` the app would happily accept a second job that
could not possibly finish — one failed with
`Limit 8000, Used 3036, Requested 5917`. Fixed properly rather than by hiding the error:

- concurrency defaults to `1`, so work is serialized
- `LLMClient` classifies failures and retries only what is worth retrying (429, 5xx,
  timeouts), never a `400`
- backoff is exponential with jitter, and **parses the provider's own
  `Please try again in 7.1475s` hint** to wait exactly as long as advised
- retried attempts are logged, not swallowed

**4. Dashboard hung forever after a restart.** Job state is in-memory; the SQLite row
outlives the process. After a restart mid-run the row stayed `running`, so the SSE handler
never reached a terminal event and streamed keep-alives indefinitely — the UI spun with
no error and no way out. Startup now reconciles stranded rows into `failed` with a clear
reason. Verified against the live server, not only in tests.

**5. Snippet truncation overshot its budget.** `_truncate` appended the `" ..."` ellipsis
*after* slicing, producing 1204-character snippets against a 1200 limit — in the exact
helper whose job is to enforce that limit. The ellipsis is now inside the budget.

**6. Citations above 99 were never validated.** The pattern `\[(\d{1,2})\]` matched only
one- and two-digit references, so a fabricated `[100]` passed straight through. Widened
to three digits, with a regression test confirming a four-digit year like `[2024]` is
still not mistaken for a citation.

**7. A method shadowed a builtin.** `ReportStore.list()` made `list` resolve to a method
inside the class body, so every later `list[...]` annotation raised
`TypeError: 'function' object is not subscriptable`. Renamed to `list_reports`.

**8. `executive_summary` was generated, then dropped.** The writer produced it and the
assembler never rendered it, so the most useful part of each report was silently missing.

**9. N+1 query on the history endpoint.** `/reports` fetched up to 50 full rows including
every report body, then issued a second query per row. Replaced with a summary projection.

**10. Groq's JSON validator rejected valid JSON.** A real run failed with
`json_validate_failed`, and the `failed_generation` in the error was, on inspection,
completely well-formed — properly escaped, correctly closed. The provider's validator was
the thing failing, not the model, and there was no way around it. `complete_json` now
falls back to generating without `response_format` and parses the text itself, using
lenient extraction that handles prose-wrapped and fenced JSON and repairs trailing commas.
The same fallback covers the case where strict mode succeeds but returns unparseable
prose. The run that previously failed now completes, with the fallback visible in the logs.

**11. An error message reported the wrong number of attempts.** Failures always claimed
`after 6 attempt(s)` — the configured maximum — even when a non-retryable `400` had failed
on the very first call. This actively misled debugging: it suggested six attempts and a
long backoff had occurred when exactly one request had been made, which is why the failure
appeared instantly. The count is now the number of attempts genuinely made.

---

## Known limitations

- **Job state is per-process.** Running multiple workers would each have their own job
  registry. Fine locally; move to Redis or Celery before deploying at scale.
- **Two processes, no containerization.** There is no Dockerfile or compose file yet.
- **`npm audit` reports 5 high-severity advisories.** All of them are in the
  `eslint-config-next` devDependency chain (`braces` → `micromatch` → `fast-glob`) and do
  not affect the production build: `npm audit --omit=dev` reports **0 vulnerabilities**.
  `braces@3.0.3` is the latest release and no upstream fix exists, so the automated remedy
  is a downgrade to `eslint-config-next@14` that would break linting for Next 16. Left
  deliberately unfixed.
- **Not deployed.** Verified locally only.

---

## License

MIT
