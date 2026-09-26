"""Unit tests for HeyBloopie DialogueManager.

Verifies:
- 'who are you' returns a conversational response from the mocked LLM.
- 'find my report' returns the '[FILE_COMMAND]' token.
- 'OTHER_COMMAND' intent explains limitations conversationally.
- Short-term conversation history is maintained and limited to the last 10 turns.
- LLM prompt includes HeyBloopie's personality system prompt, history, and user input.
- JSON responses from LLM are properly parsed.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock
import pytest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from python.dialogue_manager import DialogueManager, FILE_COMMAND_TOKEN, SYSTEM_PROMPT
from python.provider import AIProvider, ProviderFactory


@pytest.fixture
def mock_provider():
    """Creates a mock AIProvider with an async generate method."""
    provider = MagicMock(spec=AIProvider)
    provider.generate = AsyncMock()
    return provider


@pytest.fixture
def mock_provider_factory(mock_provider):
    """Creates a mock ProviderFactory returning mock_provider."""
    factory = MagicMock(spec=ProviderFactory)
    factory.get_provider = MagicMock(return_value=mock_provider)
    factory.list_available_providers = MagicMock(return_value=["mock_provider"])
    return factory


@pytest.fixture
def mock_memory():
    """Creates a mock Memory instance."""
    memory = MagicMock()
    memory.get_preference = MagicMock(return_value="mock_provider")
    return memory


@pytest.mark.asyncio
async def test_who_are_you_returns_conversational_response(mock_memory, mock_provider_factory, mock_provider):
    """Test that 'who are you' returns a conversational response."""
    conversational_reply = (
        "I am HeyBloopie, a professional, calm, and capable desktop executive. "
        "I'm here to assist you with finding, organizing, and managing your files."
    )
    mock_provider.generate.return_value = conversational_reply

    dm = DialogueManager(memory=mock_memory, provider_factory=mock_provider_factory)
    result = await dm.process("who are you")

    assert result == conversational_reply
    assert result != FILE_COMMAND_TOKEN
    assert "HeyBloopie" in result

    # Check conversation history has 2 entries (user and assistant)
    assert len(dm.history) == 2
    assert dm.history[0] == {"role": "user", "content": "who are you"}
    assert dm.history[1] == {"role": "assistant", "content": conversational_reply}


@pytest.mark.asyncio
async def test_find_my_report_returns_file_command_token(mock_memory, mock_provider_factory, mock_provider):
    """Test that 'find my report' returns the '[FILE_COMMAND]' token."""
    mock_provider.generate.return_value = "[FILE_COMMAND]"

    dm = DialogueManager(memory=mock_memory, provider_factory=mock_provider_factory)
    result = await dm.process("find my report")

    assert result == FILE_COMMAND_TOKEN
    assert len(dm.history) == 2
    assert dm.history[0] == {"role": "user", "content": "find my report"}
    assert dm.history[1] == {"role": "assistant", "content": FILE_COMMAND_TOKEN}


@pytest.mark.asyncio
async def test_prompt_includes_personality_and_history(mock_memory, mock_provider_factory, mock_provider):
    """Test that prompt includes HeyBloopie personality system prompt, history, and user input."""
    mock_provider.generate.return_value = "Hello! How can I help you today?"

    dm = DialogueManager(memory=mock_memory, provider_factory=mock_provider_factory)

    # First turn
    await dm.process("Good morning")

    # Second turn
    mock_provider.generate.return_value = "I am ready to help."
    await dm.process("Can you help me?")

    # Verify the second generate call contained full context
    last_call_args = mock_provider.generate.call_args[0]
    prompt_sent = last_call_args[0]

    assert SYSTEM_PROMPT in prompt_sent
    assert "You are HeyBloopie, a professional, calm, and capable desktop executive." in prompt_sent
    assert "Good morning" in prompt_sent
    assert "Can you help me?" in prompt_sent
    assert "CONVERSATION" in prompt_sent
    assert "FILE_COMMAND" in prompt_sent
    assert "OTHER_COMMAND" in prompt_sent


@pytest.mark.asyncio
async def test_other_command_explains_limitations(mock_memory, mock_provider_factory, mock_provider):
    """Test that OTHER_COMMAND returns a conversational limitation response."""
    limitation_reply = "I can't send emails yet, but I'm learning. I'm currently focused on file management."
    mock_provider.generate.return_value = limitation_reply

    dm = DialogueManager(memory=mock_memory, provider_factory=mock_provider_factory)
    result = await dm.process("send an email to my manager")

    assert result == limitation_reply
    assert result != FILE_COMMAND_TOKEN
    assert dm.history[-1] == {"role": "assistant", "content": limitation_reply}


@pytest.mark.asyncio
async def test_history_limited_to_last_10_turns(mock_memory, mock_provider_factory, mock_provider):
    """Test that short-term conversation history is limited to the last 10 turns."""
    mock_provider.generate.return_value = "Acknowledged."

    dm = DialogueManager(memory=mock_memory, provider_factory=mock_provider_factory, max_turns=10)

    # Send 8 interactions (each interaction adds 2 entries: user + assistant = 16 entries total)
    for i in range(8):
        await dm.process(f"Message {i}")

    # History should be capped at 10 items
    assert len(dm.history) == 10
    # Oldest entries (Message 0, 1, 2) should have been trimmed out
    contents = [entry["content"] for entry in dm.history]
    assert "Message 0" not in contents
    assert "Message 7" in contents


@pytest.mark.asyncio
async def test_json_formatted_llm_responses(mock_memory, mock_provider_factory, mock_provider):
    """Test that JSON-formatted responses from the LLM are handled properly."""
    dm = DialogueManager(memory=mock_memory, provider_factory=mock_provider_factory)

    # JSON for FILE_COMMAND
    mock_provider.generate.return_value = '{"intent": "FILE_COMMAND"}'
    res1 = await dm.process("organize my desktop")
    assert res1 == FILE_COMMAND_TOKEN

    # JSON for CONVERSATION
    mock_provider.generate.return_value = '{"intent": "CONVERSATION", "response": "I am feeling great today!"}'
    res2 = await dm.process("how are you doing?")
    assert res2 == "I am feeling great today!"

    # JSON for OTHER_COMMAND with fallback
    mock_provider.generate.return_value = '{"intent": "OTHER_COMMAND"}'
    res3 = await dm.process("play spotify")
    assert "I can't do that yet" in res3
