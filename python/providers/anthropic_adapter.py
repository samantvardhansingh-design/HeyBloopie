"""Anthropic Adapter for HeyBloopie.

Uses the anthropic SDK.
Default model: claude-3-5-haiku
Reads API key from keyring service 'heybloopie', username 'anthropic'.
"""

import asyncio
import logging
from typing import Any, AsyncIterator, Dict, Optional
import anthropic
from anthropic import AsyncAnthropic
import keyring

from python.provider import AIProvider, KEYRING_SERVICE

logger = logging.getLogger("heybloopie.provider.anthropic")


class AnthropicAdapter(AIProvider):
    """AIProvider adapter for Anthropic models."""

    def __init__(self, model_name: str = "claude-3-5-haiku"):
        self.default_model = model_name

    def _get_api_key(self) -> Optional[str]:
        try:
            return keyring.get_password(KEYRING_SERVICE, "anthropic")
        except Exception as e:
            logger.error(f"Failed to retrieve Anthropic API key from keyring: {e}")
            return None

    async def is_available(self) -> bool:
        """Returns True if Anthropic API key is configured."""
        key = self._get_api_key()
        return bool(key and str(key).strip())

    def get_model_info(self) -> dict:
        return {
            "provider": "anthropic",
            "model": self.default_model,
            "cost": "paid",
        }

    async def generate(self, prompt: str, options: Optional[dict] = None) -> str:
        """Generates a text response from Anthropic."""
        key = self._get_api_key()
        if not key:
            return "Error: Anthropic API key is not configured in keyring."

        try:
            client = AsyncAnthropic(api_key=key)
            model_id = (options or {}).get("model") or self.default_model
            max_tokens = (options or {}).get("max_tokens", 4096)

            response = await client.messages.create(
                model=model_id,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            result = ""
            for block in getattr(response, "content", []):
                text = getattr(block, "text", "")
                if text:
                    result += text
            return result
        except Exception as e:
            logger.error(f"Anthropic generate error: {e}")
            return f"Anthropic error: {e}"

    async def stream(self, prompt: str, options: Optional[dict] = None) -> AsyncIterator[str]:
        """Streams text chunks from Anthropic as an async generator."""
        key = self._get_api_key()
        if not key:
            yield "Error: Anthropic API key is not configured in keyring."
            return

        try:
            client = AsyncAnthropic(api_key=key)
            model_id = (options or {}).get("model") or self.default_model
            max_tokens = (options or {}).get("max_tokens", 4096)

            if hasattr(client.messages, "stream"):
                async with client.messages.stream(
                    model=model_id,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                ) as stream_resp:
                    if hasattr(stream_resp, "text_stream"):
                        async for text_chunk in stream_resp.text_stream:
                            if text_chunk:
                                yield text_chunk
                    else:
                        async for event in stream_resp:
                            if hasattr(event, "delta") and hasattr(event.delta, "text"):
                                yield event.delta.text
            else:
                stream_resp = await client.messages.create(
                    model=model_id,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                    stream=True,
                )
                async for chunk in stream_resp:
                    if hasattr(chunk, "delta") and hasattr(chunk.delta, "text"):
                        yield chunk.delta.text
        except Exception as e:
            logger.error(f"Anthropic stream error: {e}")
            yield f"Anthropic stream error: {e}"
