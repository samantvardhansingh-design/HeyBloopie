"""HeyBloopie Model Router.

This module dynamically routes tasks to the most suitable model and provider based on
task complexity (lightweight classification vs. deep multi-step planning), offline status,
latency budgets, and user preferences.
"""

from typing import Any, Dict, Optional


def route_request(task_type: str, requires_offline: bool = False, preferred_provider: Optional[str] = None) -> Dict[str, str]:
    """Determines the optimal provider and model identifier for a given task.

    Args:
        task_type: Type of task ('fast_intent', 'planning', 'summarization').
        requires_offline: Whether the task must strictly run on local compute (e.g. Ollama).
        preferred_provider: User-selected override provider, if configured.

    Returns:
        A dictionary containing chosen 'provider' and 'model' keys.
    """
    pass


def should_fallback(error: Exception) -> bool:
    """Determines if a model failure (e.g., rate limit, network timeout) qualifies for automatic fallback.

    Args:
        error: The encountered exception from the active provider.

    Returns:
        True if the request should be retried on a fallback model/provider, False otherwise.
    """
    pass
