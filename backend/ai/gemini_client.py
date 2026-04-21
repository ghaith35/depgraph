import json
import logging
import os
from typing import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

_GEMINI_MODEL = "gemini-2.5-flash"
# Use v1beta for streamGenerateContent with gemini-2.5-flash on free tier
_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


def _require_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")
    return key


async def stream_explanation(
    system_prompt: str,
    user_prompt: str,
) -> AsyncIterator[str]:
    """
    Stream AI explanation from Gemini 1.5 Flash via Google Generative Language API.
    Uses v1beta endpoint which supports streamGenerateContent for this model.
    """
    api_key = _require_key()
    url = f"{_API_BASE}/{_GEMINI_MODEL}:streamGenerateContent?key={api_key}&alt=sse"

    combined = f"{system_prompt}\n\n{user_prompt}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": combined}]}],
        "generationConfig": {"maxOutputTokens": 1500, "temperature": 0.3},
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, json=payload) as response:
            if response.status_code != 200:
                body = await response.aread()
                error_msg = body.decode()[:500]
                logger.error(f"Gemini API error {response.status_code}: {error_msg}")
                raise RuntimeError(f"Gemini API error {response.status_code}: {error_msg}")

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if not data_str:
                    continue
                try:
                    chunk = json.loads(data_str)
                    text = chunk["candidates"][0]["content"]["parts"][0]["text"]
                    if text:
                        yield text
                except (KeyError, IndexError, json.JSONDecodeError) as e:
                    logger.debug(f"Skipped malformed SSE chunk: {e}")
                    continue
