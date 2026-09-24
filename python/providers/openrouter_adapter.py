"""OpenRouter Adapter for HeyBloopie.

Uses the openai SDK pointed at https://openrouter.ai/api/v1.
Default model: meta-llama/llama-3.3-70b-instruct:free
Reads API key from keyring service 'heybloopie', username 'openrouter'.
"""

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional
import keyring
from openai import AsyncOpenAI

from python.provider import AIProvider, KEYRING_SERVICE

logger = logging.getLogger("heybloopie.provider.openrouter")


class OpenRouterAdapter(AIProvider):
    """AIProvider adapter for OpenRouter."""

    def __init__(self, model_name: str = "meta-llama/llama-3.3-70b-instruct:free"):
        self.default_model = model_name
        self.base_url = "https://openrouter.ai/api/v1"

    def _get_api_key(self) -> Optional[str]:
        try:
            return keyring.get_password(KEYRING_SERVICE, "openrouter")
        except Exception as e:
            logger.error(f"Failed to retrieve OpenRouter API key from keyring: {e}")
            return None

    async def is_available(self) -> bool:
        """Returns True if OpenRouter API key is configured."""
        key = self._get_api_key()
        return bool(key and str(key).strip())

    def get_model_info(self) -> dict:
        return {
            "provider": "openrouter",
            "model": self.default_model,
            "base_url": self.base_url,
            "cost": "free",
        }

    async def generate(self, prompt: str, options: Optional[dict] = None) -> str:
        """Generates a text response from OpenRouter."""
        key = self._get_api_key()
        if not key:
            return "Error: OpenRouter API key is not configured in keyring."

        try:
            client = AsyncOpenAI(api_key=key, base_url=self.base_url)
            model_id = (options or {}).get("model") or self.default_model

            response = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
            )
            if response.choices and response.choices[0].message:
                return response.choices[0].message.content or ""
            return ""
        except Exception as e:
            logger.error(f"OpenRouter generate error: {e}")
            return f"OpenRouter error: {e}"

    async def stream(self, prompt: str, options: Optional[dict] = None) -> AsyncIterator[str]:
        """Streams text chunks from OpenRouter as an async generator."""
        key = self._get_api_key()
        if not key:
            yield "Error: OpenRouter API key is not configured in keyring."
            return

        try:
            client = AsyncOpenAI(api_key=key, base_url=self.base_url)
            model_id = (options or {}).get("model") or self.default_model

            stream_resp = await client.chat.completions.create(
                model=model_id,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            async for chunk in stream_resp:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"OpenRouter stream error: {e}")
            yield f"OpenRouter stream error: {e}"
