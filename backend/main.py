import asyncio
import atexit
import logging
import os
import re
import resource
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import httpx
import orjson
import pathspec
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from graph.builder import build_graph, parse_one_file, resolve_imports_batch
from graph.context import build_context
from graph.cycles import annotate_graph, build_digraph, detect_cycles
from graph.setup import generate_setup
from app.schemas import (
    AnalysisResult, CycleReport, Edge, Graph, Node, RepoStats, SetupSteps,
)
from pipeline.job import Job
from pipeline.manager import StreamJobManager, stream_jobs as _stream_jobs_singleton
from routers.explain import router as explain_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JOBS_ROOT = Path("/tmp/jobs")
MAX_REPO_SIZE_BYTES = 200 * 1024 * 1024   # 50 MB
MAX_FILE_COUNT = 5000
MAX_CLONE_TIMEOUT = 600                    # seconds
MAX_CONCURRENT_CLONES = 2
HEAD_CHECK_TIMEOUT = 3.0                  # seconds
MAX_TOTAL_TMP_BYTES = 200 * 1024 * 1024  # 200 MB across all jobs

EXCLUDED_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build",
    ".next", "target", "__pycache__", ".tox", ".venv",
    "venv", ".mypy_cache", ".pytest_cache", ".cache",
    "coverage", ".idea", ".vscode",
}

EXCLUDED_EXTENSIONS = {".min.js", ".min.css"}

EXTENSION_LANGUAGE_MAP = {
    ".py": "python",    ".js": "javascript", ".ts": "typescript",
    ".tsx": "typescript", ".jsx": "javascript", ".java": "java",
    ".go": "go",        ".rs": "rust",        ".cpp": "cpp",
    ".c": "c",          ".h": "c",            ".hpp": "cpp",
    ".cs": "csharp",    ".rb": "ruby",        ".php": "php",
    ".swift": "swift",  ".kt": "kotlin",      ".md": "markdown",
    ".yaml": "yaml",    ".yml": "yaml",       ".json": "json",
    ".toml": "toml",    ".sh": "shell",       ".bash": "shell",
    ".html": "html",    ".css": "css",        ".xml": "xml",
    ".sql": "sql",      ".r": "r",            ".scala": "scala",
    ".ex": "elixir",    ".exs": "elixir",     ".hs": "haskell",
    ".lua": "lua",      ".dart": "dart",      ".vue": "vue",
    ".svelte": "svelte",
}

# Strict allowlist regex — only github/gitlab/bitbucket HTTPS
_URL_RE = re.compile(
    r'^https://(github\.com|gitlab\.com|bitbucket\.org)'
    r'/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+'
    r'(/tree/[a-zA-Z0-9_.\-/]+)?/?$'
)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ValidatedRepo:
    host: str
    owner: str
    repo: str
    url: str        # canonical clone URL (no /tree/... suffix)
    branch: Optional[str] = None


@dataclass
class FileEntry:
    path: str
    size: int
    language_hint: str


# ---------------------------------------------------------------------------
# Stage 1 — URL validation
# ---------------------------------------------------------------------------

def validate_url(raw: str) -> ValidatedRepo:
    if raw.startswith("git@") or raw.startswith("ssh://"):
        raise HTTPException(400, "SSH URLs are not supported; use HTTPS.")
    if not raw.startswith("https://"):
        raise HTTPException(400, "Only https:// URLs are accepted.")
    host_part = raw[len("https://"):].split("/")[0]
    if "@" in host_part:
        raise HTTPException(400, "URLs with embedded credentials are not allowed.")
    for bad in ["..", "\x00", ";", "&", "|", "`", "$", "(", ")", "<", ">", "?"]:
        if bad in raw:
            raise HTTPException(400, f"URL contains disallowed character: {bad!r}")
    if "?" in raw or "#" in raw:
        raise HTTPException(400, "Query strings and fragments are not allowed.")
    if not _URL_RE.match(raw):
        raise HTTPException(
            400,
            "URL must be a public github.com, gitlab.com, or bitbucket.org HTTPS URL."
        )
    without_scheme = raw[len("https://"):]
    parts = without_scheme.strip("/").split("/")
    host = parts[0]
    owner = parts[1]
    repo_name = parts[2]
    branch = parts[4] if len(parts) >= 5 and parts[3] == "tree" else None
    clone_url = f"https://{host}/{owner}/{repo_name}"
    return ValidatedRepo(host=host, owner=owner, repo=repo_name, url=clone_url, branch=branch)


async def check_repo_accessible(vr: ValidatedRepo) -> None:
    canonical = f"https://{vr.host}/{vr.owner}/{vr.repo}"
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.head(canonical, timeout=HEAD_CHECK_TIMEOUT)
        if resp.status_code == 404:
            raise HTTPException(404, f"Repository not found or private: {canonical}")
        if resp.status_code == 403:
            raise HTTPException(404, "Repository is private or access denied.")
        if resp.status_code >= 500:
            raise HTTPException(503, "Git host returned a server error; try again later.")
    except HTTPException:
        raise
    except httpx.TimeoutException:
        raise HTTPException(503, "Git host did not respond in time; try again later.")
    except Exception as exc:
        raise HTTPException(503, f"Could not reach git host: {exc}")


# ---------------------------------------------------------------------------
# Stage 2 — Shallow clone (runs in thread)
# ---------------------------------------------------------------------------

_clone_semaphore: Optional[asyncio.Semaphore] = None


def _get_clone_semaphore() -> asyncio.Semaphore:
    global _clone_semaphore
    if _clone_semaphore is None:
        _clone_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CLONES)
    return _clone_semaphore


def _dir_size(path: Path) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for fname in filenames:
            try:
                total += (Path(dirpath) / fname).stat().st_size
            except OSError:
                pass
            if total > MAX_REPO_SIZE_BYTES:
                return total
    return total


def _sync_clone(clone_url: str, dest: Path, job_id: str) -> str:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_HOOKS_PATH"] = "/dev/null"
    env["HOME"] = "/tmp"
    env["GIT_ASKPASS"] = "echo"

    cmd = [
        "git", "clone",
        "--depth=1",
        "--single-branch",
        "--no-tags",
        "--filter=blob:limit=1m",
        clone_url,
        str(dest),
    ]
    logger.info("Cloning job_id=%s url=%s", job_id, clone_url)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=MAX_CLONE_TIMEOUT,
        env=env,
    )

    if result.returncode != 0:
        stderr = result.stderr.lower()
        if "not found" in stderr or "repository not found" in stderr:
            raise HTTPException(404, "Repository not found.")
        if "permission denied" in stderr or "authentication" in stderr:
            raise HTTPException(404, "Repository is private or access denied.")
        if "empty repository" in stderr:
            raise HTTPException(400, "Repository is empty.")
        raise HTTPException(502, f"Clone failed: {result.stderr[:300]}")

    total_bytes = _dir_size(dest)
    if total_bytes > MAX_REPO_SIZE_BYTES:
        raise HTTPException(
            413,
            f"Repository exceeds 50 MB limit ({total_bytes // (1024*1024)} MB)."
        )

    sha_result = subprocess.run(
        ["git", "--git-dir", str(dest / ".git"), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=5, env=env,
    )
    commit_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"
    logger.info("Cloned job_id=%s commit=%s size=%d", job_id, commit_sha, total_bytes)
    return commit_sha


async def shallow_clone(vr: ValidatedRepo, dest: Path, job_id: str) -> str:
    sem = _get_clone_semaphore()
    async with sem:
        try:
            return await asyncio.to_thread(_sync_clone, vr.url, dest, job_id)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Clone timed out after 60 seconds.")


# ---------------------------------------------------------------------------
# Stage 3 — File discovery (runs in thread)
# ---------------------------------------------------------------------------

def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\x00" in fh.read(8192)
    except OSError:
        return True


def _load_gitignore(repo_root: Path) -> Optional[pathspec.PathSpec]:
    gi = repo_root / ".gitignore"
    if not gi.is_file():
        return None
    try:
        lines = gi.read_text(errors="replace").splitlines()
        return pathspec.PathSpec.from_lines("gitwildmatch", lines)
    except Exception:
        return None


def discover_files(repo_root: Path) -> list[FileEntry]:
    resolved_root = repo_root.resolve()
    spec = _load_gitignore(repo_root)
    entries: list[FileEntry] = []
    count = 0

    for dirpath, dirnames, filenames in os.walk(repo_root, followlinks=False):
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDED_DIRS and not d.startswith(".")
        ]

        for fname in filenames:
            fpath = Path(dirpath) / fname
            try:
                resolved = fpath.resolve()
                if not resolved.is_relative_to(resolved_root):
                    logger.warning("Skipping path-traversal candidate: %s", fpath)
                    continue
            except (OSError, ValueError):
                continue

            suffix = fpath.suffix.lower()
            if suffix in EXCLUDED_EXTENSIONS:
                continue

            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if size > 1024 * 1024:
                continue

            if spec:
                try:
                    rel = str(fpath.relative_to(repo_root))
                    if spec.match_file(rel):
                        continue
                except ValueError:
                    pass

            if _is_binary(fpath):
                continue

            lang = EXTENSION_LANGUAGE_MAP.get(suffix, "other")
            rel_path = str(fpath.relative_to(repo_root))
            entries.append(FileEntry(path=rel_path, size=size, language_hint=lang))

            count += 1
            if count > MAX_FILE_COUNT:
                raise HTTPException(
                    413,
                    f"Repository exceeds {MAX_FILE_COUNT}-file limit."
                )

    return entries


# ---------------------------------------------------------------------------
# Filesystem job dir manager
# ---------------------------------------------------------------------------

class FsJobManager:
    def __init__(self) -> None:
        JOBS_ROOT.mkdir(parents=True, exist_ok=True)

    def create_job_dir(self, job_id: str) -> Path:
        d = JOBS_ROOT / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def cleanup(self, job_id: str) -> None:
        d = JOBS_ROOT / job_id
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            logger.info("Cleaned up job_id=%s", job_id)

    def cleanup_all(self) -> None:
        if JOBS_ROOT.exists():
            shutil.rmtree(JOBS_ROOT, ignore_errors=True)
            logger.info("Cleaned up all jobs in %s", JOBS_ROOT)


fs_jobs = FsJobManager()
atexit.register(fs_jobs.cleanup_all)

# In-memory SSE job registry — use the module-level singleton so routers share the same instance
stream_jobs = _stream_jobs_singleton

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="DepGraph API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(explain_router)


@app.on_event("startup")
async def on_startup() -> None:
    asyncio.create_task(_memory_watchdog())
    asyncio.create_task(_evict_expired_jobs())


@app.on_event("shutdown")
def on_shutdown() -> None:
    fs_jobs.cleanup_all()


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def _memory_watchdog() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            # Linux: KB; macOS: bytes
            rss_mb = rss_kb / 1024 if os.uname().sysname != "Darwin" else rss_kb / 1024 / 1024
            if rss_mb > 400:
                logger.warning("High RSS memory: %.0f MB", rss_mb)
        except Exception:
            pass


async def _evict_expired_jobs() -> None:
    while True:
        await asyncio.sleep(120)
        stream_jobs.evict_expired()


# ---------------------------------------------------------------------------
# SSE pipeline runner
# ---------------------------------------------------------------------------

def _sse_frame(event_type: str, data: Any) -> str:
    return f"event: {event_type}\ndata: {orjson.dumps(data).decode()}\n\n"


async def _run_pipeline(job: Job, url: str, job_dir: Path) -> None:
    """Full analysis pipeline. Puts SSE frames (str) or None (EOF) into job.queue."""
    repo_dest = job_dir / "repo"
    t_start = time.monotonic()
    job.status = "running"

    async def put(event_type: str, data: Any) -> None:
        frame = _sse_frame(event_type, data)
        try:
            await asyncio.wait_for(job.queue.put(frame), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Queue full for job %s, dropping %s", job.job_id, event_type)

    try:
        # Stage 1: validate
        await put("status", {"phase": "validating", "message": "Validating URL…"})
        vr = validate_url(url.strip())
        await check_repo_accessible(vr)

        # Stage 2: clone
        await put("status", {"phase": "cloning", "message": f"Cloning {vr.url}…"})
        commit_sha = await shallow_clone(vr, repo_dest, job.job_id)

        # Stage 3: discover files
        await put("status", {"phase": "discovering", "message": "Discovering files…"})
        files = await asyncio.to_thread(discover_files, repo_dest)
        total_files = len(files)
        all_file_paths = {f.path for f in files}
        await put("progress", {"done": 0, "total": total_files, "phase": "parsing"})

        # Stage 4: build language context
        ctx = await asyncio.to_thread(build_context, repo_dest, all_file_paths)

        # Stage 5: parse files → emit nodes
        await put("status", {"phase": "parsing", "message": f"Parsing {total_files} files…"})
        nodes_list: list[dict] = []
        file_imports: dict[str, tuple[list, bool]] = {}

        for i, entry in enumerate(files):
            node_dict, raw_imports, parse_error = await asyncio.to_thread(
                parse_one_file, entry, repo_dest
            )
            nodes_list.append(node_dict)
            file_imports[entry.path] = (raw_imports, parse_error)
            await put("node", node_dict)
            if (i + 1) % 25 == 0 or (i + 1) == total_files:
                await put("progress", {"done": i + 1, "total": total_files, "phase": "parsing"})

        # Stage 6: resolve imports → emit edges
        await put("status", {"phase": "resolving", "message": "Resolving imports…"})
        edges_list: list[dict] = await asyncio.to_thread(
            resolve_imports_batch, file_imports, ctx, all_file_paths
        )
        for edge_dict in edges_list:
            await put("edge", edge_dict)

        # Stage 7: cycle detection → annotate + emit cycles
        await put("status", {"phase": "cycles", "message": "Detecting cycles…"})
        G = build_digraph(nodes_list, edges_list)
        cycle_report, cycle_node_ids, cycle_edge_pairs = detect_cycles(G)
        annotate_graph(nodes_list, edges_list, cycle_node_ids, cycle_edge_pairs)

        for scc in cycle_report.sccs:
            await put("cycle", {"nodes": scc})

        # Stage 8: setup instructions
        await put("status", {"phase": "setup", "message": "Detecting project setup…"})
        setup = await asyncio.to_thread(generate_setup, repo_dest, all_file_paths)
        await put("setup", setup.model_dump())

        # Stage 9: stats
        total_size = sum(f.size for f in files)
        lang_counts: dict[str, int] = {}
        for f in files:
            lang_counts[f.language_hint] = lang_counts.get(f.language_hint, 0) + 1
        duration_ms = int((time.monotonic() - t_start) * 1000)

        stats_payload = {
            "file_count": len(files),
            "total_size_bytes": total_size,
            "total_loc": 0,
            "languages": lang_counts,
            "commit_sha": commit_sha,
            "repo_url": vr.url,
            "analysis_duration_ms": duration_ms,
        }
        await put("stats", stats_payload)

        await put("done", {"job_id": job.job_id})
        job.status = "done"

        # Store full AnalysisResult and repo path so /explain can access them
        job.analysis_result = AnalysisResult(
            job_id=job.job_id,
            stats=RepoStats(**stats_payload),
            graph=Graph(
                nodes=[Node(**nd) for nd in nodes_list],
                edges=[Edge(**ed) for ed in edges_list],
            ),
            cycles=cycle_report,
            setup=setup,
        )
        job.repo_dir = repo_dest

        logger.info(
            "Pipeline done job_id=%s files=%d nodes=%d edges=%d cycles=%d duration=%dms",
            job.job_id, len(files), len(nodes_list), len(edges_list),
            cycle_report.scc_count, duration_ms,
        )

    except HTTPException as exc:
        await put("error", {"message": exc.detail, "status_code": exc.status_code})
        job.status = "error"
    except Exception as exc:
        logger.exception("Pipeline error job_id=%s", job.job_id)
        await put("error", {"message": str(exc)})
        job.status = "error"
    finally:
        # Put EOF sentinel so the stream endpoint can exit cleanly
        try:
            await asyncio.wait_for(job.queue.put(None), timeout=5.0)
        except asyncio.TimeoutError:
            pass

        if job.status == "done":
            # Keep repo_dir alive for /explain; eviction handles FS + memory cleanup
            await asyncio.sleep(30)  # drain SSE stream
            # Intentionally not removing from stream_jobs here
        else:
            # Error path: clean up immediately
            fs_jobs.cleanup(job.job_id)
            await asyncio.sleep(30)
            stream_jobs.remove(job.job_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz():
    return {"ok": True}


class SubmitRequest(BaseModel):
    url: str


@app.post("/jobs")
def submit_job(body: SubmitRequest):
    job_id = str(uuid.uuid4())
    logger.info("New job submitted | job_id=%s url=%s", job_id, body.url)
    return {"job_id": job_id}


class AnalyzeRequest(BaseModel):
    url: str


@app.post("/analyze")
async def analyze(body: AnalyzeRequest):
    """Start an analysis job. Returns job_id. Stream results via GET /stream/{job_id}."""
    job_id = str(uuid.uuid4())
    job_dir = fs_jobs.create_job_dir(job_id)
    job = stream_jobs.create(job_id)
    asyncio.create_task(_run_pipeline(job, body.url, job_dir))
    return {"job_id": job_id, "status": "queued"}


@app.get("/stream/{job_id}")
async def stream(job_id: str):
    """SSE stream for a running analysis job."""
    job = stream_jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found or expired.")

    async def event_generator() -> AsyncIterator[str]:
        while True:
            try:
                frame = await asyncio.wait_for(job.queue.get(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            except Exception:
                break

            if frame is None:  # EOF sentinel
                break
            yield frame

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering on Render
        },
    )
