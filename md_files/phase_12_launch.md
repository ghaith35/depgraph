# DepGraph — Phase 12: Observability + Launch Readiness

## Goal

Ship it. Cloudflare in front of Render. Logging in structured JSON. `/metrics` accessible. Cron-based warmup. README with screenshots and architecture. Demo video. Load test to verify graceful degradation.

## Deliverable

Public URL. Portfolio-grade README. A working demo of the app surviving a synthetic 40-concurrent-SSE load. All the scalability concerns from the plan actually tested, not just hypothesized.

---

## Cloudflare in front of Render (free tier)

Sign up for Cloudflare free. Add the domain (if custom domain) or use a Cloudflare Workers URL as a proxy.

### DNS

- Custom domain (recommended): e.g. `api.depgraph.dev` → CNAME to the Render-provided URL. Proxy enabled (orange cloud).
- No custom domain: skip Cloudflare proxy, accept Render's hostname directly.

### Cloudflare settings

- **Caching:** cache `/healthz` (60s) and `/demos/*` (1 day). Do NOT cache `/analyze`, `/stream`, `/explain`, `/metrics`.
- **Security level:** Medium.
- **Bot fight mode:** on (free tier version).
- **Rate limiting rule:** 100 requests per minute per IP on `/*`, 10 per minute on `/analyze`. Custom challenge page for exceeders.
- **WAF:** default managed rules enabled.
- **Always Use HTTPS:** on.
- **HSTS:** on, 6 months.

### Testing Cloudflare config

```bash
curl -I https://your-domain/healthz
# Expect cf-cache-status: HIT on second call

curl -I https://your-domain/stream/fake
# Expect cf-cache-status: BYPASS or DYNAMIC
```

---

## Warmup cron

Render's free dyno sleeps after 15 minutes of no traffic. For portfolio purposes, we want it warm during likely traffic windows.

**GitHub Actions workflow at `.github/workflows/warmup.yml`:**

```yaml
name: Warmup Render
on:
  schedule:
    - cron: "*/14 * * * *"  # every 14 minutes
  workflow_dispatch:

jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - name: Ping healthz
        run: |
          curl -fsS https://your-domain/healthz || exit 1
```

This runs every 14 minutes — just under Render's 15-minute sleep threshold. GitHub Actions free tier has 2000 minutes/month; at ~5 seconds per ping × ~3000 pings/month = 250 minutes. Well within budget.

**Ethical note:** this is skirting Render's free-tier intent. If you're uncomfortable, disable the cron and accept cold starts. For the portfolio demo window (first week post-launch), keeping warm makes sense.

---

## Structured logging

Replace `print` and default Python logging with JSON-structured logs throughout. Use `structlog` or `loguru`.

**Format:**
```json
{
  "ts": "2026-04-20T12:34:56.789Z",
  "level": "info",
  "event": "pipeline_stage_complete",
  "job_id": "abc123",
  "stage": "parse",
  "duration_ms": 2341,
  "files_processed": 187
}
```

**Events to emit:**
- `job_start` — new analysis requested.
- `job_queued` — job waiting for semaphore slot.
- `pipeline_stage_start` / `pipeline_stage_complete` — per stage of the backend pipeline.
- `job_complete` — total pipeline time.
- `job_error` — with error type and stage.
- `cache_hit` / `cache_miss` — with tier.
- `cache_evict` — Janitor actions.
- `rate_limit_rejected` — with IP (hashed for privacy), retry_after.
- `ai_stream_start` / `ai_stream_complete` / `ai_stream_error`.
- `sse_client_disconnect` — mid-stream close.
- `memory_shed` — adaptive shedding kicked in (Phase 5).

No user content in logs. No full file paths from the cloned repo. Just metadata.

---

## `/metrics` endpoint (enhanced from Phase 9)

Already implemented in Phase 9. Add rolling-window latencies per pipeline stage:

```python
class LatencyWindow:
    """Rolling 5-minute window of stage durations."""
    def __init__(self):
        self.samples: deque[tuple[float, float]] = deque()  # (timestamp, duration_ms)

    def record(self, duration_ms: float):
        now = time()
        self.samples.append((now, duration_ms))
        while self.samples and self.samples[0][0] < now - 300:
            self.samples.popleft()

    def percentile(self, p: float) -> float:
        if not self.samples:
            return 0.0
        sorted_durations = sorted(d for _, d in self.samples)
        idx = int(len(sorted_durations) * p)
        return sorted_durations[min(idx, len(sorted_durations) - 1)]
```

Exposed at `/metrics`:
```json
{
  "stages": {
    "clone":    {"p50": 3200, "p95": 7800, "p99": 15000, "count": 47},
    "walk":     {"p50": 85,   "p95": 180,  "p99": 320,   "count": 47},
    "parse":    {"p50": 1200, "p95": 3500, "p99": 8000,  "count": 47},
    "resolve":  {"p50": 80,   "p95": 150,  "p99": 290,   "count": 47},
    "cycles":   {"p50": 12,   "p95": 45,   "p99": 110,   "count": 47},
    "total":    {"p50": 4800, "p95": 11000,"p99": 22000, "count": 47}
  },
  ...
}
```

---

## Synthetic load test

Goal: verify graceful degradation per the scalability plan, not real scale.

**Tool:** `oha` (Rust-based, lightweight) or `vegeta`. Install locally.

**Test 1 — sustained light load:**
```bash
oha -n 100 -c 5 -z 60s https://your-domain/healthz
```
Expect: all 200, p99 < 500ms.

**Test 2 — SSE saturation:**
Custom script opening 40 concurrent EventSources to `/stream/<job_id>` (use a pre-cached job_id that streams the same fixture):
```bash
# Use a shell loop + curl
for i in $(seq 1 40); do
  curl -N https://your-domain/stream/fake-job-$i > /tmp/stream_$i.log 2>&1 &
done
wait
```
Expect: all 40 receive events, no connection drops.

**Test 3 — queue saturation:**
```bash
oha -n 20 -c 10 -m POST -T 'application/json' \
  -d '{"url":"https://github.com/tiangolo/fastapi"}' \
  https://your-domain/analyze
```
With concurrency cap at 2, expect most requests to get queued-status events, no 5xx errors, eventual completion.

**Test 4 — rate limit:**
```bash
oha -n 20 -c 1 -m POST -T 'application/json' \
  -d '{"url":"https://github.com/x/y"}' \
  https://your-domain/analyze
```
Expect: first 5 succeed (or 404 for fake URL — either way, pass the rate limit), next 15 return 429 with Retry-After.

Run all four tests. Capture `/metrics` before and after. Document results in README.

---

## README structure

`/README.md` at the repo root:

```markdown
# DepGraph

Paste a GitHub URL, get a live dependency graph of the codebase.

[Live demo](https://your-domain) · [Video](link) · [How it works](#architecture)

![screenshot.png]

## Features
- Interactive force-directed graph of file-level imports.
- Support for 7 languages (JS, TS, Python, Java, Go, Rust, C/C++).
- Circular dependency detection with full SCC highlighting.
- Click any file for an AI-generated explanation of its role.
- Auto-generated setup instructions.

## Architecture

[diagram.png — the component map from the plan Section 2]

**Stack:** Vite + React + D3 (frontend, Vercel) · FastAPI + Tree-sitter + Gemini (backend, Render) · SSE streaming.

Full engineering plan: [docs/ENGINEERING.md](docs/ENGINEERING.md).

## Run locally
<instructions>

## Limitations
- Public repos only, ≤500 files.
- Some dynamic imports and Vite-aliased paths may be missed.
- AI explanations are best-effort; spot-check against actual code.

## License
MIT.
```

Assets:
- `screenshot.png` — a good-looking graph of a recognizable repo.
- `diagram.png` — architecture diagram (export from draw.io or excalidraw).
- `docs/ENGINEERING.md` — the original engineering plan.

---

## Demo video

2-minute screen recording:
1. Land on the page (0–10s).
2. Click a demo chip (10–25s) — show the graph appearing.
3. Hover and click nodes (25–55s) — show tooltips, selection.
4. Open AI explanation for a file (55–90s) — show streaming.
5. Submit a fresh GitHub URL (90–120s) — show progress, final graph, cycles panel.

Host on YouTube (unlisted) or Loom. Link in README.

---

## Pre-launch checklist

- [ ] All 13 phase verifications green (check logs from each phase).
- [ ] 12 security tests green (Phase 10).
- [ ] `/metrics` accessible and returns correct numbers.
- [ ] Cloudflare proxying, WAF rules active.
- [ ] GitHub Actions warmup cron running.
- [ ] 5 demo JSONs in place, chips working on landing page.
- [ ] README complete with screenshot, diagram, video link.
- [ ] `/security` page published.
- [ ] Load tests 1–4 passed, results in README.
- [ ] Env vars set on Render: `GEMINI_API_KEY`, `CLOUDFLARE_TRUSTED_IPS` (if used), `ENV=production`.
- [ ] Env vars set on Vercel: `VITE_API_URL`.
- [ ] Custom 404 / 500 pages on Vercel.
- [ ] `robots.txt` allowing indexing of landing page, blocking `/analyze`, `/stream/*`, `/explain/*`.
- [ ] Social share tags (`og:title`, `og:image`, `twitter:card`) on the landing page.

---

## Launch

1. Final merge to `main`. Auto-deploys trigger.
2. Smoke-test the production URL end-to-end once more.
3. Post to:
   - Personal portfolio.
   - LinkedIn / X / Mastodon / Bluesky — link to the live demo, not the repo.
   - Hacker News `Show HN` (if you want the hug of death).
4. Watch `/metrics` for the first hour. Be prepared to shed load or temporarily disable `/analyze` if things go sideways.

---

## Post-launch

Things you explicitly defer:
- Authentication and user accounts.
- Private repo support.
- More languages (C#, Ruby, PHP, Kotlin, Swift).
- Interactive filters ("hide test files," "hide generated").
- Search within the graph.
- Persistent history.
- Paid tier.

Each of these is a real feature and could be a whole project. Ship v1 first.

---

## Time budget

2 hours.

---

## Cumulative time across all 13 phases

- Phase 0: 2h
- Phase 1: 3h
- Phase 2: 3h
- Phase 3: 5h
- Phase 4: 2h
- Phase 5: 4.5h
- Phase 6: 4h
- Phase 7: 3h
- Phase 8: 5h
- Phase 9: 2h
- Phase 10: 4h
- Phase 11: 3h
- Phase 12: 2h

**Total: ~42.5 hours** of focused work. Ship it.
