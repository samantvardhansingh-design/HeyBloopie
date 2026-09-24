"""HeyBloopie Model Router.

This module decides which AI model and provider to use for a given task based on
user preferences, free-model availability, context window limits, cost, and fallback rules.
"""

import logging
from typing import Any, Dict, List, Optional

try:
    from python import memory, model_registry
    from python.memory import Memory, get_memory
    from python.model_registry import ModelRegistry
except (ImportError, ModuleNotFoundError):
    import memory
    import model_registry
    from memory import Memory, get_memory
    from model_registry import ModelRegistry

logger = logging.getLogger("heybloopie.model_router")


class NoSuitableModelError(Exception):
    """Raised when no suitable model can be selected according to active routing rules."""
    pass


def _is_pref_true(val: Any, default: bool = False) -> bool:
    """Helper to parse boolean configuration values from SQLite preferences."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    return str(val).lower().strip() in ("true", "1", "yes")


class ModelRouter:
    """Selects and prioritizes models based on user preference, pricing, and availability."""

    def __init__(self, registry: Optional[ModelRegistry] = None, memory: Optional[Memory] = None):
        """Initializes the ModelRouter with ModelRegistry and Memory references."""
        self.memory = memory if memory is not None else get_memory()
        self.registry = registry if registry is not None else ModelRegistry(self.memory)

    async def select_model(self, user_request: str, user_preference: Optional[str] = None) -> str:
        """Selects the best available model according to routing rules.

        Selection Rules:
        1. If user_preference is provided AND the model exists in the registry, return it.
        2. Get all configured models from the registry.
        3. Collect all FREE models across all providers.
        4. If any free model exists, return the best one:
           - Prefer models from the active_provider preference.
           - Prefer models with larger context windows.
        5. If no free model exists, check routing rules:
           - If allow_paid_fallback is True, return the cheapest paid model.
           - If allow_local_fallback is True and Ollama is available, return an Ollama model.
        6. If nothing suitable, raise NoSuitableModelError.

        Args:
            user_request: The user's input prompt or command.
            user_preference: Optional explicit model ID preference override.

        Returns:
            The selected model identifier string.

        Raises:
            NoSuitableModelError: If no model satisfies the rules.
        """
        candidates = await self.select_with_fallback(user_request, user_preference)
        if not candidates:
            raise NoSuitableModelError(
                "No suitable model found matching routing rules. Please check your provider settings."
            )
        return candidates[0]

    async def select_with_fallback(
        self, user_request: str, user_preference: Optional[str] = None
    ) -> List[str]:
        """Returns an ordered list of model IDs to try in sequence.

        Order:
        1. user_preference (if provided and exists in registry).
        2. Free models (best first: active provider, then largest context window).
        3. Paid fallback models (cheapest first), if allow_paid_fallback is enabled.
        4. Local fallback models (Ollama), if allow_local_fallback is enabled.

        Args:
            user_request: The user's input prompt or command.
            user_preference: Optional explicit model ID preference.

        Returns:
            Ordered list of unique model ID strings to attempt.
        """
        ordered: List[str] = []

        def add_model(mid: str) -> None:
            if mid and mid not in ordered:
                ordered.append(mid)

        # 1. User explicit preference override
        if user_preference:
            info = self.registry.get_model_info(user_preference)
            if info:
                add_model(user_preference)

        # 2. Retrieve all known models from SQLite
        all_models = self.registry.get_models()

        # Retrieve preference settings
        active_provider = (self.memory.get_preference("active_provider") or "gemini").lower().strip()
        allow_paid = _is_pref_true(self.memory.get_preference("allow_paid_fallback"), default=False)
        allow_local = _is_pref_true(self.memory.get_preference("allow_local_fallback"), default=False)

        # Separate models into free, paid, and local
        if active_provider == "ollama":
            # If active provider is Ollama, treat Ollama models as the primary free pool
            free_models = [m for m in all_models if m.get("is_free") == 1]
            local_models: List[Dict[str, Any]] = []
        else:
            free_models = [
                m for m in all_models
                if m.get("is_free") == 1 and m.get("provider", "").lower() != "ollama"
            ]
            local_models = [
                m for m in all_models
                if m.get("provider", "").lower() == "ollama"
            ]

        paid_models = [m for m in all_models if m.get("is_free") == 0]

        # 3. Best Free Models First:
        # Prefer models from active_provider, then larger context window
        sorted_free = sorted(
            free_models,
            key=lambda m: (
                1 if m.get("provider", "").lower() == active_provider else 0,
                m.get("context_length", 0) or 0,
            ),
            reverse=True,
        )
        for m in sorted_free:
            add_model(m["id"])

        # 4. Paid Fallback (cheapest input price first, then larger context window)
        if allow_paid:
            sorted_paid = sorted(
                paid_models,
                key=lambda m: (
                    m.get("input_price", float("inf")) or 0.0,
                    -(m.get("context_length", 0) or 0),
                ),
            )
            for m in sorted_paid:
                add_model(m["id"])

        # 5. Local Fallback (Ollama)
        if allow_local and active_provider != "ollama":
            sorted_local = sorted(
                local_models,
                key=lambda m: (m.get("context_length", 0) or 0),
                reverse=True,
            )
            for m in sorted_local:
                add_model(m["id"])

        return ordered


# Backward-compatibility helper functions
def route_request(
    task_type: str, requires_offline: bool = False, preferred_provider: Optional[str] = None
) -> Dict[str, str]:
    """Helper returning chosen provider and model for a given task type."""
    defaults = {
        "gemini": "gemini-2.5-flash-lite",
        "openrouter": "google/gemini-2.5-flash",
        "openai": "gpt-4o-mini",
        "anthropic": "claude-3-5-haiku-20241022",
        "ollama": "llama3.2:latest",
    }
    provider = preferred_provider or ("ollama" if requires_offline else "gemini")
    model = defaults.get(provider.lower(), "gemini-2.5-flash-lite")
    return {"provider": provider, "model": model}


def should_fallback(error: Exception) -> bool:
    """Determines if a model failure qualifies for automatic fallback."""
    err_str = str(error).lower()
    type_name = type(error).__name__.lower()
    fallback_keywords = [
        "rate", "limit", "429", "quota", "exhausted",
        "unavailable", "503", "connection", "connect", "timeout", "offline", "overloaded"
    ]
    return any(kw in err_str or kw in type_name for kw in fallback_keywords)
