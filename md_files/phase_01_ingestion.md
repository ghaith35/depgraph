# DepGraph — Phase 1: Repo Ingestion + File Discovery

## Goal

`POST /analyze` now actually does work: validates the URL, clones the repo to `/tmp`, walks the file tree honoring exclusions and size caps, returns a JSON summary synchronously. No parsing, no graph, no SSE yet.

## Deliverable

```
POST /analyze { "url": "https://github.com/tiangolo/fastapi" }

→ 200
{
  "job_id": "<uuid>",
  "commit_sha": "abc123...",
  "file_count": 187,
  "total_size_bytes": 1245678,
  "languages": {"python": 165, "markdown": 12, "yaml": 10}
}
```

Plus the error cases enumerated in the verification section below.

---

## Pipeline stages to implement

### Stage 1 — Repo validation

- **Input:** `str` URL from `POST /analyze`.
- **Output:** `ValidatedRepo { host, owner, repo, branch_or_none }` or 4xx.
- **Logic:** Regex against an allowlist of `github.com`, `gitlab.com`, `bitbucket.org` only. Reject anything with credentials in URL (`user:pass@`), reject SSH-style (`git@`), reject query strings, reject paths with `..`. Do a HEAD request to the repo's public web URL with a 3-second timeout to confirm it exists and is public before we incur a clone. This HEAD check costs ~200ms but saves 5 seconds of failed clone time.
- **Latency:** <500ms.
- **Failures:** Invalid URL → 400 with explicit error. Private/404 → 404. Timeout → 503 with retry hint.

### Stage 2 — Shallow clone

- **Input:** `ValidatedRepo`.
- **Output:** Path to `/tmp/jobs/{job_id}/repo/` plus `commit_sha` from `git rev-parse HEAD`.
- **Logic:** `subprocess.run(["git", "clone", "--depth=1", "--single-branch", "--no-tags", "--filter=blob:limit=1m", url, dest], timeout=30)`. The `--filter=blob:limit=1m` is critical — it prevents pulling huge binary blobs (model weights, video assets) that would blow past our 50 MB budget before we even know the repo's size. Capture stderr; on non-zero exit, parse for "not found" / "permission denied" / "repository is empty" and surface a typed error.
- **Latency cold instance:** 3–8 seconds for typical OSS repos. **Latency warm:** 1–4 seconds.
- **Failures:** Timeout (30s hard limit) → kill and 504. Disk full (cap `/tmp` usage at 200 MB across all jobs via the JobManager) → evict LRU jobs. Clone returns >50 MB → abort and 413.

### Stage 3 — File discovery

- **Input:** Repo path.
- **Output:** `list[FileEntry { path, size, language_hint }]`.
- **Logic:** Single `os.walk` honoring an exclusion list: `.git`, `node_modules`, `vendor`, `dist`, `build`, `.next`, `target`, `__pycache__`, `*.min.js`, anything `> 1 MB`, anything in `.gitignore` (parsed cheaply via `pathspec`), anything detected as binary via the `\0`-in-first-8KB heuristic. Stop and return error if file count exceeds 500.
- **Latency:** ~100ms for 500 files on warm fs.
- **Failures:** Symlink loops → `os.walk(followlinks=False)`. Permission errors → skip and log.

---

## Security mitigations required in this phase

These are critical — implement as you build the pipeline, not after.

### Git URL injection / SSRF via clone target

URL validation pipeline rejects everything that doesn't match `https://(github\.com|gitlab\.com|bitbucket\.org)/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+(/tree/[a-zA-Z0-9_.\-/]+)?/?$`. No exceptions. Schemes other than `https` rejected. Hosts other than the allowlist rejected. Username/password (`https://user:pass@...`) rejected. Path components containing `..`, `\0`, or shell metacharacters rejected. Validated URL is passed to `subprocess.run` as a list element (never `shell=True`), preventing shell injection.

### Malicious repo content — Git hooks execution

Set `GIT_TERMINAL_PROMPT=0` and `GIT_HOOKS_PATH=/dev/null` in the subprocess environment. Use `--no-tags` and explicitly do not run any subsequent git commands inside the cloned directory — once cloned, treat it as a pile of files. Never `cd` into the repo; always use absolute paths.

### Path traversal via repo contents

Every file path is validated post-walk: `Path(file).resolve().is_relative_to(repo_root.resolve())`. Files failing this check are skipped and logged. Path strings used in cache keys are hashed, never used raw. Never construct file paths by string concatenation — always `Path / segment`.

### Disk exhaustion via huge clone

`--filter=blob:limit=1m` skips fetching blobs larger than 1 MB. Hard 30-second timeout on the clone subprocess. After clone, total directory size measured with `du`-equivalent walk; if > 50 MB, abort and clean up. Concurrent clones limited to 2 (semaphore) so disk pressure is bounded.

### Zip-bomb-equivalent via repo file count

File count cap of 500 enforced *during* the walk — count as you go and abort the walk past the limit, returning a typed error before parsing begins. Single walk pass, no recursive globs.

---

## Cleanup

Implement a `JobManager` class:
- `start_job(url) -> job_id` — creates `/tmp/jobs/{job_id}/`, runs pipeline, stores result.
- `cleanup(job_id)` — removes the directory. Called on success AND failure.
- Registered `atexit` handler and FastAPI `shutdown` event that nuke `/tmp/jobs/` entirely.

`/tmp/jobs/` should never contain orphaned clones. If it does, you have a cleanup bug.

---

## Verification (must pass ALL of these)

1. Submit `https://github.com/tiangolo/fastapi` → get back accurate counts, `file_count` > 100, cleanup verified (the dir is gone after response).
2. Submit `https://github.com/torvalds/linux` → 413 (too many files / too large).
3. Submit `https://github.com/nonexistent-user-xyz/fake-repo` → 404.
4. Submit `file:///etc/passwd` → 400.
5. Submit `https://github.com/foo/bar; rm -rf /` → 400 (rejected by regex).
6. Submit `https://user:pass@github.com/foo/bar` → 400.
7. Submit `git@github.com:foo/bar.git` → 400.
8. Submit `https://github.com/foo/bar/../../etc` → 400.
9. Check `/tmp/jobs/` after each request — empty.

---

## Constraints

- No Tree-sitter yet. No AST. No graph. No SSE.
- Response is synchronous JSON for Phase 1 only (will become async SSE in Phase 5).
- Use `asyncio.to_thread` or `run_in_executor` for the `subprocess.run` clone — do not block the event loop.
- Do not introduce Docker at this stage; Render's Python native runtime is fine.

## Time budget

3 hours.
