"""Ollama Adapter for HeyBloopie.

Uses httpx to call the local Ollama server at http://localhost:11434.
No API key required.
Lists models via GET /api/tags.
Default model: the first available model, or llama3.2 if available.
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional
import httpx

from python.provider import AIProvider

logger = logging.getLogger("heybloopie.provider.ollama")


class OllamaAdapter(AIProvider):
    """AIProvider adapter for local Ollama instances."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url.rstrip("/")
        self.default_model = "llama3.2"

    async def list_models(self) -> List[str]:
        """Queries GET /api/tags to list installed models."""
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                if res.status_code == 200:
                    data = res.json()
                    models = data.get("models", [])
                    return [m.get("name") for m in models if m.get("name")]
        except Exception as e:
            logger.debug(f"Failed to list Ollama models: {e}")
        return []

    async def get_effective_default_model(self) -> str:
        """Returns 'llama3.2' if available, otherwise the first installed model, or 'llama3.2'."""
        models = await self.list_models()
        if not models:
            return self.default_model

        for m in models:
            if m == "llama3.2" or m.startswith("llama3.2:"):
                return m

        return models[0]

    async def is_available(self) -> bool:
        """Checks if local Ollama server is reachable."""
        try:
            async with httpx.AsyncClient(timeout=1.5) as client:
                res = await client.get(f"{self.base_url}/api/tags")
                return res.status_code == 200
        except Exception:
            return False

    def get_model_info(self) -> dict:
        return {
            "provider": "ollama",
            "model": self.default_model,
            "base_url": self.base_url,
            "cost": "free",
        }

    async def generate(self, prompt: str, options: Optional[dict] = None) -> str:
        """Generates a text response from Ollama via /api/generate."""
        try:
            model = (options or {}).get("model") or await self.get_effective_default_model()
            async with httpx.AsyncClient(timeout=60.0) as client:
                res = await client.post(
                    f"{self.base_url}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": False},
                )
                res.raise_for_status()
                data = res.json()
                return data.get("response", "")
        except Exception as e:
            logger.error(f"Ollama generate error: {e}")
            return f"Ollama error: {e}"

    async def stream(self, prompt: str, options: Optional[dict] = None) -> AsyncIterator[str]:
        """Streams text chunks from Ollama via /api/generate stream=True."""
        try:
            model = (options or {}).get("model") or await self.get_effective_default_model()
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/generate",
                    json={"model": model, "prompt": prompt, "stream": True},
                ) as stream_resp:
                    stream_resp.raise_for_status()
                    async for line in stream_resp.aiter_lines():
                        if line and line.strip():
                            try:
                                chunk = json.loads(line)
                                text = chunk.get("response", "")
                                if text:
                                    yield text
                            except Exception:
                                pass
        except Exception as e:
            logger.error(f"Ollama stream error: {e}")
            yield f"Ollama stream error: {e}"
