"""HeyBloopie Model Registry.

This module maintains the catalog of supported foundation models, their vendor specifications,
token limits, recommended task assignments (fast reasoning, lightweight classification, complex planning),
and capabilities (e.g. structured output, prompt caching support).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


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


def get_available_models() -> List[ModelDescriptor]:
    """Retrieves the list of all registered models across supported providers.

    Returns:
        A list of ModelDescriptor records.
    """
    pass


def get_model_descriptor(model_id: str) -> Optional[ModelDescriptor]:
    """Looks up detailed capabilities and specifications for a specific model ID.

    Args:
        model_id: Identifier (e.g. 'gemini-1.5-flash', 'claude-3-5-sonnet', 'llama3').

    Returns:
        ModelDescriptor if found, None otherwise.
    """
    pass


def get_default_model(provider_name: str = "gemini") -> str:
    """Returns the default, optimal model identifier for a given provider.

    Args:
        provider_name: Provider name.

    Returns:
        Standard model string identifier.
    """
    pass
