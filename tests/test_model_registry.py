"""Tests for the HeyBloopie Model Registry (Part 3).

Tests cover:
- Mock OpenRouter response: verify free models identified (pricing.prompt == "0" -> is_free == 1).
- Mock Ollama response: verify all models marked free.
- Test get_models returns cached data without calling API.
- Test refresh_models does not overwrite data on API failure.
- 7-day caching policy behavior.
- get_model_info lookup for existing and non-existing models.
"""

from datetime import datetime, timedelta, timezone
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "python")))

from python import memory
from python.model_registry import ModelRegistry, is_cache_expired


@pytest.fixture
def mock_memory(monkeypatch, tmp_path):
    """Sets up an isolated SQLite memory database for each test."""
    db_file = str(tmp_path / "test_models.db")
    test_mem = memory.Memory(db_path=db_file)
    monkeypatch.setattr(memory, "_default_memory", test_mem)
    monkeypatch.setattr(memory, "get_memory", lambda *a, **k: test_mem)
    yield test_mem
    test_mem.close()


# ═══════════════════════════════════════════════════════════════════
# 1. OpenRouter Response & Free Models Identification
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_openrouter_free_models_identified(mock_memory):
    """Verify that OpenRouter models with pricing.prompt == '0' are marked is_free = 1."""
    registry = ModelRegistry(memory=mock_memory)

    mock_response_data = {
        "data": [
            {
                "id": "meta-llama/llama-3.3-70b-instruct:free",
                "name": "Meta: Llama 3.3 70B Instruct (free)",
                "context_length": 131072,
                "pricing": {
                    "prompt": "0",
                    "completion": "0",
                },
            },
            {
                "id": "google/gemini-2.5-flash",
                "name": "Google: Gemini 2.5 Flash",
                "context_length": 1048576,
                "pricing": {
                    "prompt": "0.000000075",
                    "completion": "0.0000003",
                },
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        await registry.refresh_models("openrouter", force=True)

    models = registry.get_models("openrouter")
    assert len(models) == 2

    free_model = next(m for m in models if m["id"] == "meta-llama/llama-3.3-70b-instruct:free")
    assert free_model["is_free"] == 1
    assert free_model["input_price"] == 0.0
    assert free_model["output_price"] == 0.0
    assert free_model["context_length"] == 131072

    paid_model = next(m for m in models if m["id"] == "google/gemini-2.5-flash")
    assert paid_model["is_free"] == 0
    assert pytest.approx(paid_model["input_price"], 0.001) == 0.075
    assert pytest.approx(paid_model["output_price"], 0.001) == 0.30
    assert paid_model["context_length"] == 1048576


# ═══════════════════════════════════════════════════════════════════
# 2. Ollama Response & All Models Marked Free
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ollama_all_models_marked_free(mock_memory):
    """Verify that all Ollama local models are marked is_free = 1 with zero pricing."""
    registry = ModelRegistry(memory=mock_memory)

    mock_response_data = {
        "models": [
            {
                "name": "llama3.2:latest",
                "model": "llama3.2:latest",
                "size": 2019393189,
            },
            {
                "name": "mistral:latest",
                "model": "mistral:latest",
                "size": 4109393189,
            },
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_data
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        await registry.refresh_models("ollama", force=True)

    models = registry.get_models("ollama")
    assert len(models) == 2
    for m in models:
        assert m["is_free"] == 1
        assert m["input_price"] == 0.0
        assert m["output_price"] == 0.0
        assert m["provider"] == "ollama"


# ═══════════════════════════════════════════════════════════════════
# 3. get_models Returns Cached Data Without Calling API
# ═══════════════════════════════════════════════════════════════════

def test_get_models_returns_cached_data_without_calling_api(mock_memory):
    """Verify get_models strictly reads from SQLite cache without invoking any network calls."""
    registry = ModelRegistry(memory=mock_memory)

    # Pre-seed models in SQLite
    mock_memory.save_models([
        {
            "id": "cached-model-1",
            "name": "Cached Model 1",
            "provider": "openrouter",
            "is_free": 1,
            "context_length": 32768,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": memory.get_iso_timestamp(),
        },
        {
            "id": "cached-model-2",
            "name": "Cached Model 2",
            "provider": "openrouter",
            "is_free": 0,
            "context_length": 65536,
            "input_price": 1.5,
            "output_price": 3.0,
            "last_updated": memory.get_iso_timestamp(),
        },
    ])

    # Ensure no network call happens even if httpx would fail
    with patch("httpx.AsyncClient.get", side_effect=RuntimeError("Network should not be called!")):
        cached = registry.get_models("openrouter")

    assert len(cached) == 2
    assert cached[0]["id"] == "cached-model-1"
    assert cached[1]["id"] == "cached-model-2"


# ═══════════════════════════════════════════════════════════════════
# 4. refresh_models Does Not Overwrite Data on API Failure
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_refresh_models_does_not_overwrite_data_on_api_failure(mock_memory):
    """Verify that existing cached models are preserved if an API call fails."""
    registry = ModelRegistry(memory=mock_memory)

    # Pre-seed existing models
    mock_memory.save_models([
        {
            "id": "existing-model",
            "name": "Existing Safe Model",
            "provider": "openrouter",
            "is_free": 1,
            "context_length": 16384,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": memory.get_iso_timestamp(),
        }
    ])

    # Trigger a network failure on refresh
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("Connection refused")):
        await registry.refresh_models("openrouter", force=True)

    # Verify existing model is still in database and not overwritten or cleared
    models = registry.get_models("openrouter")
    assert len(models) == 1
    assert models[0]["id"] == "existing-model"
    assert models[0]["name"] == "Existing Safe Model"


# ═══════════════════════════════════════════════════════════════════
# 5. 7-Day Caching Policy Behavior
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_refresh_models_respects_7_day_cache(mock_memory):
    """Verify refresh_models skips API call if cached data is under 7 days old, unless forced."""
    registry = ModelRegistry(memory=mock_memory)

    recent_ts = datetime.now(timezone.utc).isoformat()
    mock_memory.save_models([
        {
            "id": "fresh-model",
            "name": "Fresh Model",
            "provider": "openrouter",
            "is_free": 1,
            "context_length": 8192,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": recent_ts,
        }
    ])

    # Attempt refresh without force - API must NOT be called
    mock_get = AsyncMock()
    with patch("httpx.AsyncClient.get", mock_get):
        await registry.refresh_models("openrouter", force=False)
        assert mock_get.call_count == 0

    # Old timestamp (> 7 days)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    mock_memory.save_models([
        {
            "id": "fresh-model",
            "name": "Fresh Model",
            "provider": "openrouter",
            "is_free": 1,
            "context_length": 8192,
            "input_price": 0.0,
            "output_price": 0.0,
            "last_updated": old_ts,
        }
    ])

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": [
            {
                "id": "refreshed-model",
                "name": "Refreshed Model",
                "context_length": 8192,
                "pricing": {"prompt": "0", "completion": "0"},
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp) as mock_fetch:
        await registry.refresh_models("openrouter", force=False)
        assert mock_fetch.call_count == 1

    updated_models = registry.get_models("openrouter")
    assert any(m["id"] == "refreshed-model" for m in updated_models)


# ═══════════════════════════════════════════════════════════════════
# 6. get_model_info Single Model Lookup
# ═══════════════════════════════════════════════════════════════════

def test_get_model_info_lookup(mock_memory):
    """Verify single model info retrieval by ID."""
    registry = ModelRegistry(memory=mock_memory)

    mock_memory.save_models([
        {
            "id": "gemini-2.5-flash-lite",
            "name": "Gemini 2.5 Flash Lite",
            "provider": "gemini",
            "is_free": 1,
            "context_length": 1048576,
            "input_price": 0.075,
            "output_price": 0.30,
            "last_updated": memory.get_iso_timestamp(),
        }
    ])

    info = registry.get_model_info("gemini-2.5-flash-lite")
    assert info is not None
    assert info["id"] == "gemini-2.5-flash-lite"
    assert info["provider"] == "gemini"
    assert info["is_free"] == 1
    assert info["input_price"] == 0.075

    non_existent = registry.get_model_info("non-existent-model")
    assert non_existent is None


# ═══════════════════════════════════════════════════════════════════
# 7. Gemini, OpenAI, Anthropic Refresh Mock Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_gemini_models_refresh(mock_memory, monkeypatch):
    """Verify Gemini models are parsed and persisted using google-genai client."""
    monkeypatch.setattr("keyring.get_password", lambda svc, u: "AIzaSyTestKey123")
    registry = ModelRegistry(memory=mock_memory)

    class MockGeminiModel:
        def __init__(self, name, display_name, input_token_limit, supported_actions):
            self.name = name
            self.display_name = display_name
            self.input_token_limit = input_token_limit
            self.supported_actions = supported_actions

    class MockPager:
        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            yield MockGeminiModel("models/gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite", 1048576, ["generateContent"])
            yield MockGeminiModel("models/gemini-2.5-flash", "Gemini 2.5 Flash", 1048576, ["generateContent"])
            yield MockGeminiModel("models/text-embedding-004", "Embedding", 2048, ["embedContent"])

    mock_client = MagicMock()
    mock_client.aio.models.list = AsyncMock(return_value=MockPager())

    with patch("google.genai.Client", return_value=mock_client):
        await registry.refresh_models("gemini", force=True)

    models = registry.get_models("gemini")
    assert len(models) == 2
    assert any(m["id"] == "gemini-2.5-flash-lite" for m in models)
    assert any(m["id"] == "gemini-2.5-flash" for m in models)
    # Embedding model excluded
    assert not any(m["id"] == "text-embedding-004" for m in models)


@pytest.mark.asyncio
async def test_openai_models_refresh(mock_memory, monkeypatch):
    """Verify OpenAI chat models are parsed and persisted."""
    monkeypatch.setattr("keyring.get_password", lambda svc, u: "sk-testkey123")
    registry = ModelRegistry(memory=mock_memory)

    class MockModel:
        def __init__(self, id_):
            self.id = id_

    mock_resp = MagicMock()
    mock_resp.data = [
        MockModel("gpt-4o-mini"),
        MockModel("gpt-4o"),
        MockModel("text-embedding-3-small"),
    ]

    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(return_value=mock_resp)

    with patch("openai.AsyncOpenAI", return_value=mock_client):
        await registry.refresh_models("openai", force=True)

    models = registry.get_models("openai")
    assert len(models) == 2
    assert any(m["id"] == "gpt-4o-mini" for m in models)
    assert any(m["id"] == "gpt-4o" for m in models)
    assert not any(m["id"] == "text-embedding-3-small" for m in models)


@pytest.mark.asyncio
async def test_anthropic_models_refresh(mock_memory, monkeypatch):
    """Verify Anthropic Claude models are parsed and persisted."""
    monkeypatch.setattr("keyring.get_password", lambda svc, u: "sk-ant-testkey123")
    registry = ModelRegistry(memory=mock_memory)

    class MockAnthropicModel:
        def __init__(self, id_, display_name):
            self.id = id_
            self.display_name = display_name

    mock_resp = MagicMock()
    mock_resp.data = [
        MockAnthropicModel("claude-3-5-haiku-20241022", "Claude 3.5 Haiku"),
        MockAnthropicModel("claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet"),
    ]

    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(return_value=mock_resp)

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        await registry.refresh_models("anthropic", force=True)

    models = registry.get_models("anthropic")
    assert len(models) == 2
    assert any(m["id"] == "claude-3-5-haiku-20241022" for m in models)
    assert any(m["id"] == "claude-3-5-sonnet-20241022" for m in models)

