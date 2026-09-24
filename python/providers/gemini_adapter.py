"""Gemini Adapter for HeyBloopie.

Uses the official modern google.genai SDK.
Default model: gemini-2.5-flash-lite
Reads API key from keyring service 'heybloopie', username 'gemini'.
"""

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional
from google import genai
import keyring

from python.provider import AIProvider, KEYRING_SERVICE

logger = logging.getLogger("heybloopie.provider.gemini")


class GeminiAdapter(AIProvider):
    """AIProvider adapter for Google Gemini models using the modern google.genai SDK."""

    def __init__(self, model_name: str = "gemini-2.5-flash-lite"):
        self.default_model = model_name

    def _get_api_key(self) -> Optional[str]:
        try:
            return keyring.get_password(KEYRING_SERVICE, "gemini")
        except Exception as e:
            logger.error(f"Failed to retrieve Gemini API key from keyring: {e}")
            return None

    async def is_available(self) -> bool:
        """Returns True if Gemini API key is configured."""
        key = self._get_api_key()
        return bool(key and str(key).strip())

    def get_model_info(self) -> dict:
        return {
            "provider": "gemini",
            "model": self.default_model,
            "cost": "free",
        }

    async def generate(self, prompt: str, options: Optional[dict] = None) -> str:
        """Generates a text response from Gemini using google.genai."""
        key = self._get_api_key()
        if not key:
            return "Error: Gemini API key is not configured in keyring."

        try:
            client = genai.Client(api_key=key)
            model_id = (options or {}).get("model") or self.default_model

            if hasattr(client, "aio") and hasattr(client.aio, "models"):
                response = await client.aio.models.generate_content(
                    model=model_id,
                    contents=prompt,
                )
            else:
                response = client.models.generate_content(
                    model=model_id,
                    contents=prompt,
                )

            return getattr(response, "text", "") or ""
        except Exception as e:
            logger.error(f"Gemini generate error: {e}")
            return f"Gemini error: {e}"

    async def stream(self, prompt: str, options: Optional[dict] = None) -> AsyncIterator[str]:
        """Streams text chunks from Gemini using google.genai as an async generator."""
        key = self._get_api_key()
        if not key:
            yield "Error: Gemini API key is not configured in keyring."
            return

        try:
            client = genai.Client(api_key=key)
            model_id = (options or {}).get("model") or self.default_model

            if hasattr(client, "aio") and hasattr(client.aio, "models"):
                stream_resp = await client.aio.models.generate_content_stream(
                    model=model_id,
                    contents=prompt,
                )
                async for chunk in stream_resp:
                    text = getattr(chunk, "text", "") or ""
                    if text:
                        yield text
            else:
                stream_resp = client.models.generate_content_stream(
                    model=model_id,
                    contents=prompt,
                )
                for chunk in stream_resp:
                    text = getattr(chunk, "text", "") or ""
                    if text:
                        yield text
        except Exception as e:
            logger.error(f"Gemini stream error: {e}")
            yield f"Gemini stream error: {e}"
