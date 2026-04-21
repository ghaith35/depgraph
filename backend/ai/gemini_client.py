import logging
import os
from typing import AsyncIterator

logger = logging.getLogger(__name__)

_GEMINI_MODEL = "gemini-1.5-flash"


def _require_key() -> str:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")
    return key


async def stream_explanation(
    system_prompt: str,
    user_prompt: str,
) -> AsyncIterator[str]:
    from google import genai
    from google.genai import types

    api_key = _require_key()
    client = genai.Client(api_key=api_key)

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        max_output_tokens=1500,
        temperature=0.3,
    )

    async for chunk in client.aio.models.generate_content_stream(
        model=_GEMINI_MODEL,
        contents=user_prompt,
        config=config,
    ):
        try:
            text = chunk.text
            if text:
                yield text
        except Exception:
            continue
