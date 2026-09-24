"""Tests for the HeyBloopie Model Router (Part 4).

Tests cover:
- Test that select_model returns a free model when one is available.
- Test that select_model honors user_preference.
- Test that select_model raises NoSuitableModelError when no model fits.
- Test that select_with_fallback returns an ordered list.
- Test that the Core uses the router and falls back on failure.
- Test that active_provider and context window sizes are prioritized.
"""

import os
import sys
from unittest.mock import AsyncMock, patch
import pytest

# Ensure project root and python directory are in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "python")))

from python import core, memory, planner
from python.model_registry import ModelRegistry
from python.model_router import ModelRouter, NoSuitableModelError


@pytest.fixture
def test_env(monkeypatch, tmp_path):
    """Sets up an isolated SQLite database and ModelRegistry for each test."""
    db_file = str(tmp_path / "test_router.db")
    test_mem = memory.Memory(db_path=db_file)
    monkeypatch.setattr(memory, "_default_memory", test_mem)
    monkeypatch.setattr(memory, "get_memory", lambda *a, **k: test_mem)

    registry = ModelRegistry(memory=test_mem)
    router = ModelRouter(registry=registry, memory=test_mem)
    yield test_mem, registry, router
    test_mem.close()


# ═══════════════════════════════════════════════════════════════════
# 1. select_model Returns Free Model When Available
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_select_model_returns_free_model_when_available(test_env):
    """Verify that select_model defaults to a free model over a paid one."""
    mem, registry, router = test_env

    mem.save_models([
        {
            "id": "gpt-4o",
            "name": "GPT-4o",
            "provider": "openai",
            "is_free": 0,
            "context_length": 128000,
            "input_price": 2.50,
            "output_price": 10.00,
            "last_updated": memory.get_iso_timestamp(),
        },
        {
            "id": "gemini-2.5-flash-lite",
            "name": "Gemini 2.5 Flash Lite",
            "provider": "gemini",
            "is_free": 1,
            "context_length": 1048576,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": memory.get_iso_timestamp(),
        },
    ])
    mem.set_preference("active_provider", "gemini")

    chosen = await router.select_model("Find my invoices")
    assert chosen == "gemini-2.5-flash-lite"


# ═══════════════════════════════════════════════════════════════════
# 2. select_model Honors user_preference
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_select_model_honors_user_preference(test_env):
    """Verify that user_preference override takes priority if the model exists."""
    mem, registry, router = test_env

    mem.save_models([
        {
            "id": "gemini-2.5-flash-lite",
            "name": "Gemini 2.5 Flash Lite",
            "provider": "gemini",
            "is_free": 1,
            "context_length": 1048576,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": memory.get_iso_timestamp(),
        },
        {
            "id": "claude-3-5-sonnet-20241022",
            "name": "Claude 3.5 Sonnet",
            "provider": "anthropic",
            "is_free": 0,
            "context_length": 200000,
            "input_price": 3.00,
            "output_price": 15.00,
            "last_updated": memory.get_iso_timestamp(),
        },
    ])

    # Explicitly ask for paid Claude
    chosen = await router.select_model(
        "Complex architecture review", user_preference="claude-3-5-sonnet-20241022"
    )
    assert chosen == "claude-3-5-sonnet-20241022"

    # If requested model does not exist, it falls back to best free model
    fallback_chosen = await router.select_model(
        "Find file", user_preference="non-existent-model"
    )
    assert fallback_chosen == "gemini-2.5-flash-lite"


# ═══════════════════════════════════════════════════════════════════
# 3. select_model Raises NoSuitableModelError
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_select_model_raises_no_suitable_model_error(test_env):
    """Verify NoSuitableModelError is raised when no free model exists and paid/local fallbacks are disabled."""
    mem, registry, router = test_env

    # Only paid models exist in registry
    mem.save_models([
        {
            "id": "gpt-4o",
            "name": "GPT-4o",
            "provider": "openai",
            "is_free": 0,
            "context_length": 128000,
            "input_price": 2.50,
            "output_price": 10.00,
            "last_updated": memory.get_iso_timestamp(),
        }
    ])
    mem.set_preference("allow_paid_fallback", "false")
    mem.set_preference("allow_local_fallback", "false")

    with pytest.raises(NoSuitableModelError):
        await router.select_model("Find reports")


# ═══════════════════════════════════════════════════════════════════
# 4. select_with_fallback Returns Ordered List
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_select_with_fallback_returns_ordered_list(test_env):
    """Verify fallback sequence follows: user_preference -> free (best first) -> paid -> local."""
    mem, registry, router = test_env

    now_ts = memory.get_iso_timestamp()
    mem.save_models([
        # User preferred model
        {
            "id": "custom-preferred",
            "name": "Custom Preferred",
            "provider": "anthropic",
            "is_free": 0,
            "context_length": 100000,
            "input_price": 5.0,
            "output_price": 10.0,
            "last_updated": now_ts,
        },
        # Active provider free model (Gemini)
        {
            "id": "gemini-2.5-flash",
            "name": "Gemini 2.5 Flash",
            "provider": "gemini",
            "is_free": 1,
            "context_length": 1048576,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": now_ts,
        },
        # Other provider free model (OpenRouter)
        {
            "id": "meta-llama/llama-3.3-70b-instruct:free",
            "name": "Llama 3.3 (free)",
            "provider": "openrouter",
            "is_free": 1,
            "context_length": 131072,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": now_ts,
        },
        # Cheaper paid model
        {
            "id": "gpt-4o-mini",
            "name": "GPT-4o Mini",
            "provider": "openai",
            "is_free": 0,
            "context_length": 128000,
            "input_price": 0.15,
            "output_price": 0.60,
            "last_updated": now_ts,
        },
        # Expensive paid model
        {
            "id": "claude-3-opus",
            "name": "Claude 3 Opus",
            "provider": "anthropic",
            "is_free": 0,
            "context_length": 200000,
            "input_price": 15.00,
            "output_price": 75.00,
            "last_updated": now_ts,
        },
        # Local model
        {
            "id": "llama3.2:latest",
            "name": "Llama 3.2 Local",
            "provider": "ollama",
            "is_free": 1,
            "context_length": 8192,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": now_ts,
        },
    ])

    mem.set_preference("active_provider", "gemini")
    mem.set_preference("allow_paid_fallback", "true")
    mem.set_preference("allow_local_fallback", "true")

    sequence = await router.select_with_fallback(
        "Find file", user_preference="custom-preferred"
    )

    expected = [
        "custom-preferred",                          # 1. user_preference
        "gemini-2.5-flash",                          # 2. active provider free model (large context)
        "meta-llama/llama-3.3-70b-instruct:free",    # 3. other provider free model
        "gpt-4o-mini",                               # 4. cheaper paid fallback
        "claude-3-opus",                             # 5. more expensive paid fallback
        "llama3.2:latest",                           # 6. local fallback
    ]
    assert sequence == expected


# ═══════════════════════════════════════════════════════════════════
# 5. Core Uses Router and Falls Back on Failure
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_core_uses_router_and_falls_back_on_failure(test_env, monkeypatch):
    """Verify that Core runs fallback sequence when the primary model encounters a rate limit error."""
    mem, registry, router = test_env

    now_ts = memory.get_iso_timestamp()
    mem.save_models([
        {
            "id": "primary-model",
            "name": "Primary Model",
            "provider": "gemini",
            "is_free": 1,
            "context_length": 1048576,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": now_ts,
        },
        {
            "id": "backup-model",
            "name": "Backup Model",
            "provider": "openrouter",
            "is_free": 1,
            "context_length": 131072,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": now_ts,
        },
    ])
    mem.set_preference("active_provider", "gemini")

    attempted_models = []

    async def mock_create_plan_with_fallback(user_request: str, available_tools=None, model=None):
        attempted_models.append(model)
        if model == "primary-model":
            # Primary model hits rate limit / quota error
            raise Exception("429 Too Many Requests: Quota limit exceeded for provider")
        # Backup model succeeds
        return planner.Plan(
            steps=[
                planner.PlanStep(
                    tool_name="find_files",
                    params={"query": "backup_result"},
                    risk_level="low",
                    description="Find backup files",
                )
            ],
            summary="Fallback plan generated successfully.",
            requires_confirmation=False,
        )

    monkeypatch.setattr(planner, "create_plan", mock_create_plan_with_fallback)

    # Mock tool layer so execution succeeds
    monkeypatch.setattr(
        core.tools,
        "find_files",
        AsyncMock(
            return_value=core.tools.ToolResult(
                success=True,
                data=["backup_result.txt"],
                message="Found 1 file",
                verified=True,
                verification_details="Verified",
            )
        ),
    )

    report = await core.run("search my documents")

    # Verify both models were attempted in order
    assert attempted_models == ["primary-model", "backup-model"]
    # Verify overall Core execution succeeded via backup
    assert report.success is True
    assert report.summary.startswith("Done.")
    assert report.steps_succeeded == 1


# ═══════════════════════════════════════════════════════════════════
# 6. Active Provider and Context Window Prioritization
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_active_provider_and_context_window_prioritized(test_env):
    """Verify that among free models, active_provider is preferred first, then context length."""
    mem, registry, router = test_env

    now_ts = memory.get_iso_timestamp()
    mem.save_models([
        {
            "id": "openrouter-large-context",
            "name": "OpenRouter Big",
            "provider": "openrouter",
            "is_free": 1,
            "context_length": 2000000,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": now_ts,
        },
        {
            "id": "gemini-medium-context",
            "name": "Gemini Medium",
            "provider": "gemini",
            "is_free": 1,
            "context_length": 1048576,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": now_ts,
        },
    ])

    # When active provider is Gemini: Gemini is selected even with lower context
    mem.set_preference("active_provider", "gemini")
    chosen_gemini = await router.select_model("Prompt")
    assert chosen_gemini == "gemini-medium-context"

    # When active provider is OpenRouter: OpenRouter is selected
    mem.set_preference("active_provider", "openrouter")
    chosen_openrouter = await router.select_model("Prompt")
    assert chosen_openrouter == "openrouter-large-context"
