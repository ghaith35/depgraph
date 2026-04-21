import asyncio
import atexit
import logging
import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx
import pathspec
from fastapi import FastAPI, HTTPException
from graph.builder import build_graph
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JOBS_ROOT = Path("/tmp/jobs")
MAX_REPO_SIZE_BYTES = 50 * 1024 * 1024   # 50 MB
MAX_FILE_COUNT = 5000
MAX_CLONE_TIMEOUT = 30                    # seconds
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
    # Reject SSH-style
    if raw.startswith("git@") or raw.startswith("ssh://"):
        raise HTTPException(400, "SSH URLs are not supported; use HTTPS.")

    # Reject non-https
    if not raw.startswith("https://"):
        raise HTTPException(400, "Only https:// URLs are accepted.")

    # Reject embedded credentials (user:pass@host)
    host_part = raw[len("https://"):].split("/")[0]
    if "@" in host_part:
        raise HTTPException(400, "URLs with embedded credentials are not allowed.")

    # Reject dangerous characters before regex (belt + suspenders)
    for bad in ["..", "\x00", ";", "&", "|", "`", "$", "(", ")", "<", ">", "?"]:
        if bad in raw:
            raise HTTPException(400, f"URL contains disallowed character: {bad!r}")

    # Reject query strings / fragments
    if "?" in raw or "#" in raw:
        raise HTTPException(400, "Query strings and fragments are not allowed.")

    # Allowlist regex
    if not _URL_RE.match(raw):
        raise HTTPException(
            400,
            "URL must be a public github.com, gitlab.com, or bitbucket.org HTTPS URL."
        )

    # Parse
    without_scheme = raw[len("https://"):]
    parts = without_scheme.strip("/").split("/")
    host = parts[0]
    owner = parts[1]
    repo_name = parts[2]
    branch = parts[4] if len(parts) >= 5 and parts[3] == "tree" else None

    # Canonical clone URL (strip /tree/... suffix)
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


def _get_semaphore() -> asyncio.Semaphore:
    global _clone_semaphore
    if _clone_semaphore is None:
        _clone_semaphore = asyncio.Semaphore(MAX_CONCURRENT_CLONES)
    return _clone_semaphore


def _dir_size(path: Path) -> int:
    """Fast recursive size sum with early-exit."""
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
    """Blocking clone. Returns commit_sha. Raises HTTPException on failure."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_HOOKS_PATH"] = "/dev/null"
    env["HOME"] = "/tmp"            # prevent ~/.gitconfig credential helpers
    env["GIT_ASKPASS"] = "echo"     # extra guard against interactive prompts

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
        # Never shell=True — list form prevents injection
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

    # Size check — must happen before we do anything with files
    total_bytes = _dir_size(dest)
    if total_bytes > MAX_REPO_SIZE_BYTES:
        raise HTTPException(
            413,
            f"Repository exceeds 50 MB limit ({total_bytes // (1024*1024)} MB)."
        )

    # Commit SHA — use --git-dir, never cd into repo
    sha_result = subprocess.run(
        ["git", "--git-dir", str(dest / ".git"), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=5, env=env,
    )
    commit_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"
    logger.info("Cloned job_id=%s commit=%s size=%d", job_id, commit_sha, total_bytes)
    return commit_sha


async def shallow_clone(vr: ValidatedRepo, dest: Path, job_id: str) -> str:
    sem = _get_semaphore()
    async with sem:
        try:
            return await asyncio.to_thread(_sync_clone, vr.url, dest, job_id)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Clone timed out after 30 seconds.")


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
        # Prune excluded dirs in-place (modifying dirnames controls descent)
        dirnames[:] = [
            d for d in dirnames
            if d not in EXCLUDED_DIRS and not d.startswith(".")
        ]

        for fname in filenames:
            fpath = Path(dirpath) / fname

            # Path traversal guard — every file resolved against repo root
            try:
                resolved = fpath.resolve()
                if not resolved.is_relative_to(resolved_root):
                    logger.warning("Skipping path-traversal candidate: %s", fpath)
                    continue
            except (OSError, ValueError):
                continue

            # Excluded extensions
            suffix = fpath.suffix.lower()
            if suffix in EXCLUDED_EXTENSIONS:
                continue

            # Per-file size cap (1 MB)
            try:
                size = fpath.stat().st_size
            except OSError:
                continue
            if size > 1024 * 1024:
                continue

            # gitignore
            if spec:
                try:
                    rel = str(fpath.relative_to(repo_root))
                    if spec.match_file(rel):
                        continue
                except ValueError:
                    pass

            # Binary heuristic
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
# JobManager
# ---------------------------------------------------------------------------

class JobManager:
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


job_manager = JobManager()
atexit.register(job_manager.cleanup_all)

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


@app.on_event("shutdown")
def on_shutdown() -> None:
    job_manager.cleanup_all()


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
    job_id = str(uuid.uuid4())
    job_dir = job_manager.create_job_dir(job_id)
    repo_dest = job_dir / "repo"

    try:
        # Stage 1 — validate URL
        vr = validate_url(body.url.strip())
        await check_repo_accessible(vr)

        # Stage 2 — clone
        commit_sha = await shallow_clone(vr, repo_dest, job_id)

        # Stage 3 — discover files
        files = await asyncio.to_thread(discover_files, repo_dest)

        # Stage 4 — parse + build graph
        graph = await asyncio.to_thread(build_graph, repo_dest, files)

        total_size = sum(f.size for f in files)
        logger.info(
            "Analysis complete job_id=%s files=%d nodes=%d edges=%d commit=%s",
            job_id, len(files), len(graph["nodes"]), len(graph["edges"]), commit_sha,
        )
        return {
            "job_id": job_id,
            "commit_sha": commit_sha,
            "file_count": len(files),
            "total_size_bytes": total_size,
            "nodes": graph["nodes"],
            "edges": graph["edges"],
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unexpected error job_id=%s", job_id)
        raise HTTPException(500, f"Internal error: {exc}")
    finally:
        # Always clean up — success or failure
        job_manager.cleanup(job_id)
