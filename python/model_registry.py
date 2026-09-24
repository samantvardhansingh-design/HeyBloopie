"""HeyBloopie Model Registry.

This module maintains the catalog of foundation models, their vendor specifications,
token limits, pricing, and free/paid status. Models are persisted in SQLite and cached
for 7 days before refreshing.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
from typing import Any, Dict, List, Optional
import httpx
import keyring

try:
    from python.memory import Memory, get_iso_timestamp, get_memory
except (ImportError, ModuleNotFoundError):
    from memory import Memory, get_iso_timestamp, get_memory

logger = logging.getLogger("heybloopie.model_registry")

# Static fallbacks / catalog metadata for popular models
GEMINI_DEFAULTS = {
    "gemini-2.5-flash-lite": {"context": 1048576, "input_price": 0.075, "output_price": 0.30, "is_free": 1},
    "gemini-2.5-flash": {"context": 1048576, "input_price": 0.15, "output_price": 0.60, "is_free": 1},
    "gemini-2.0-flash": {"context": 1048576, "input_price": 0.10, "output_price": 0.40, "is_free": 1},
    "gemini-1.5-flash": {"context": 1048576, "input_price": 0.075, "output_price": 0.30, "is_free": 1},
    "gemini-1.5-pro": {"context": 2097152, "input_price": 1.25, "output_price": 5.00, "is_free": 1},
}

OPENAI_DEFAULTS = {
    "gpt-4o-mini": {"context": 128000, "input_price": 0.15, "output_price": 0.60, "is_free": 0},
    "gpt-4o": {"context": 128000, "input_price": 2.50, "output_price": 10.00, "is_free": 0},
    "o1-mini": {"context": 128000, "input_price": 1.10, "output_price": 4.40, "is_free": 0},
    "o3-mini": {"context": 200000, "input_price": 1.10, "output_price": 4.40, "is_free": 0},
}

ANTHROPIC_DEFAULTS = {
    "claude-3-5-haiku-20241022": {"name": "Claude 3.5 Haiku", "context": 200000, "input_price": 0.80, "output_price": 4.00, "is_free": 0},
    "claude-3-5-sonnet-20241022": {"name": "Claude 3.5 Sonnet", "context": 200000, "input_price": 3.00, "output_price": 15.00, "is_free": 0},
    "claude-3-opus-20240229": {"name": "Claude 3 Opus", "context": 200000, "input_price": 15.00, "output_price": 75.00, "is_free": 0},
}


def is_cache_expired(last_updated_iso: Optional[str], days: int = 7) -> bool:
    """Determines whether a cached timestamp is older than the expiration threshold."""
    if not last_updated_iso:
        return True
    try:
        updated_dt = datetime.fromisoformat(last_updated_iso)
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - updated_dt) >= timedelta(days=days)
    except Exception:
        return True


@dataclass
class ModelDescriptor:
    """Metadata describing a specific model entry in the registry."""
    model_id: str
    provider_name: str
    display_name: str
    context_window: int
    supports_structured_output: bool
    supports_streaming: bool
    is_local: bool


class ModelRegistry:
    """Manages model cataloging, dynamic provider listing, and SQLite caching."""

    def __init__(self, memory: Optional[Memory] = None):
        """Initializes the ModelRegistry with a reference to the Memory layer."""
        self.memory = memory if memory is not None else get_memory()

    async def refresh_models(self, provider_name: str, force: bool = False) -> None:
        """Refreshes the available model catalog for a specific provider.

        Only calls the provider API if force is True, if no cached models exist,
        or if the cache is older than 7 days. If the API call fails, logs the error
        gracefully and leaves existing cached models untouched.

        Args:
            provider_name: 'gemini', 'openrouter', 'openai', 'anthropic', or 'ollama'.
            force: If True, bypasses the 7-day cache freshness check.
        """
        provider = provider_name.lower().strip()

        # Check existing cache
        if not force:
            last_updated = self.memory.get_models_last_updated(provider)
            existing_models = self.memory.get_models(provider)
            if existing_models and not is_cache_expired(last_updated, days=7):
                logger.debug(f"Models for {provider} are still fresh (last updated: {last_updated}).")
                return

        # Fetch models from the target provider
        try:
            fetched_models = await self._fetch_provider_models(provider)
            if fetched_models:
                self.memory.save_models(fetched_models)
                logger.info(f"Successfully refreshed {len(fetched_models)} models for {provider}.")
        except Exception as err:
            logger.warning(
                f"Failed to refresh models for provider '{provider}': {err}. Keeping existing cache."
            )

    def get_models(self, provider_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns cached models for a provider (or all providers if None/empty) from SQLite without making API calls.

        Args:
            provider_name: Provider identifier (e.g. 'gemini', 'openrouter', 'ollama'), or None for all.

        Returns:
            List of model dictionaries matching the SQLite models schema.
        """
        norm_name = provider_name.lower().strip() if provider_name else None
        return self.memory.get_models(norm_name)

    def get_model_info(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves detailed information for a specific model by ID from SQLite.

        Args:
            model_id: Model identifier (e.g. 'gemini-2.5-flash-lite', 'llama3.2:latest').

        Returns:
            Dictionary of model information, or None if not found.
        """
        return self.memory.get_model(model_id)

    async def _fetch_provider_models(self, provider: str) -> List[Dict[str, Any]]:
        """Dispatches provider-specific catalog fetching logic."""
        if provider == "openrouter":
            return await self._fetch_openrouter_models()
        elif provider == "ollama":
            return await self._fetch_ollama_models()
        elif provider == "gemini":
            return await self._fetch_gemini_models()
        elif provider == "openai":
            return await self._fetch_openai_models()
        elif provider == "anthropic":
            return await self._fetch_anthropic_models()
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    async def _fetch_openrouter_models(self) -> List[Dict[str, Any]]:
        """Fetches models from OpenRouter public API.

        Models with pricing.prompt == '0' are marked FREE (is_free = 1).
        """
        url = "https://openrouter.ai/api/v1/models"
        api_key = keyring.get_password("heybloopie", "openrouter")
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json().get("data", [])

        now_iso = get_iso_timestamp()
        results: List[Dict[str, Any]] = []

        for item in data:
            model_id = item.get("id")
            if not model_id:
                continue
            name = item.get("name") or model_id
            context_length = int(item.get("context_length") or 0)
            pricing = item.get("pricing") or {}

            prompt_val = str(pricing.get("prompt", "0"))
            completion_val = str(pricing.get("completion", "0"))

            try:
                prompt_f = float(prompt_val)
            except (ValueError, TypeError):
                prompt_f = 0.0

            try:
                comp_f = float(completion_val)
            except (ValueError, TypeError):
                comp_f = 0.0

            # OpenRouter free models have prompt == "0"
            is_free = 1 if (prompt_val.strip() == "0" or (prompt_f == 0.0 and comp_f == 0.0)) else 0

            # Prices per 1M tokens
            input_price = prompt_f * 1_000_000.0
            output_price = comp_f * 1_000_000.0

            results.append({
                "id": model_id,
                "name": name,
                "provider": "openrouter",
                "is_free": is_free,
                "context_length": context_length,
                "input_price": input_price,
                "output_price": output_price,
                "last_updated": now_iso,
            })

        return results

    async def _fetch_ollama_models(self) -> List[Dict[str, Any]]:
        """Fetches models from local Ollama instance (http://localhost:11434/api/tags).

        All local Ollama models are marked FREE (is_free = 1).
        """
        url = "http://localhost:11434/api/tags"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json().get("models", [])

        now_iso = get_iso_timestamp()
        results: List[Dict[str, Any]] = []

        for item in data:
            model_id = item.get("name") or item.get("model")
            if not model_id:
                continue
            name = item.get("name") or model_id
            results.append({
                "id": model_id,
                "name": name,
                "provider": "ollama",
                "is_free": 1,
                "context_length": 128000,
                "input_price": 0.0,
                "output_price": 0.0,
                "last_updated": now_iso,
            })

        return results

    async def _fetch_gemini_models(self) -> List[Dict[str, Any]]:
        """Fetches models using Google GenAI SDK (client.aio.models.list)."""
        api_key = keyring.get_password("heybloopie", "gemini")
        if not api_key:
            raise ValueError("No Gemini API key stored in keyring.")

        from google import genai

        client = genai.Client(api_key=api_key)
        now_iso = get_iso_timestamp()
        results: List[Dict[str, Any]] = []

        pager = await client.aio.models.list()
        async for m in pager:
            raw_id = getattr(m, "name", "")
            if not raw_id:
                continue
            model_id = raw_id.split("/")[-1] if "/" in raw_id else raw_id
            supported_actions = getattr(m, "supported_actions", None) or []

            # Only include models capable of generateContent if supported_actions is specified
            if supported_actions and "generateContent" not in supported_actions:
                continue
            if "embedding" in model_id.lower() or "aqa" in model_id.lower():
                continue

            name = getattr(m, "display_name", None) or model_id
            context_length = int(getattr(m, "input_token_limit", 0) or 1048576)

            # Check pricing defaults
            matched_default = None
            for key, val in GEMINI_DEFAULTS.items():
                if key in model_id:
                    matched_default = val
                    break

            is_free = matched_default["is_free"] if matched_default else 1
            input_price = matched_default["input_price"] if matched_default else 0.075
            output_price = matched_default["output_price"] if matched_default else 0.30

            results.append({
                "id": model_id,
                "name": name,
                "provider": "gemini",
                "is_free": is_free,
                "context_length": context_length,
                "input_price": input_price,
                "output_price": output_price,
                "last_updated": now_iso,
            })

        return results

    async def _fetch_openai_models(self) -> List[Dict[str, Any]]:
        """Fetches models using OpenAI SDK."""
        api_key = keyring.get_password("heybloopie", "openai")
        if not api_key:
            raise ValueError("No OpenAI API key stored in keyring.")

        import openai

        client = openai.AsyncOpenAI(api_key=api_key)
        resp = await client.models.list()
        now_iso = get_iso_timestamp()
        results: List[Dict[str, Any]] = []

        for m in resp.data:
            model_id = m.id
            # Filter chat models
            if not (model_id.startswith("gpt-") or model_id.startswith("o1") or model_id.startswith("o3")):
                continue
            if "realtime" in model_id or "audio" in model_id:
                continue

            matched = None
            for k, v in OPENAI_DEFAULTS.items():
                if k in model_id:
                    matched = v
                    break

            context_length = matched["context"] if matched else 128000
            input_price = matched["input_price"] if matched else 2.50
            output_price = matched["output_price"] if matched else 10.00

            results.append({
                "id": model_id,
                "name": model_id,
                "provider": "openai",
                "is_free": 0,
                "context_length": context_length,
                "input_price": input_price,
                "output_price": output_price,
                "last_updated": now_iso,
            })

        return results

    async def _fetch_anthropic_models(self) -> List[Dict[str, Any]]:
        """Fetches models using Anthropic SDK."""
        api_key = keyring.get_password("heybloopie", "anthropic")
        if not api_key:
            raise ValueError("No Anthropic API key stored in keyring.")

        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        resp = await client.models.list()
        now_iso = get_iso_timestamp()
        results: List[Dict[str, Any]] = []

        for m in resp.data:
            model_id = m.id
            display_name = getattr(m, "display_name", None) or model_id

            matched = None
            for k, v in ANTHROPIC_DEFAULTS.items():
                if k in model_id or model_id in k:
                    matched = v
                    break

            context_length = matched["context"] if matched else 200000
            input_price = matched["input_price"] if matched else 3.00
            output_price = matched["output_price"] if matched else 15.00

            results.append({
                "id": model_id,
                "name": display_name,
                "provider": "anthropic",
                "is_free": 0,
                "context_length": context_length,
                "input_price": input_price,
                "output_price": output_price,
                "last_updated": now_iso,
            })

        return results


def get_default_model(provider_name: str = "gemini") -> str:
    """Returns the default, optimal model identifier for a given provider."""
    defaults = {
        "gemini": "gemini-2.5-flash-lite",
        "openrouter": "google/gemini-2.5-flash",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-haiku-20241022",
        "ollama": "llama3.2:latest",
    }
    return defaults.get(provider_name.lower(), "gemini-2.5-flash-lite")


def get_available_models(provider_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves available models from the singleton ModelRegistry."""
    registry = ModelRegistry()
    return registry.get_models(provider_name or "gemini")


def get_model_descriptor(model_id: str) -> Optional[Dict[str, Any]]:
    """Looks up model specifications from the singleton ModelRegistry."""
    registry = ModelRegistry()
    return registry.get_model_info(model_id)
