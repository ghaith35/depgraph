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
    """Yield text tokens from Gemini using async streaming."""
    import google.generativeai as genai

    api_key = _require_key()
    genai.configure(api_key=api_key)

    model = genai.GenerativeModel(
        _GEMINI_MODEL,
        system_instruction=system_prompt,
    )
    generation_config = genai.GenerationConfig(
        max_output_tokens=1500,
        temperature=0.3,
    )

    response = await model.generate_content_async(
        [{"role": "user", "parts": [{"text": user_prompt}]}],
        generation_config=generation_config,
        stream=True,
    )

    async for chunk in response:
        try:
            text = chunk.text
            if text:
                yield text
        except Exception:
            # chunk.text raises if the chunk has no text (e.g. safety blocks)
            continue
