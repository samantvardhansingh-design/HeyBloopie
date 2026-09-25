"""HeyBloopie AI Provider Abstraction Layer.

Defines the abstract base class AIProvider and the ProviderFactory for managing
multi-vendor LLM integrations (Gemini, OpenRouter, OpenAI, Anthropic, Ollama).
"""

from abc import ABC, abstractmethod
import logging
from typing import Any, AsyncIterator, Dict, List, Optional
import keyring

logger = logging.getLogger("heybloopie.provider")

KEYRING_SERVICE = "heybloopie"


class AIProvider(ABC):
    """Abstract base class for all AI providers in HeyBloopie."""

    @abstractmethod
    async def generate(self, prompt: str, options: Optional[dict] = None) -> str:
        """Generates a complete response for the given prompt.

        Args:
            prompt: Text prompt string.
            options: Optional configuration overrides (e.g. model, temperature).

        Returns:
            The complete generated text, or an error message if an error occurred.
        """
        pass

    @abstractmethod
    async def stream(self, prompt: str, options: Optional[dict] = None) -> AsyncIterator[str]:
        """Streams text chunks as an async generator as they arrive from the provider.

        Args:
            prompt: Text prompt string.
            options: Optional configuration overrides.

        Yields:
            Text chunks string as they arrive.
        """
        pass

    @abstractmethod
    async def is_available(self) -> bool:
        """Checks if the provider is configured and available for requests.

        Returns:
            True if available and configured, False otherwise.
        """
        pass

    @abstractmethod
    def get_model_info(self) -> dict:
        """Returns metadata about the active model.

        Returns:
            Dict containing provider, model name, and related capabilities.
        """
        pass


class ProviderFactory:
    """Factory for managing AI providers and enforcing keyring storage constraints."""

    SUPPORTED_PROVIDERS = ["gemini", "openrouter", "openai", "anthropic", "ollama"]

    @staticmethod
    def get_provider(name: str) -> AIProvider:
        """Instantiates and returns an AIProvider adapter.

        Args:
            name: Provider identifier ('gemini', 'openrouter', 'openai', 'anthropic', 'ollama').

        Returns:
            An instance of AIProvider.

        Raises:
            ValueError: If the provider is unsupported or has no key configured.
        """
        norm_name = name.lower().strip()
        if norm_name not in ProviderFactory.SUPPORTED_PROVIDERS:
            raise ValueError(f"Unknown provider: {name}. Supported: {ProviderFactory.SUPPORTED_PROVIDERS}")

        # The ProviderFactory MUST NOT instantiate adapters for providers that have no key configured.
        # Ollama is a local server and does not require an API key.
        if norm_name != "ollama":
            try:
                key = keyring.get_password(KEYRING_SERVICE, norm_name)
            except Exception as e:
                logger.error(f"Error querying keyring for {norm_name}: {e}")
                key = None

            if not key or not str(key).strip():
                raise ValueError(f"Provider '{name}' has no key configured in keyring.")

        if norm_name == "gemini":
            from python.providers.gemini_adapter import GeminiAdapter
            return GeminiAdapter()
        elif norm_name == "openrouter":
            from python.providers.openrouter_adapter import OpenRouterAdapter
            return OpenRouterAdapter()
        elif norm_name == "openai":
            from python.providers.openai_adapter import OpenAIAdapter
            return OpenAIAdapter()
        elif norm_name == "anthropic":
            from python.providers.anthropic_adapter import AnthropicAdapter
            return AnthropicAdapter()
        elif norm_name == "ollama":
            from python.providers.ollama_adapter import OllamaAdapter
            return OllamaAdapter()

        raise ValueError(f"Unsupported provider: {name}")

    @staticmethod
    def list_available_providers() -> List[str]:
        """Lists providers that currently have keys configured in keyring.

        Returns:
            List of provider names that have keys configured.
        """
        available: List[str] = []
        for name in ["gemini", "openrouter", "openai", "anthropic"]:
            try:
                key = keyring.get_password(KEYRING_SERVICE, name)
                if key and str(key).strip():
                    available.append(name)
            except Exception:
                pass
        return available


async def generate_plan(prompt: str, options: Optional[dict] = None) -> str:
    """Backward-compatible helper used by planner.py and test suites."""
    factory = ProviderFactory()

    # If options contains a specific model, attempt to route to that model's provider
    if options and options.get("model"):
        chosen_model = options["model"]
        try:
            from python.model_registry import ModelRegistry
            info = ModelRegistry().get_model_info(chosen_model)
            if info and info.get("provider"):
                provider_inst = factory.get_provider(info["provider"])
                return await provider_inst.generate(prompt, options=options)
        except Exception as e:
            logger.debug(f"Could not route specific model {chosen_model} via registry: {e}")

    # Check active_provider preference from memory first
    try:
        from python import memory
        active_prov = (memory.get_preference("active_provider") or "").lower().strip()
        if active_prov:
            provider_inst = factory.get_provider(active_prov)
            if await provider_inst.is_available():
                return await provider_inst.generate(prompt, options=options)
    except Exception as e:
        logger.debug(f"Could not route to active_provider: {e}")

    available = factory.list_available_providers()
    if "gemini" in available:
        provider = factory.get_provider("gemini")
    elif available:
        provider = factory.get_provider(available[0])
    else:
        from python.providers.gemini_adapter import GeminiAdapter
        provider = GeminiAdapter()
    return await provider.generate(prompt, options=options)


PROVIDER_PREFIXES = {
    "gemini": ("AIzaSy", "AQ."),
    "openai": "sk-",
    "anthropic": "sk-ant-",
    "openrouter": "sk-or-",
}

PROVIDER_DISPLAY_NAMES = {
    "gemini": "Gemini",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "openrouter": "OpenRouter",
    "ollama": "Ollama",
}


async def validate_provider_key(provider: str, key: str) -> Dict[str, Any]:
    """Validates an API key by checking its format and making a minimal API call.

    On success, stores the key in keyring under service 'heybloopie' and sets the
    'active_provider' preference in SQLite memory.

    Returns:
        Dict with 'success': bool, and optionally 'error': str, 'provider': str.
    """
    prov = provider.lower().strip()
    clean_key = (key or "").strip()
    display_name = PROVIDER_DISPLAY_NAMES.get(prov, provider.capitalize())

    # 1. Format validation
    expected_prefix = PROVIDER_PREFIXES.get(prov)
    if expected_prefix:
        prefixes = expected_prefix if isinstance(expected_prefix, tuple) else (expected_prefix,)
        if not any(clean_key.startswith(p) for p in prefixes):
            display_prefix = prefixes[0]
            return {
                "success": False,
                "error": f"That doesn't look like a valid key. Make sure you copied the full key. It usually starts with {display_prefix}.",
            }

    # 2. Minimal API Call
    try:
        if prov == "gemini":
            from google import genai
            client = genai.Client(api_key=clean_key)
            if hasattr(client, "aio") and hasattr(client.aio, "models"):
                try:
                    await client.aio.models.list()
                except Exception:
                    await client.aio.models.get(model="gemini-2.5-flash-lite")
            else:
                try:
                    client.models.list()
                except Exception:
                    client.models.get(model="gemini-2.5-flash-lite")

        elif prov == "openai":
            import openai
            client = openai.AsyncOpenAI(api_key=clean_key, timeout=10.0)
            await client.models.list()

        elif prov == "anthropic":
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=clean_key, timeout=10.0)
            await client.models.list()

        elif prov == "openrouter":
            import openai
            client = openai.AsyncOpenAI(
                api_key=clean_key,
                base_url="https://openrouter.ai/api/v1",
                timeout=10.0,
            )
            await client.models.list()

        elif prov == "ollama":
            return await check_ollama()

        else:
            return {
                "success": False,
                "error": f"Unknown provider: {provider}",
            }

    except Exception as e:
        err_str = str(e).lower()
        err_type = type(e).__name__.lower()

        # Check for quota / rate limits
        if any(term in err_str for term in ["quota", "429", "resource_exhausted", "ratelimit"]):
            return {
                "success": False,
                "error": "Your key works, but your account has no quota left.",
            }

        # Check for authentication / rejection
        if any(term in err_str for term in ["401", "403", "unauthorized", "authentication", "api_key_invalid", "invalid api key", "not recognized"]):
            return {
                "success": False,
                "error": f"{display_name} didn't recognize this key. It may have been deleted or copied incorrectly.",
            }

        # Check for connection / network issues
        if any(term in err_str for term in ["connection", "connect", "timeout", "network", "unreachable", "dns"]) or "connection" in err_type or "timeout" in err_type:
            return {
                "success": False,
                "error": f"I can't reach {display_name}. Check your internet connection.",
            }

        # Check for server outage / 5xx
        if any(term in err_str for term in ["500", "502", "503", "504", "internal server error", "overloaded", "bad gateway"]):
            return {
                "success": False,
                "error": f"{display_name}'s servers are not responding right now.",
            }

        # Generic rejection fallback
        return {
            "success": False,
            "error": f"{display_name} didn't recognize this key. It may have been deleted or copied incorrectly.",
        }

    # 3. Success: store key in keyring and save preference
    try:
        keyring.set_password(KEYRING_SERVICE, prov, clean_key)
    except Exception as e:
        logger.warning(f"Failed to store key in keyring: {e}")

    try:
        from python import memory
        memory.set_preference("active_provider", prov)
    except Exception as e:
        logger.warning(f"Failed to set active_provider preference: {e}")

    return {
        "success": True,
        "provider": prov,
    }


async def check_ollama(base_url: str = "http://localhost:11434") -> Dict[str, Any]:
    """Checks if local Ollama server is running and returns installed models."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            res = await client.get(f"{base_url.rstrip('/')}/api/tags")
            if res.status_code == 200:
                data = res.json()
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                try:
                    from python import memory
                    memory.set_preference("active_provider", "ollama")
                except Exception:
                    pass
                return {
                    "success": True,
                    "detected": True,
                    "models": models,
                }
    except Exception:
        pass

    return {
        "success": False,
        "detected": False,
        "models": [],
        "error": "Ollama server not detected.",
    }
