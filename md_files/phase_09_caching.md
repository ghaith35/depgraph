# DepGraph — Phase 9: Caching Layer

## Goal

Three-tier cache for analysis results and AI explanations. Cache hits served in under 500ms. Metrics endpoint reporting hit rates. Graceful degradation when the ephemeral disk is wiped by a Render restart.

## Deliverable

- Analyzing the same repo twice — second call served from cache in <500ms.
- Clicking an already-explained file — served from cache instantly.
- `/metrics` endpoint reports hit rates per cache tier.
- Cache survives within a dyno lifetime; resets cleanly on dyno restart.

---

## Three cache tiers

### Tier 1 — In-process LRU (fastest, smallest)

An `OrderedDict`-backed LRU of the 30 most recent `AnalysisResult` objects in memory.

**Why:** hit rate dominates because the same user clicking around the UI re-fetches the same analysis multiple times. This layer responds in microseconds.

**Key:** `sha256(repo_url + "\0" + commit_sha)` — null-byte separator prevents collisions.

```python
from collections import OrderedDict

class InProcessLRU:
    def __init__(self, maxsize=30):
        self.cache: OrderedDict[str, AnalysisResult] = OrderedDict()
        self.maxsize = maxsize
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[AnalysisResult]:
        if key in self.cache:
            self.cache.move_to_end(key)
            self.hits += 1
            return self.cache[key]
        self.misses += 1
        return None

    def set(self, key: str, value: AnalysisResult):
        self.cache[key] = value
        self.cache.move_to_end(key)
        if len(self.cache) > self.maxsize:
            self.cache.popitem(last=False)
```

### Tier 2 — Disk cache (`/tmp/cache/`)

Two subdirectories:
- `/tmp/cache/analyses/{key}.json.gz` — full `AnalysisResult` serialized as gzipped JSON via `orjson.dumps()` + `gzip.compress()`. Typical size: 50–500 KB compressed for a 500-file repo.
- `/tmp/cache/explanations/{key}.txt` — per-file AI explanation, plain text. Typical size: 1–4 KB each.

**Analysis cache key:** `sha256(repo_url + "\0" + commit_sha)`.

**Explanation cache key:** `sha256(commit_sha + "\0" + file_path + "\0" + file_content_sha)`. Including `file_content_sha` means if a file changes across commits, we re-explain; identical content across commits reuses the cache.

**On write:** write to `{key}.json.gz.tmp`, then atomic rename to `{key}.json.gz`. Prevents half-written files being served on crash.

### Tier 3 — No tier 3

No Redis, no S3, no external store. The decision to stay off Redis is justified below.

---

## Read/write flow

```python
async def get_analysis(repo_url: str, commit_sha: str) -> Optional[AnalysisResult]:
    key = make_analysis_key(repo_url, commit_sha)

    # Tier 1
    if result := in_process_lru.get(key):
        record_hit("lru")
        return result

    # Tier 2
    disk_path = Path(f"/tmp/cache/analyses/{key}.json.gz")
    if disk_path.exists():
        try:
            data = gzip.decompress(disk_path.read_bytes())
            result = AnalysisResult.model_validate_json(data)
            # Verify the cached URL matches (defense against hash collision)
            if result.repo_stats.repo_url == repo_url:
                in_process_lru.set(key, result)  # populate LRU
                record_hit("disk")
                return result
        except Exception as e:
            log.warning("Cache corruption", path=disk_path, error=str(e))
            disk_path.unlink(missing_ok=True)

    record_miss()
    return None


async def set_analysis(result: AnalysisResult):
    key = make_analysis_key(result.repo_stats.repo_url, result.repo_stats.commit_sha)
    in_process_lru.set(key, result)
    await asyncio.to_thread(_write_analysis_to_disk, key, result)


def _write_analysis_to_disk(key: str, result: AnalysisResult):
    dest = Path(f"/tmp/cache/analyses/{key}.json.gz")
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    data = gzip.compress(result.model_dump_json().encode("utf-8"))
    tmp.write_bytes(data)
    tmp.rename(dest)
```

---

## Disk budget management — Janitor

`/tmp` is shared with clones and working files. Cap total cache usage at **300 MB**.

`JanitorTask` runs every 60 seconds in an asyncio background task:

```python
async def janitor_loop():
    while True:
        await asyncio.sleep(60)
        try:
            evict_until_under_budget()
        except Exception as e:
            log.exception("janitor", error=str(e))

def evict_until_under_budget():
    cache_root = Path("/tmp/cache")
    if not cache_root.exists():
        return
    files = [
        (f, f.stat().st_size, f.stat().st_atime)
        for f in cache_root.rglob("*") if f.is_file()
    ]
    total = sum(s for _, s, _ in files)
    if total <= 300 * 1024 * 1024:
        return
    # LRU eviction by access time
    files.sort(key=lambda x: x[2])  # oldest atime first
    for f, s, _ in files:
        f.unlink(missing_ok=True)
        total -= s
        log.info("cache_evict", path=str(f), size=s)
        if total <= 250 * 1024 * 1024:  # evict down to 250 to give headroom
            break
```

Active job working directories (`/tmp/jobs/`) are **not** cache and are exempt from Janitor. They're cleaned by JobManager on job completion.

---

## TTL

- Analyses: 7 days. Commits don't change; a stale analysis is still the correct analysis of that commit.
- Explanations: 30 days. Same logic — content hash in the key means they're effectively immutable.

TTL is enforced at read time (`if file.stat().st_mtime < now - TTL: delete and miss`) rather than via scheduled sweeps. Simpler, handles dyno restarts correctly.

---

## Behavior on dyno restart

After a Render dyno restart, `/tmp` is wiped. In-process LRU is gone. All caches cold. **This is fine:**

1. Flow degrades gracefully — a miss means we run the full pipeline, which is what we did the first time.
2. Average latency on miss is the 8–15s baseline; on hit, <500ms.
3. Log cache hit rate to `/metrics` so we can tell whether this is a practical problem.

Expected hit rate: 30–50% during normal usage, near 0% after restart, recovering over the next hour as popular repos get re-analyzed.

---

## Why no Redis

Redis is necessary only if:
- **Cross-dyno sharing needed** — NO, single dyno on free tier.
- **Cache size exceeds `/tmp`** — NO, 300 MB holds ~600 average analyses, enough for portfolio traffic.
- **Atomic counters across processes** — NO, single-worker uvicorn means in-process dict suffices for rate limiting.

None of those are true today. The first time any becomes true, add Upstash Redis free tier as a write-through layer behind the in-process LRU. Until then, Redis solves a problem we don't have at the cost of latency we can't afford on cold start.

---

## Cache poisoning concerns

Because cache keys include `commit_sha` and `file_content_sha`, an attacker cannot poison cache entries to affect future requests for the same key — they'd have to control the upstream Git repo at that commit, at which point the cache is faithfully reflecting reality.

Remaining concern: **cache-fill DoS**. Attacker analyzes 1000 throwaway repos to fill `/tmp` and evict legitimate entries. Mitigated by:
- Rate limiting (5/hour/IP) caps fill rate at 120 entries/day/IP.
- Janitor's LRU eviction means hot entries survive.

---

## `/metrics` endpoint

```python
@app.get("/metrics")
async def metrics():
    return {
        "cache": {
            "lru": {
                "size": len(in_process_lru.cache),
                "hits": in_process_lru.hits,
                "misses": in_process_lru.misses,
                "hit_rate": in_process_lru.hits / max(1, in_process_lru.hits + in_process_lru.misses),
            },
            "disk": {
                "analyses_count": count_files("/tmp/cache/analyses"),
                "explanations_count": count_files("/tmp/cache/explanations"),
                "total_bytes": sum_sizes("/tmp/cache"),
                "hits": disk_cache_hits,
            },
            "evictions_total": evictions_total,
        },
        "jobs": {
            "active": len(job_manager.active),
            "queued": job_manager.queue.qsize(),
        },
        "memory": {
            "rss_mb": get_rss_mb(),
            "baseline_rss_mb": baseline_rss_mb,
        },
    }
```

No auth on `/metrics` in v1 — content is non-sensitive operational data. Lock down later if needed.

---

## Verification (must pass ALL of these)

1. Analyze `fastapi/fastapi` → first call, ~8-15s. Second call from a new browser tab → <500ms. `/metrics` shows `lru.hits=1`.

2. Restart the Render service (manual redeploy). Analyze same repo → cache miss, full pipeline runs. `/metrics` shows fresh counters.

3. Click a file in an analyzed repo → Gemini call. Click the same file again → served from disk cache instantly. `/metrics` shows the explanation cache hit.

4. Force cache fill: mock the disk cache to exceed 300 MB. Wait 60s. Verify Janitor evicted down to 250 MB. Log lines for each eviction visible.

5. Corrupt a cache file (truncate it). Try to read. Server logs "Cache corruption", deletes file, falls through to miss. No crash.

6. Simulate dyno restart mid-analysis (kill the uvicorn process). Restart. Verify `/tmp/cache/` starts empty, `/tmp/jobs/` is empty (no orphan dirs from the killed analysis — this tests Phase 1's atexit cleanup).

---

## Constraints

- `orjson` for serialization (already a dep).
- `gzip` is stdlib, no new dep.
- No sync I/O in the request path. Disk reads/writes via `asyncio.to_thread`.
- Cache reads MUST re-validate the URL/commit inside the payload, not trust the key alone.
- Do not cache partial/incomplete AnalysisResults. Only cache after the pipeline emits `done`.

## Time budget

2 hours.
