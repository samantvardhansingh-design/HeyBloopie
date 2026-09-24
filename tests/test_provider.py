"""Unit and integration tests for the HeyBloopie Provider Abstraction Layer (Part 1).

Tests cover:
- Mock each provider's SDK and verify generate() returns text.
- Mock each provider's SDK and verify stream() yields chunks.
- Test that is_available() returns False when no key is stored.
- Test that ProviderFactory only lists providers with keys configured.
- Test that keys are never written to a file (inspect the code).
"""

import ast
import asyncio
from contextlib import asynccontextmanager
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Ensure python directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from python.provider import AIProvider, ProviderFactory
from python.providers.gemini_adapter import GeminiAdapter
from python.providers.openrouter_adapter import OpenRouterAdapter
from python.providers.openai_adapter import OpenAIAdapter
from python.providers.anthropic_adapter import AnthropicAdapter
from python.providers.ollama_adapter import OllamaAdapter


# ═══════════════════════════════════════════════════════════════════
# 1. Gemini Adapter Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_gemini_generate_and_stream(monkeypatch):
    """Mock Gemini google.genai SDK and verify generate() returns text and stream() yields chunks."""
    monkeypatch.setattr("keyring.get_password", lambda service, user: "fake-gemini-key")

    mock_client = MagicMock()

    # Non-stream
    mock_res = MagicMock()
    mock_res.text = "Gemini generated text"
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_res)

    # Stream
    async def mock_async_stream():
        for text in ["chunk1 ", "chunk2"]:
            yield MagicMock(text=text)

    mock_client.aio.models.generate_content_stream = AsyncMock(return_value=mock_async_stream())

    monkeypatch.setattr("google.genai.Client", lambda **kwargs: mock_client)

    adapter = GeminiAdapter()
    result = await adapter.generate("Hello Gemini")
    assert result == "Gemini generated text"

    chunks = []
    async for chunk in adapter.stream("Stream prompt"):
        chunks.append(chunk)

    assert chunks == ["chunk1 ", "chunk2"]
    assert adapter.get_model_info()["provider"] == "gemini"


# ═══════════════════════════════════════════════════════════════════
# 2. OpenRouter Adapter Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_openrouter_generate_and_stream(monkeypatch):
    """Mock OpenRouter SDK and verify generate() returns text and stream() yields chunks."""
    monkeypatch.setattr("keyring.get_password", lambda service, user: "fake-openrouter-key")

    mock_client = MagicMock()

    # Non-stream
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "OpenRouter response"
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    monkeypatch.setattr("python.providers.openrouter_adapter.AsyncOpenAI", lambda **kwargs: mock_client)

    adapter = OpenRouterAdapter()
    result = await adapter.generate("Hello OpenRouter")
    assert result == "OpenRouter response"

    # Stream
    async def mock_stream():
        for t in ["Open", "Router", " stream"]:
            c = MagicMock()
            c.choices = [MagicMock(delta=MagicMock(content=t))]
            yield c

    mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())

    chunks = []
    async for chunk in adapter.stream("Stream prompt"):
        chunks.append(chunk)

    assert chunks == ["Open", "Router", " stream"]
    assert adapter.get_model_info()["provider"] == "openrouter"


# ═══════════════════════════════════════════════════════════════════
# 3. OpenAI Adapter Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_openai_generate_and_stream(monkeypatch):
    """Mock OpenAI SDK and verify generate() returns text and stream() yields chunks."""
    monkeypatch.setattr("keyring.get_password", lambda service, user: "fake-openai-key")

    mock_client = MagicMock()

    # Non-stream
    mock_resp = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "OpenAI response"
    mock_resp.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_resp)

    monkeypatch.setattr("python.providers.openai_adapter.AsyncOpenAI", lambda **kwargs: mock_client)

    adapter = OpenAIAdapter()
    result = await adapter.generate("Hello OpenAI")
    assert result == "OpenAI response"

    # Stream
    async def mock_stream():
        for t in ["Open", "AI", " chunk"]:
            c = MagicMock()
            c.choices = [MagicMock(delta=MagicMock(content=t))]
            yield c

    mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())

    chunks = []
    async for chunk in adapter.stream("Stream prompt"):
        chunks.append(chunk)

    assert chunks == ["Open", "AI", " chunk"]
    assert adapter.get_model_info()["provider"] == "openai"


# ═══════════════════════════════════════════════════════════════════
# 4. Anthropic Adapter Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_anthropic_generate_and_stream(monkeypatch):
    """Mock Anthropic SDK and verify generate() returns text and stream() yields chunks."""
    monkeypatch.setattr("keyring.get_password", lambda service, user: "fake-anthropic-key")

    mock_client = MagicMock()

    # Non-stream
    mock_resp = MagicMock()
    mock_block = MagicMock()
    mock_block.text = "Anthropic response"
    mock_resp.content = [mock_block]
    mock_client.messages.create = AsyncMock(return_value=mock_resp)

    # Stream context manager
    @asynccontextmanager
    async def mock_stream_cm(*args, **kwargs):
        class StreamHandler:
            async def text_stream(self):
                for chunk in ["Claude", " stream", " output"]:
                    yield chunk

            def __aiter__(self):
                return self.text_stream()

        sh = StreamHandler()
        sh.text_stream = sh.text_stream()
        yield sh

    mock_client.messages.stream = mock_stream_cm

    monkeypatch.setattr("python.providers.anthropic_adapter.AsyncAnthropic", lambda **kwargs: mock_client)

    adapter = AnthropicAdapter()
    result = await adapter.generate("Hello Claude")
    assert result == "Anthropic response"

    chunks = []
    async for chunk in adapter.stream("Stream prompt"):
        chunks.append(chunk)

    assert chunks == ["Claude", " stream", " output"]
    assert adapter.get_model_info()["provider"] == "anthropic"


# ═══════════════════════════════════════════════════════════════════
# 5. Ollama Adapter Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_ollama_generate_and_stream(monkeypatch):
    """Mock Ollama local server calls and verify generate() returns text and stream() yields chunks."""
    adapter = OllamaAdapter()

    # Mock list_models to return llama3.2
    monkeypatch.setattr(adapter, "list_models", AsyncMock(return_value=["llama3.2:latest"]))

    # Mock httpx.AsyncClient.post for generate
    mock_post_resp = MagicMock()
    mock_post_resp.json.return_value = {"response": "Ollama response"}
    mock_post_resp.raise_for_status = MagicMock()

    # Mock httpx.AsyncClient.stream for stream
    @asynccontextmanager
    async def mock_stream_cm(*args, **kwargs):
        class MockStreamResp:
            def raise_for_status(self):
                pass

            async def aiter_lines(self):
                yield '{"response": "Ollama "}'
                yield '{"response": "streaming"}'

        yield MockStreamResp()

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_post_resp)
    mock_client.stream = mock_stream_cm

    @asynccontextmanager
    async def mock_async_client(*args, **kwargs):
        yield mock_client

    monkeypatch.setattr("httpx.AsyncClient", mock_async_client)

    result = await adapter.generate("Hello Ollama")
    assert result == "Ollama response"

    chunks = []
    async for chunk in adapter.stream("Stream prompt"):
        chunks.append(chunk)

    assert chunks == ["Ollama ", "streaming"]
    assert adapter.get_model_info()["provider"] == "ollama"


# ═══════════════════════════════════════════════════════════════════
# 6. is_available() Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_is_available_returns_false_when_no_key_stored(monkeypatch):
    """Test that is_available() returns False when no key is stored in keyring."""
    monkeypatch.setattr("keyring.get_password", lambda service, user: None)

    assert await GeminiAdapter().is_available() is False
    assert await OpenRouterAdapter().is_available() is False
    assert await OpenAIAdapter().is_available() is False
    assert await AnthropicAdapter().is_available() is False

    # Ollama returns False when server cannot be reached
    @asynccontextmanager
    async def mock_fail_client(*args, **kwargs):
        class FailClient:
            async def get(self, *a, **kw):
                raise ConnectionRefusedError("Ollama not running")
        yield FailClient()

    monkeypatch.setattr("httpx.AsyncClient", mock_fail_client)
    assert await OllamaAdapter().is_available() is False


# ═══════════════════════════════════════════════════════════════════
# 7. ProviderFactory Key Constraints Tests
# ═══════════════════════════════════════════════════════════════════

def test_provider_factory_only_lists_providers_with_keys_configured(monkeypatch):
    """Test that ProviderFactory only lists and instantiates providers with keys configured."""
    key_store = {}

    def mock_get_password(service, user):
        if service == "heybloopie":
            return key_store.get(user)
        return None

    monkeypatch.setattr("keyring.get_password", mock_get_password)

    # 1. No keys configured
    assert ProviderFactory.list_available_providers() == []

    # Attempting to get provider without key configured must raise ValueError
    with pytest.raises(ValueError, match="no key configured"):
        ProviderFactory.get_provider("gemini")

    with pytest.raises(ValueError, match="no key configured"):
        ProviderFactory.get_provider("openai")

    with pytest.raises(ValueError, match="no key configured"):
        ProviderFactory.get_provider("openrouter")

    with pytest.raises(ValueError, match="no key configured"):
        ProviderFactory.get_provider("anthropic")

    # 2. Configure key for Gemini and OpenAI
    key_store["gemini"] = "gemini-secret-key"
    key_store["openai"] = "openai-secret-key"

    available = ProviderFactory.list_available_providers()
    assert set(available) == {"gemini", "openai"}

    # Instantiating configured providers succeeds
    gemini_prov = ProviderFactory.get_provider("gemini")
    assert isinstance(gemini_prov, GeminiAdapter)

    openai_prov = ProviderFactory.get_provider("openai")
    assert isinstance(openai_prov, OpenAIAdapter)

    # OpenRouter still has no key, so it must still raise
    with pytest.raises(ValueError, match="no key configured"):
        ProviderFactory.get_provider("openrouter")


# ═══════════════════════════════════════════════════════════════════
# 8. Security Audit: Keys Never Written to Disk
# ═══════════════════════════════════════════════════════════════════

def test_keys_are_never_written_to_a_file():
    """Inspect python/provider.py and all python/providers/*.py to verify keys are never written to file."""
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "python"))
    files_to_check = [
        os.path.join(base_dir, "provider.py"),
        os.path.join(base_dir, "providers", "gemini_adapter.py"),
        os.path.join(base_dir, "providers", "openrouter_adapter.py"),
        os.path.join(base_dir, "providers", "openai_adapter.py"),
        os.path.join(base_dir, "providers", "anthropic_adapter.py"),
        os.path.join(base_dir, "providers", "ollama_adapter.py"),
    ]

    for file_path in files_to_check:
        assert os.path.exists(file_path), f"File {file_path} does not exist"
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()

        tree = ast.parse(code)
        for node in ast.walk(tree):
            # Check for file opening in write/append mode
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "open":
                    for arg in node.args[1:]:
                        if isinstance(arg, ast.Constant) and any(m in str(arg.value) for m in ["w", "a", "+"]):
                            raise AssertionError(f"Illegal file write operation found in {file_path}")
                # Check for Path.write_text or write_bytes
                if isinstance(node.func, ast.Attribute) and node.func.attr in ("write_text", "write_bytes"):
                    raise AssertionError(f"Illegal Path write operation found in {file_path}")
