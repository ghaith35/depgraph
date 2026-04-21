# DepGraph — Phase 5: SSE Streaming Pipeline

## Goal
Convert the synchronous `POST /analyze` into an async streaming pipeline. Client gets a `job_id` synchronously, then opens `GET /stream/{job_id}` which is a Server-Sent Events stream emitting nodes, edges, cycles, setup, stats, and progress as they are computed.

## Time budget
4.5 hours (includes the adaptive concurrency from Refinement 2 in the plan).

## Prerequisites
Phase 4 complete. Full `AnalysisResult` buildable synchronously.

---

## Why SSE, not WebSocket
- SSE is one-way (server → client), which is all we need. WebSocket's bidirectionality is wasted here.
- SSE works over plain HTTP/2, no upgrade handshake, no proxy issues on Render or Cloudflare.
- Browser `EventSource` API auto-reconnects on drop (we use this in Phase 11).
- We have zero need for client-to-server streaming.

---

## Protocol design

### Endpoints
- `POST /analyze` — accepts `{"url": "..."}`, validates URL, creates a job, returns `{"job_id": "uuid", "status": "queued" | "running"}` immediately (no work done yet).
- `GET /stream/{job_id}` — SSE stream. Client opens this right after getting the job_id.

### SSE event types
Each event is a standard SSE frame: `event: <type>\ndata: <json>\n\n`.

| Event | When emitted | Payload |
|-------|--------------|---------|
| `status` | Start, on queued/running transitions | `{"status": "queued"\|"cloning"\|"parsing"\|"done"\|"error", "message": "..."}` |
| `progress` | Once per stage boundary | `{"stage": "clone"\|"walk"\|"parse"\|"resolve"\|"cycles"\|"setup", "percent": 0-100}` |
| `node` | One per file as discovered | `Node` JSON |
| `edge` | One per resolved import | `Edge` JSON |
| `cycle` | Once per SCC found | `{"scc": [...], "simple_cycles": [...]}` |
| `setup` | Once, at end | `SetupSteps` JSON |
| `stats` | Once, at end | `RepoStats` JSON |
| `error` | On fatal error | `{"code": "...", "message": "..."}` (terminal) |
| `done` | On clean completion | `{"job_id": "..."}` (terminal) |

Heartbeat: `: keepalive\n\n` every 10 seconds during long stages. SSE comment frames (starting with `:`) keep the connection alive without being delivered as events to the client.

### Response headers
```
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no
Connection: keep-alive
```

`X-Accel-Buffering: no` defeats proxy buffering.

---

## Architecture: JobManager + async generator

### JobManager
```python
class JobManager:
    def __init__(self, max_concurrent: int):
        self.jobs: dict[str, Job] = {}
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.queue: asyncio.Queue[str] = asyncio.Queue()

    async def submit(self, url: str) -> str:
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, url=url, status="queued", event_queue=asyncio.Queue(maxsize=256))
        self.jobs[job_id] = job
        asyncio.create_task(self._run_job(job))
        return job_id

    async def _run_job(self, job: Job):
        async with self.semaphore:
            job.status = "running"
            try:
                await pipeline.run(job)
                await job.event_queue.put(Event("done", {"job_id": job.id}))
            except Exception as e:
                await job.event_queue.put(Event("error", {"code": type(e).__name__, "message": str(e)}))
            finally:
                # cleanup /tmp/jobs/{job_id}, mark job complete-but-retain-events-for-30s
                ...

    async def stream(self, job_id: str) -> AsyncIterator[Event]:
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        while True:
            try:
                event = await asyncio.wait_for(job.event_queue.get(), timeout=10)
                yield event
                if event.type in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                yield Event.keepalive()
```

### Global instance
One `JobManager` per process. Initial `max_concurrent` set by the adaptive sizing below.

---

## Adaptive concurrency sizing (startup)

At app startup, measure memory after loading all Tree-sitter grammars:

```python
import resource, os

def compute_concurrency_limits() -> tuple[int, int]:
    """Returns (max_workers_per_job, max_concurrent_jobs)."""
    # Force load all grammars
    from app.parsers import load_all_parsers
    load_all_parsers()

    rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # ru_maxrss is in KB on Linux, bytes on macOS — on Render it's Linux, so KB.
    baseline_mb = rss_kb / 1024

    budget_mb = 480  # Render free is 512MB; leave 32MB headroom
    per_worker_mb = 90  # conservative estimate per ProcessPoolExecutor worker

    available_mb = budget_mb - baseline_mb
    if available_mb < per_worker_mb:
        return 1, 1  # too tight, serial only

    total_workers = max(1, int(available_mb // per_worker_mb))
    max_concurrent_jobs = max(1, total_workers // 2)  # each job uses ~2 workers
    return 2, max_concurrent_jobs
```

Log these values at startup. Use `max_concurrent_jobs` for the `JobManager` semaphore.

### Runtime memory watchdog
A background task sampling RSS every 5 seconds:

```python
async def memory_watchdog(job_manager: JobManager):
    while True:
        await asyncio.sleep(5)
        rss_mb = get_rss_mb()
        if rss_mb > 480 * 0.95:
            # Critical: cancel the most recently started job
            job_manager.cancel_newest_running_job()
        elif rss_mb > 480 * 0.80:
            # Warning: refuse new submissions by closing the semaphore
            job_manager.freeze_intake = True
        else:
            job_manager.freeze_intake = False
```

If `freeze_intake` is true, `POST /analyze` returns `503 Retry-After: 30`.

---

## Pipeline refactor

Rewrite the pipeline from Phase 4 as an async generator that pushes events into the job's queue as work progresses:

```python
async def run_pipeline(job: Job):
    await emit(job, "status", {"status": "cloning", "message": "Cloning repository..."})
    repo_path, commit_sha = await clone_repo(job.url, job.id)

    await emit(job, "progress", {"stage": "walk", "percent": 10})
    files = walk_files(repo_path)

    await emit(job, "progress", {"stage": "parse", "percent": 20})
    # Parse in ProcessPoolExecutor, emit each node as it's parsed
    async for node, imports in parse_files_async(files):
        await emit(job, "node", node.model_dump())

    await emit(job, "progress", {"stage": "resolve", "percent": 70})
    # Resolve imports, emit each edge as resolved
    for edge in resolve_imports(all_imports, repo_context):
        await emit(job, "edge", edge.model_dump())

    await emit(job, "progress", {"stage": "cycles", "percent": 85})
    cycles = detect_cycles(graph)
    for scc in cycles.sccs:
        await emit(job, "cycle", {"scc": scc, "simple_cycles": get_paths(scc)})

    await emit(job, "progress", {"stage": "setup", "percent": 95})
    setup = generate_setup(repo_path)
    await emit(job, "setup", setup.model_dump())

    stats = build_stats(...)
    await emit(job, "stats", stats.model_dump())
```

### Bounded queue backpressure
The job's event queue has `maxsize=256`. If it fills (slow client):

```python
async def emit(job: Job, event_type: str, data: dict):
    event = Event(type=event_type, data=data)
    try:
        job.event_queue.put_nowait(event)
    except asyncio.QueueFull:
        if event_type == "progress":
            pass  # drop progress events first
        else:
            # for node/edge/cycle/etc., block with a short timeout
            try:
                await asyncio.wait_for(job.event_queue.put(event), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning(f"Event queue blocked for job {job.id}, terminating stream")
                job.cancel()
```

Never drop `node`, `edge`, `cycle`, `error`, or `done` events.

---

## FastAPI endpoint

```python
@app.post("/analyze")
async def analyze(req: AnalyzeRequest, job_manager: JobManager = Depends(get_jm)):
    if job_manager.freeze_intake:
        raise HTTPException(503, headers={"Retry-After": "30"})
    # URL validation per Phase 1
    validated = validate_url(req.url)
    job_id = await job_manager.submit(validated.url)
    return {"job_id": job_id, "status": job_manager.jobs[job_id].status}


@app.get("/stream/{job_id}")
async def stream(job_id: str, job_manager: JobManager = Depends(get_jm)):
    async def event_generator():
        try:
            async for event in job_manager.stream(job_id):
                yield event.to_sse_frame()
        except asyncio.CancelledError:
            # Client disconnected; JobManager cleans up on its own
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
```

The `Event.to_sse_frame()` method:
```python
def to_sse_frame(self) -> bytes:
    if self.is_keepalive:
        return b": keepalive\n\n"
    data_json = orjson.dumps(self.data).decode("utf-8")
    return f"event: {self.type}\ndata: {data_json}\n\n".encode("utf-8")
```

Use `orjson` (add to requirements) — 3-5× faster than stdlib `json` when emitting hundreds of small events.

---

## Frontend: EventSource integration

```typescript
const { data } = await fetch(`${API_URL}/analyze`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ url }),
}).then(r => r.json());

const es = new EventSource(`${API_URL}/stream/${data.job_id}`);

const state = {
  nodes: new Map(),
  edges: [],
  cycles: [],
  setup: null,
  stats: null,
  status: "starting",
};

es.addEventListener("status", e => {
  state.status = JSON.parse(e.data).status;
  render();
});
es.addEventListener("progress", e => {
  updateProgressBar(JSON.parse(e.data));
});
es.addEventListener("node", e => {
  const node = JSON.parse(e.data);
  state.nodes.set(node.id, node);
  appendToGraph(node);  // Phase 6 hooks in here
});
es.addEventListener("edge", e => {
  state.edges.push(JSON.parse(e.data));
  appendEdgeToGraph(JSON.parse(e.data));
});
es.addEventListener("cycle", e => { state.cycles.push(JSON.parse(e.data)); render(); });
es.addEventListener("setup", e => { state.setup = JSON.parse(e.data); render(); });
es.addEventListener("stats", e => { state.stats = JSON.parse(e.data); render(); });
es.addEventListener("error", e => {
  console.error(JSON.parse(e.data));
  es.close();
});
es.addEventListener("done", e => {
  es.close();
});
```

For Phase 5, render minimally — a counter of nodes/edges received, a status message. Phase 6 replaces this with D3.

---

## Verification tests

### Test A — basic stream
Submit a 50-file repo. Observe in Network tab:
- `POST /analyze` returns job_id immediately (<100ms).
- `GET /stream/{job_id}` opens and stays open.
- `node` events arrive incrementally over ~2 seconds, not all at once.
- `done` event arrives last, connection closes cleanly.

### Test B — concurrent jobs respect semaphore
Submit 3 analyses simultaneously (3 browser tabs). With `max_concurrent_jobs = 2`, assert:
- Jobs 1 and 2 start immediately (see `cloning` status).
- Job 3 stays in `queued` status until job 1 or 2 finishes.
- Status transitions are visible via `status` events on job 3's stream.

### Test C — client disconnect cleanup
Submit an analysis, wait for it to start cloning, then close the browser tab. Verify (via server logs):
- The stream's `asyncio.CancelledError` fires.
- The pipeline task is cancelled.
- `/tmp/jobs/{job_id}/` is deleted.
- The semaphore slot is released (verify by submitting a new job immediately — it should start without queueing).

### Test D — heartbeat during slow clone
Submit a repo that takes 12+ seconds to clone. Capture the raw SSE stream with `curl -N`. Assert: a `: keepalive` comment appears in the output during the clone phase.

### Test E — backpressure
Simulate a slow client by opening an EventSource with a Chrome breakpoint that halts JS execution. The server's event queue will fill. Assert:
- Server logs show `progress` events being dropped.
- No `node` or `edge` events are lost.
- Eventually (after 2s timeout), the server logs a backpressure warning and closes the stream.

### Test F — error mid-stream
Submit a valid URL but kill the `git` subprocess mid-clone (add a test hook for this, or use a very slow repo + low timeout). Assert:
- `error` event is emitted with a typed error code.
- Connection closes.
- No `done` event.
- Cleanup still runs.

### Test G — memory watchdog
Artificially inflate RSS (e.g., allocate a 200 MB buffer in a test endpoint). Assert:
- `freeze_intake` flips true above 80% threshold.
- New `POST /analyze` calls return `503`.
- After the allocation is freed, `freeze_intake` returns to false.

---

## Out of scope for this phase
- D3 rendering (Phase 6)
- Canvas performance optimization (Phase 7)
- AI integration (Phase 8)
- Caching (Phase 9)

---

## Common pitfalls
- Don't emit events synchronously from inside a `ProcessPoolExecutor` worker — workers are separate processes, they can't reach the main event loop's queue. Use a `multiprocessing.Queue` or `concurrent.futures.as_completed()` on the main side, then emit from there.
- Don't forget `X-Accel-Buffering: no` — without it, some proxies buffer the entire response.
- Don't use `asyncio.Queue()` without `maxsize` — unbounded queues leak memory on slow clients.
- Don't forget to cancel the pipeline task when the client disconnects — zombie tasks pile up.
- Heartbeats must be sent even if no other events are being emitted — schedule a separate task for them.
