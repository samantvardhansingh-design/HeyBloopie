"""OpenAI Adapter for HeyBloopie.

Uses the openai SDK.
Default model: gpt-4o-mini
Reads API key from keyring service 'heybloopie', username 'openai'.
"""

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional
import keyring
from openai import AsyncOpenAI

from python.provider import AIProvider, KEYRING_SERVICE

logger = logging.getLogger("heybloopie.provider.openai")


class OpenAIAdapter(AIProvider):
    """AIProvider adapter for OpenAI."""

    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.default_model = model_name

    def _get_api_key(self) -> Optional[str]:
        try:
            return keyring.get_password(KEYRING_SERVICE, "openai")
        except Exception as e:
            logger.error(f"Failed to retrieve OpenAI API key from keyring: {e}")
            return None

    async def is_available(self) -> bool:
        """Returns True if OpenAI API key is configured."""
        key = self._get_api_key()
        return bool(key and str(key).strip())

    def get_model_info(self) -> dict:
        return {
            "provider": "openai",
            "model": self.default_model,
            "cost": "paid",
        }

    async def generate(self, prompt: str, options: Optional[dict] = None) -> str:
        """Generates a text response from OpenAI."""
        key = self._get_api_key()
        if not key:
            return "Error: OpenAI API key is not configured in keyring."

        try:
            client = AsyncOpenAI(api_key=key, max_retries=0, timeout=3.0)
            model_id = (options or {}).get("model") or self.default_model
            max_tokens = (options or {}).get("max_tokens")

            create_kwargs = {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
            }
            if max_tokens:
                create_kwargs["max_tokens"] = max_tokens

            response = await client.chat.completions.create(**create_kwargs)
            if response.choices and response.choices[0].message:
                return response.choices[0].message.content or ""
            return ""
        except Exception as e:
            logger.error(f"OpenAI generate error: {e}")
            return f"OpenAI error: {e}"

    async def stream(self, prompt: str, options: Optional[dict] = None) -> AsyncIterator[str]:
        """Streams text chunks from OpenAI as an async generator."""
        key = self._get_api_key()
        if not key:
            yield "Error: OpenAI API key is not configured in keyring."
            return

        try:
            client = AsyncOpenAI(api_key=key, max_retries=0, timeout=3.0)
            model_id = (options or {}).get("model") or self.default_model
            max_tokens = (options or {}).get("max_tokens")

            stream_kwargs = {
                "model": model_id,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True,
            }
            if max_tokens:
                stream_kwargs["max_tokens"] = max_tokens

            stream_resp = await client.chat.completions.create(**stream_kwargs)
            async for chunk in stream_resp:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            logger.error(f"OpenAI stream error: {e}")
            yield f"OpenAI stream error: {e}"
