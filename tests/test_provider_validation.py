"""Tests for Provider API Key Validation and Ollama detection (Part 2).

Tests cover:
- Invalid key format error for each provider.
- Key rejected error.
- Quota exhausted error.
- Network/internet unreachable error.
- Provider outage (5xx) error.
- Successful validation sets keyring and active_provider preference.
- check_ollama returns detected state and models.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Ensure python directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from python import memory, provider
from python.provider import check_ollama, validate_provider_key


@pytest.fixture
def mock_keyring_and_memory(monkeypatch, tmp_path):
    """Sets up in-memory keyring dict and temp SQLite memory for testing."""
    key_store = {}
    monkeypatch.setattr("keyring.set_password", lambda svc, u, pwd: key_store.update({u: pwd}))
    monkeypatch.setattr("keyring.get_password", lambda svc, u: key_store.get(u))

    db_file = str(tmp_path / "test_val.db")
    test_mem = memory.Memory(db_path=db_file)
    monkeypatch.setattr(memory, "_default_memory", test_mem)
    monkeypatch.setattr(memory, "get_memory", lambda *a, **k: test_mem)
    yield key_store, test_mem
    test_mem.close()


# ═══════════════════════════════════════════════════════════════════
# 1. Invalid Key Format Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_validate_provider_key_format_errors():
    """Verify exact invalid format message for each provider."""
    # Gemini requires AIzaSy
    res_gemini = await validate_provider_key("gemini", "bad_gemini_key")
    assert res_gemini["success"] is False
    assert res_gemini["error"] == (
        "That doesn't look like a valid key. Make sure you copied the full key. It usually starts with AIzaSy."
    )

    # OpenAI requires sk-
    res_openai = await validate_provider_key("openai", "bad_openai_key")
    assert res_openai["success"] is False
    assert res_openai["error"] == (
        "That doesn't look like a valid key. Make sure you copied the full key. It usually starts with sk-."
    )

    # Anthropic requires sk-ant-
    res_anthropic = await validate_provider_key("anthropic", "sk-wrong-key")
    assert res_anthropic["success"] is False
    assert res_anthropic["error"] == (
        "That doesn't look like a valid key. Make sure you copied the full key. It usually starts with sk-ant-."
    )

    # OpenRouter requires sk-or-
    res_or = await validate_provider_key("openrouter", "sk-bad-key")
    assert res_or["success"] is False
    assert res_or["error"] == (
        "That doesn't look like a valid key. Make sure you copied the full key. It usually starts with sk-or-."
    )


# ═══════════════════════════════════════════════════════════════════
# 2. Key Rejected Tests (401 / AuthenticationError)
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_validate_provider_key_rejected(monkeypatch):
    """Verify exact key rejected message when provider API returns 401."""
    # Mock Gemini rejected
    mock_client = MagicMock()
    mock_client.aio.models.get = AsyncMock(side_effect=Exception("API_KEY_INVALID: 401 Unauthorized"))
    monkeypatch.setattr("google.genai.Client", lambda **kw: mock_client)

    res = await validate_provider_key("gemini", "AIzaSyFakeKey123")
    assert res["success"] is False
    assert res["error"] == "Gemini didn't recognize this key. It may have been deleted or copied incorrectly."


# ═══════════════════════════════════════════════════════════════════
# 3. Quota Exhausted Tests (429 / RESOURCE_EXHAUSTED)
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_validate_provider_key_quota_exhausted(monkeypatch):
    """Verify exact no quota message when account limit is exceeded."""
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(side_effect=Exception("429 RESOURCE_EXHAUSTED: quota exceeded"))
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kw: mock_client)

    res = await validate_provider_key("openai", "sk-validPrefixKey123")
    assert res["success"] is False
    assert res["error"] == "Your key works, but your account has no quota left."


# ═══════════════════════════════════════════════════════════════════
# 4. Connection / No Internet Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_validate_provider_key_no_internet(monkeypatch):
    """Verify exact no internet message when connection fails."""
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(side_effect=ConnectionError("Failed to resolve host or connect"))
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: mock_client)

    res = await validate_provider_key("anthropic", "sk-ant-validKey123")
    assert res["success"] is False
    assert res["error"] == "I can't reach Anthropic. Check your internet connection."


# ═══════════════════════════════════════════════════════════════════
# 5. Provider Outage Tests (500 / 503)
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_validate_provider_key_outage(monkeypatch):
    """Verify exact provider outage message on 5xx server errors."""
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(side_effect=Exception("503 Service Unavailable: overloaded"))
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kw: mock_client)

    res = await validate_provider_key("openrouter", "sk-or-validKey123")
    assert res["success"] is False
    assert res["error"] == "OpenRouter's servers are not responding right now."


# ═══════════════════════════════════════════════════════════════════
# 6. Successful Validation Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_validate_provider_key_success(mock_keyring_and_memory, monkeypatch):
    """Verify successful validation saves key to keyring and active_provider to preferences."""
    key_store, test_mem = mock_keyring_and_memory

    mock_client = MagicMock()
    mock_client.aio.models.get = AsyncMock(return_value={"name": "models/gemini-2.5-flash-lite"})
    monkeypatch.setattr("google.genai.Client", lambda **kw: mock_client)

    res = await validate_provider_key("gemini", "AIzaSyWorkingValidKey999")
    assert res["success"] is True
    assert res["provider"] == "gemini"

    # Key is stored in keyring
    assert key_store.get("gemini") == "AIzaSyWorkingValidKey999"

    # Active provider preference is updated in SQLite memory
    assert test_mem.get_preference("active_provider") == "gemini"


# ═══════════════════════════════════════════════════════════════════
# 7. Ollama Detection Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_check_ollama_detected(mock_keyring_and_memory, monkeypatch):
    """Verify check_ollama returns models and updates active_provider when running."""
    _, test_mem = mock_keyring_and_memory

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "models": [{"name": "llama3.2:latest"}, {"name": "nomic-embed-text:latest"}]
    }

    mock_http_client = MagicMock()
    mock_http_client.get = AsyncMock(return_value=mock_resp)

    class MockAsyncClientCM:
        async def __aenter__(self):
            return mock_http_client
        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: MockAsyncClientCM())

    res = await check_ollama()
    assert res["success"] is True
    assert res["detected"] is True
    assert res["models"] == ["llama3.2:latest", "nomic-embed-text:latest"]
    assert test_mem.get_preference("active_provider") == "ollama"


@pytest.mark.asyncio
async def test_check_ollama_not_detected(monkeypatch):
    """Verify check_ollama returns detected=False when server is down."""
    class MockFailCM:
        async def __aenter__(self):
            raise ConnectionRefusedError("Connection refused on port 11434")
        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: MockFailCM())

    res = await check_ollama()
    assert res["success"] is False
    assert res["detected"] is False
    assert res["models"] == []
    assert "not detected" in res["error"]
