"""HeyBloopie Provider Abstraction Layer (PAL).

This module standardizes communication with AI model providers. It provides a unified,
agnostic interface so that the Core and Planner remain completely insulated from specific
provider SDKs, payload formats, and API nuances.

Supported Target Providers:
- Google Gemini (primary via google-generativeai SDK)
- OpenAI
- Anthropic Claude
- OpenRouter
- Ollama (offline local models)
"""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional


class AIProvider(ABC):
    """Abstract base class establishing the contract for all AI model providers."""

    @abstractmethod
    async def complete(self, prompt: str, schema: Optional[Dict[str, Any]] = None) -> str:
        """Sends a completion request and returns the full generated text/JSON.

        Args:
            prompt: Structured prompt string.
            schema: Optional JSON schema for structured output enforcement.

        Returns:
            The raw text response from the model.
        """
        pass

    @abstractmethod
    async def stream_response(self, prompt: str) -> AsyncIterator[str]:
        """Streams token-by-token responses from the provider.

        Args:
            prompt: Prompt string.

        Yields:
            Incremental text chunks as they arrive from the provider.
        """
        pass


class GeminiProvider(AIProvider):
    """Google Gemini implementation using the google-generativeai SDK."""

    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash"):
        self.api_key = api_key
        self.model_name = model_name

    async def complete(self, prompt: str, schema: Optional[Dict[str, Any]] = None) -> str:
        pass

    async def stream_response(self, prompt: str) -> AsyncIterator[str]:
        pass


def get_provider(provider_name: str = "gemini") -> AIProvider:
    """Factory function to instantiate and retrieve configured AI provider.

    Args:
        provider_name: Name of provider ('gemini', 'openai', 'anthropic', 'ollama', 'openrouter').

    Returns:
        Configured AIProvider instance loaded with credentials from Windows Credential Manager.
    """
    pass
