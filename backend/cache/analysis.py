"""
Two-tier analysis cache:
  Tier 1 — InProcessLRU  (30 entries, microsecond access)
  Tier 2 — Disk gzip     (/tmp/cache/analyses/, 7-day TTL)
"""
import asyncio
import gzip
import hashlib
import logging
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from app.schemas import AnalysisResult

logger = logging.getLogger(__name__)

ANALYSIS_CACHE_DIR = Path("/tmp/cache/analyses")
EXPLANATION_CACHE_DIR = Path("/tmp/cache/explanations")
ANALYSIS_TTL = 7 * 24 * 3600   # 7 days
EXPLANATION_TTL = 30 * 24 * 3600  # 30 days
CACHE_BUDGET = 300 * 1024 * 1024  # 300 MB hard cap
EVICT_TARGET = 250 * 1024 * 1024  # evict down to 250 MB

# ---------------------------------------------------------------------------
# Metrics counters (module-level, reset on restart)
# ---------------------------------------------------------------------------
lru_hits = 0
lru_misses = 0
disk_hits = 0
disk_misses = 0
evictions_total = 0


# ---------------------------------------------------------------------------
# Tier 1 — In-process LRU
# ---------------------------------------------------------------------------
class InProcessLRU:
    def __init__(self, maxsize: int = 30) -> None:
        self._cache: OrderedDict[str, AnalysisResult] = OrderedDict()
        self.maxsize = maxsize

    def get(self, key: str) -> Optional[AnalysisResult]:
        global lru_hits, lru_misses
        if key in self._cache:
            self._cache.move_to_end(key)
            lru_hits += 1
            return self._cache[key]
        lru_misses += 1
        return None

    def set(self, key: str, value: AnalysisResult) -> None:
        self._cache[key] = value
        self._cache.move_to_end(key)
        if len(self._cache) > self.maxsize:
            self._cache.popitem(last=False)

    def size(self) -> int:
        return len(self._cache)


in_process_lru: InProcessLRU = InProcessLRU(maxsize=30)

# Maps canonical repo URL → last known commit SHA (for pre-clone cache lookup)
_url_commit_index: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Cache key helpers
# ---------------------------------------------------------------------------
def make_analysis_key(repo_url: str, commit_sha: str) -> str:
    return hashlib.sha256(f"{repo_url}\0{commit_sha}".encode()).hexdigest()


def make_explanation_key(commit_sha: str, file_path: str, content: str) -> str:
    content_sha = hashlib.sha256(content.encode()).hexdigest()[:16]
    return hashlib.sha256(f"{commit_sha}\0{file_path}\0{content_sha}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Tier 2 — Disk helpers
# ---------------------------------------------------------------------------
def _disk_read_analysis(key: str) -> Optional[AnalysisResult]:
    path = ANALYSIS_CACHE_DIR / f"{key}.json.gz"
    if not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime > ANALYSIS_TTL:
            path.unlink(missing_ok=True)
            logger.info("cache_expired key=%s", key[:8])
            return None
        data = gzip.decompress(path.read_bytes())
        return AnalysisResult.model_validate_json(data)
    except Exception as exc:
        logger.warning("cache_corrupt key=%s err=%s", key[:8], exc)
        path.unlink(missing_ok=True)
        return None


def _disk_write_analysis(key: str, result: AnalysisResult) -> None:
    ANALYSIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dest = ANALYSIS_CACHE_DIR / f"{key}.json.gz"
    tmp = dest.with_suffix(".gz.tmp")
    try:
        compressed = gzip.compress(result.model_dump_json().encode())
        tmp.write_bytes(compressed)
        tmp.rename(dest)
        logger.info("cache_write key=%s bytes=%d", key[:8], len(compressed))
    except Exception as exc:
        logger.warning("cache_write_fail key=%s err=%s", key[:8], exc)
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------
def get_cached_commit(repo_url: str) -> Optional[str]:
    """Return last known commit SHA for a URL (pre-clone cache lookup)."""
    return _url_commit_index.get(repo_url)


async def get_analysis(repo_url: str, commit_sha: str) -> Optional[AnalysisResult]:
    global disk_hits, disk_misses
    key = make_analysis_key(repo_url, commit_sha)

    result = in_process_lru.get(key)
    if result is not None:
        logger.info("cache_hit tier=lru repo=%s", repo_url)
        return result

    result = await asyncio.to_thread(_disk_read_analysis, key)
    if result is not None:
        if result.stats.repo_url == repo_url:
            in_process_lru.set(key, result)
            disk_hits += 1
            logger.info("cache_hit tier=disk repo=%s", repo_url)
            return result
        (ANALYSIS_CACHE_DIR / f"{key}.json.gz").unlink(missing_ok=True)

    disk_misses += 1
    return None


async def set_analysis(result: AnalysisResult) -> None:
    key = make_analysis_key(result.stats.repo_url, result.stats.commit_sha)
    _url_commit_index[result.stats.repo_url] = result.stats.commit_sha
    in_process_lru.set(key, result)
    await asyncio.to_thread(_disk_write_analysis, key, result)


def get_explanation(commit_sha: str, file_path: str, content: str) -> Optional[str]:
    key = make_explanation_key(commit_sha, file_path, content)
    path = EXPLANATION_CACHE_DIR / f"{key}.txt"
    if not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime > EXPLANATION_TTL:
            path.unlink(missing_ok=True)
            return None
        return path.read_text()
    except Exception:
        path.unlink(missing_ok=True)
        return None


def set_explanation(commit_sha: str, file_path: str, content: str, text: str) -> None:
    key = make_explanation_key(commit_sha, file_path, content)
    EXPLANATION_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = EXPLANATION_CACHE_DIR / f"{key}.txt"
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(text)
        tmp.rename(path)
    except Exception as exc:
        logger.warning("expl_cache_write_fail key=%s err=%s", key[:8], exc)
        tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Janitor — evict oldest files when over budget
# ---------------------------------------------------------------------------
def evict_until_under_budget() -> None:
    global evictions_total
    cache_root = Path("/tmp/cache")
    if not cache_root.exists():
        return
    files = []
    for f in cache_root.rglob("*"):
        if f.is_file():
            try:
                st = f.stat()
                files.append((f, st.st_size, st.st_atime))
            except OSError:
                pass
    total = sum(s for _, s, _ in files)
    if total <= CACHE_BUDGET:
        return
    files.sort(key=lambda x: x[2])
    for f, sz, _ in files:
        try:
            f.unlink(missing_ok=True)
            total -= sz
            evictions_total += 1
            logger.info("cache_evict path=%s size=%d", f.name, sz)
        except OSError:
            pass
        if total <= EVICT_TARGET:
            break


def count_files(path_str: str) -> int:
    p = Path(path_str)
    return sum(1 for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def sum_sizes(path_str: str) -> int:
    p = Path(path_str)
    if not p.exists():
        return 0
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total
