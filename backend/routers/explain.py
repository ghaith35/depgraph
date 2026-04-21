import asyncio
import hashlib
import logging
import urllib.parse
from pathlib import Path
from typing import AsyncIterator

import orjson
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from ai.classifier import is_injection
from ai.gemini_client import stream_explanation
from ai.prompt_builder import build_prompt, estimate_tokens
from ai.scrubber import scrub
from pipeline.manager import stream_jobs

logger = logging.getLogger(__name__)
router = APIRouter()

CACHE_DIR = Path("/tmp/cache/explanations")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {orjson.dumps(data).decode()}\n\n"


def _cache_key(commit_sha: str, file_path: str, raw_content: str) -> str:
    content_sha = hashlib.sha256(raw_content.encode()).hexdigest()[:16]
    raw = f"{commit_sha}:{file_path}:{content_sha}"
    return hashlib.sha256(raw.encode()).hexdigest()


@router.get("/explain/{job_id}/{file_path:path}")
async def explain(job_id: str, file_path: str):
    file_path = urllib.parse.unquote(file_path)

    job = stream_jobs.get(job_id)
    if job is None or job.analysis_result is None:
        raise HTTPException(404, "Job not found or analysis not complete.")
    if job.repo_dir is None or not job.repo_dir.exists():
        raise HTTPException(410, "Repository files are no longer available.")

    result = job.analysis_result

    if not any(n.id == file_path for n in result.graph.nodes):
        raise HTTPException(404, f"File not in graph: {file_path}")

    async def generate() -> AsyncIterator[str]:
        # SSE comment wakes Render proxy before any real work
        yield ": waking up\n\n"
        yield _sse("status", {"message": "Preparing explanation..."})

        # Read raw file content
        abs_path = job.repo_dir / file_path
        try:
            raw_content = abs_path.read_text(errors="replace")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", file_path, exc)
            yield _sse("error", {
                "code": "FILE_UNAVAILABLE",
                "message": "Could not read file contents.",
            })
            return

        # Secret scrubbing — must happen before any content leaves this server
        scrub_result = scrub(raw_content)
        if scrub_result.count > 0:
            yield _sse("ai.redacted", {"count": scrub_result.count})

        # Cache lookup (keyed on commit SHA + file path + content hash)
        key = _cache_key(result.stats.commit_sha, file_path, raw_content)
        cache_file = CACHE_DIR / f"{key}.txt"
        if cache_file.exists():
            try:
                cached = cache_file.read_text()
                logger.info("Cache hit for %s", file_path)
                for i in range(0, len(cached), 80):
                    yield _sse("ai.token", {"text": cached[i:i + 80]})
                yield _sse("ai.done", {})
                return
            except OSError:
                pass  # fall through to fresh generation

        # Build prompt from scrubbed content
        try:
            system_prompt, user_prompt = build_prompt(
                result, file_path, scrub_result.text
            )
            total_tokens = estimate_tokens(system_prompt + user_prompt)
            if total_tokens > 6000:
                logger.warning(
                    "Large prompt for %s: ~%d tokens", file_path, total_tokens
                )
        except Exception as exc:
            logger.exception("Prompt build failed for %s", file_path)
            yield _sse("error", {"code": "PROMPT_ERROR", "message": str(exc)})
            return

        # Stream from Gemini, accumulating full text for classifier
        full_parts: list[str] = []

        try:
            async for token in stream_explanation(system_prompt, user_prompt):
                full_parts.append(token)
                yield _sse("ai.token", {"text": token})
                # Yield control so keepalive comments can interleave if needed
                await asyncio.sleep(0)

        except RuntimeError as exc:
            logger.error("Gemini runtime error for %s: %s", file_path, exc)
            yield _sse("error", {
                "code": "AI_UNAVAILABLE",
                "message": (
                    "AI explanation is temporarily unavailable. "
                    "The dependency graph is unaffected."
                ),
            })
            return

        except Exception as exc:
            err_str = str(exc)
            logger.exception("Gemini stream error for %s: %s", file_path, err_str)
            if full_parts:
                yield _sse("ai.truncated", {
                    "message": "Explanation cut off. Click to retry.",
                })
            else:
                code = "RATE_LIMITED" if "429" in err_str else "AI_UNAVAILABLE"
                yield _sse("error", {
                    "code": code,
                    "message": (
                        "AI explanation is temporarily unavailable. "
                        "The dependency graph is unaffected."
                    ),
                })
            return

        complete_text = "".join(full_parts)
        if not complete_text:
            yield _sse("ai.done", {})
            return

        # Classifier — runs after full stream, ~500ms overhead
        try:
            flagged = await asyncio.wait_for(
                is_injection(file_path, complete_text), timeout=10.0
            )
        except asyncio.TimeoutError:
            flagged = False
            logger.warning("Classifier timed out for %s", file_path)

        if flagged:
            yield _sse("ai.replaced", {
                "message": "Could not generate explanation for this file.",
            })
            return

        # Cache successful, clean response
        try:
            cache_file.write_text(complete_text)
        except OSError:
            pass

        yield _sse("ai.done", {})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
