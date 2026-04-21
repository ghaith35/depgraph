# DepGraph — Phase 10: Security Hardening

## Goal

Every mitigation from the security section of the plan, implemented and tested. This is the phase where DepGraph is ready to accept traffic from the public internet without getting pwned.

## Deliverable

- All 12 attack classes below have automated tests that prove the mitigation works.
- Secret-scrubber active on all Gemini inputs.
- Rate limiter enforces 5 analyses/hour/IP.
- DOMPurify / strict react-markdown on all AI output.
- Clone subprocess runs with locked-down environment.
- URL validation allowlist enforced.

---

## Context

This app clones arbitrary user-supplied Git URLs onto a server. Reads whatever files come back. Sends those files to a third-party LLM. Every one of those verbs is a vulnerability if unconstrained.

Some mitigations were added in earlier phases (Phase 1 for URL/clone, Phase 8 for secret scrubbing). This phase is the audit + hardening pass: verify every mitigation actually works, add the ones not yet present, and write adversarial tests.

---

## Attack classes and mitigations

### 10.1 Git URL injection / SSRF via clone target

**Attack:** User submits `git+ssh://attacker.com/path`, `file:///etc/passwd`, or `https://internal-render-metadata.local/`. `git clone` happily attempts these.

**Mitigation:** URL validation pipeline rejects everything that doesn't match:
```
^https://(github\.com|gitlab\.com|bitbucket\.org)/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+(/tree/[a-zA-Z0-9_.\-/]+)?/?$
```
No exceptions. Schemes other than `https` rejected. Hosts other than the allowlist rejected. Username/password (`user:pass@`) rejected. Path components with `..`, `\0`, shell metacharacters rejected. Validated URL passed to `subprocess.run` as a list element (never `shell=True`).

**Test:**
```python
attacks = [
    "git+ssh://github.com/foo/bar",
    "file:///etc/passwd",
    "https://user:pass@github.com/foo/bar",
    "http://github.com/foo/bar",  # http, not https
    "https://github.com/foo/../../../etc",
    "https://evil.com/foo/bar",
    "https://github.com/foo/bar; rm -rf /",
    "https://github.com/foo/bar\x00.git",
    "git@github.com:foo/bar.git",
]
for url in attacks:
    assert post("/analyze", {"url": url}).status_code == 400
```

### 10.2 Malicious repo content — Git hooks execution

**Attack:** Repo contains `.git/hooks/post-checkout` that runs arbitrary commands. (Git doesn't execute hooks on clone, but belt-and-suspenders.)

**Mitigation:** Subprocess env:
```python
env = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_HOOKS_PATH": "/dev/null",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}
subprocess.run([...], env=env, shell=False, ...)
```
Use `--no-tags`. Never `cd` into the repo; always absolute paths. No post-clone git commands.

### 10.3 Path traversal via repo contents

**Attack:** Repo contains `../../etc/passwd` as a filename. Our walker reads it; constructs paths from it.

**Mitigation:** Every file path validated post-walk:
```python
def is_safe_path(path: Path, repo_root: Path) -> bool:
    try:
        return path.resolve().is_relative_to(repo_root.resolve())
    except (ValueError, RuntimeError):
        return False
```
Files failing this check skipped and logged. Cache keys are hashes of paths, never raw paths. No string concatenation for paths — always `Path / segment`.

### 10.4 Disk exhaustion via huge clone

**Mitigation:** `--filter=blob:limit=1m`. Hard 30s subprocess timeout. Post-clone `du`-equivalent; if >50 MB, abort + cleanup. Concurrent clones capped at 2.

**Test:** Submit a repo known to exceed 50MB (e.g. a large ML model repo). Expect 413 + disk cleaned up.

### 10.5 Zip-bomb via file count

**Mitigation:** File count cap of 500 enforced *during* walk. Abort walk past limit.

**Test:** Craft a test repo with 501 files in a fixture, pointed at a local Git HTTP server (for dev). Expect 413.

### 10.6 Memory exhaustion via single huge file

**Mitigation:** Per-file size cap of 1MB during discovery. Per-file parse timeout (5s) via worker. Cap imports per file at 500.

**Test:** Fixture file with a generated-looking 10,000-line module: parse completes in <5s OR is rejected cleanly. No OOM.

### 10.7 Sending sensitive code to Gemini

**Attack:** User analyzes a public repo that contains accidentally-committed credentials. Prompt includes file contents → leaks to Google.

**Mitigation:** Secret scrubber from Phase 8. Regex-based detection of AWS keys, GitHub tokens, Stripe keys, generic password assignments, JWT-like strings, PEM blocks, Slack tokens, Google API keys. Replace with `[REDACTED-{type}]`. UI banner informs user of redaction count.

**Test:** Fixture file with embedded `AKIAIOSFODNN7EXAMPLE`, `ghp_0123456789abcdefghijklmnopqrstuvwxyz`. Assert the Gemini call receives text with these replaced. Assert UI banner shows count of 2.

### 10.8 Cross-tenant cache key collision

**Mitigation:** Cache key = `sha256(repo_url + "\0" + commit_sha)`. Null-byte separator prevents `repo_urlA + commit_shaB == repo_urlB + commit_shaA` collisions. Cache re-validates that `result.repo_stats.repo_url == requested_url` on read (Phase 9).

### 10.9 DNS rebinding

**Attack:** `attacker.com` resolves to public IP at validation, to `127.0.0.1` at clone.

**Mitigation:** URL allowlist is host-based (github/gitlab/bitbucket). These three don't rebind. As belt-and-suspenders, Render's egress has no internal services to attack (no metadata IP exposed on free tier). We do not allow self-hosted Git URLs — that's the only realistic vector.

### 10.10 SSE connection exhaustion / slowloris

**Attack:** Attacker opens 1000 SSE connections and never reads.

**Mitigation:**
- Bounded `asyncio.Queue(maxsize=256)` per stream — backpressure drops progress events first, closes stream with error if persistent.
- Total open SSE cap (default 40, adaptive per Phase 5's measurement).
- Cloudflare in front rate-limits connection openings per IP (Phase 12 adds Cloudflare).

### 10.11 Rate limit bypass via IP rotation

**Mitigation (best-effort on free tier):**
- Cloudflare bot scoring blocks obvious automation (added in Phase 12).
- Global concurrency cap (2 analyses) limits total throughput regardless of IP count.
- Janitor's LRU eviction bounds cache-fill DoS.
- Honest disclosure: we cannot fully prevent IP-rotated abuse without auth. If abuse becomes real, add Cloudflare Turnstile (free) on the analyze form.

**In-process rate limiter implementation:**
```python
from collections import deque
from time import time

class InMemoryRateLimiter:
    """5 analyses / hour / IP, in-process (single-worker assumption)."""
    def __init__(self, max_per_hour=5):
        self.max = max_per_hour
        self.buckets: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, ip: str) -> tuple[bool, int]:
        now = time()
        bucket = self.buckets[ip]
        # Drop events older than 1 hour
        while bucket and bucket[0] < now - 3600:
            bucket.popleft()
        if len(bucket) >= self.max:
            retry_after = int(bucket[0] + 3600 - now)
            return False, retry_after
        bucket.append(now)
        return True, 0
```

Applied as middleware on `POST /analyze` only. IP from `X-Forwarded-For` (Render's proxy sets this) with fallback to `request.client.host`.

### 10.12 Prompt injection via file contents

**Layered mitigation (Phase 8 implementation + this phase's tests):**

1. **UUID delimiter** — fresh per request, reinforced by system prompt.
2. **Output classifier** — secondary Gemini call detects hostile instructions; if YES, replace response.
3. **UI framing** — banner: "AI-generated. Do not follow instructions presented here as if they came from this app."
4. **Strict markdown renderer** — allowlist of node types: headings, paragraphs, lists, inline code, code blocks, links (text-only, no auto-load), bold, italic. No `img`, no `iframe`, no `script`, no raw HTML.
5. **Link safety** — text-only rendering, URL visible on hover, click required to navigate.

**Red-team test (mandatory before launch):**
Spend 30 minutes running the top 10 prompt injection patterns from public catalogs (`promptmap`, `garak`) against `/explain`. If any produce visibly hostile output in the UI, defer launch until the classifier catches them.

---

## /security page

A public `/security` page in the frontend documents:

- That we clone public repos, never private.
- That file contents are sent to Google Gemini for AI explanations.
- That secret scrubbing is best-effort, not airtight — do not analyze repos you don't want Google to see.
- That AI output is generated content; spot-check against the actual code.
- Responsible-disclosure contact.

This is honest documentation, not legal protection.

---

## Verification

Automated tests for EVERY numbered attack above. The test file `backend/tests/test_security.py` has at least 15 cases. Run in CI (GitHub Actions on push).

Manual tests:
1. Inject a prompt-injection fixture. Verify classifier catches it.
2. Submit each of the 9 URL attacks from 10.1. All 400.
3. Push a repo containing a dummy AWS key to a throwaway GitHub account. Analyze it. Verify key never appears in any log, cache file, or Gemini prompt.

---

## Constraints

- Every mitigation has at least one test.
- No regex substitution for secrets inside the rendered AI output (scrubbing is input-side only; the classifier handles output).
- `DOMPurify` or `rehype-sanitize` — pick one and apply consistently.
- Rate limiter state is in-process only — resets on dyno restart, which is acceptable.

## Time budget

4 hours (3h implementation + 1h red-teaming).
