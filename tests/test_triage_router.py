"""Unit and integration tests for the HeyBloopie Triage Router.

Tests cover:
1. Fast intent classification for CONVERSATION queries (greetings, identity, capabilities, small talk).
2. Fast intent classification for FILE_COMMAND queries (find, delete, organize, rename, move, plan reuse).
3. Fast intent classification for OTHER queries (email, music, weather, alarms, general tasks).
4. Integration with Core:
   - CONVERSATION routes directly to conversational pipeline (streaming TTS) without calling planner.
   - FILE_COMMAND routes directly to planner and tool orchestrator.
   - OTHER routes to generic "I can't do that yet" response without calling planner.
"""

import os
import sys
from unittest.mock import AsyncMock, MagicMock
import pytest

# Ensure python directory is accessible
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from python import core, dialogue_manager, memory, planner, provider, tools, triage_router


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "who are you",
        "Who are you?",
        "what are you",
        "what is your name",
        "tell me about yourself",
        "what can you do",
        "what are your capabilities",
        "how can you help",
        "help me",
        "hello",
        "hi",
        "hey bloopie",
        "good morning",
        "how are you",
        "tell me a joke",
        "thank you",
        "bye",
    ],
)
async def test_triage_router_classifies_conversation(query):
    """Verifies that conversational queries are classified as CONVERSATION."""
    intent = await triage_router.route(query)
    assert intent == triage_router.INTENT_CONVERSATION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "find my report",
        "search for invoices",
        "locate recent pdfs",
        "delete last screenshot",
        "delete old log",
        "remove duplicate files",
        "move photos to archive",
        "organize my downloads",
        "clean up desktop",
        "rename quarterly_report.pdf to final.pdf",
        "same as last time",
        "do it again",
        "use my usual",
        "find notes in documents",
    ],
)
async def test_triage_router_classifies_file_command(query):
    """Verifies that file management queries are classified as FILE_COMMAND."""
    intent = await triage_router.route(query)
    assert intent == triage_router.INTENT_FILE_COMMAND


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        "send an email to Alice",
        "check my unread emails",
        "play jazz music on spotify",
        "play Beatles songs",
        "what's the weather today in Seattle",
        "will it rain tomorrow",
        "set an alarm for 7am",
        "set a timer for 10 minutes",
        "book a flight to New York",
        "calculate 520 divided by 4",
        "order pizza tonight",
        "what is the stock price of Apple",
    ],
)
async def test_triage_router_classifies_other(query):
    """Verifies that unsupported non-file requests are classified as OTHER."""
    intent = await triage_router.route(query)
    assert intent == triage_router.INTENT_OTHER


@pytest.mark.asyncio
async def test_core_routes_conversation_without_planner(monkeypatch):
    """Verifies that CONVERSATION intent routes to conversational pipeline and does NOT call planner."""
    mock_planner = AsyncMock(side_effect=AssertionError("Planner should NOT be called for conversational query!"))
    monkeypatch.setattr(planner, "create_plan", mock_planner)

    mock_dm = MagicMock()
    mock_dm.process = AsyncMock(return_value="I am HeyBloopie, your desktop executive.")
    mock_dm._build_prompt = MagicMock(return_value="Prompt")
    monkeypatch.setattr(core, "get_dialogue_manager", lambda: mock_dm)

    async def fake_stream(prompt, options=None):
        yield "I am HeyBloopie, "
        yield "your desktop executive."

    monkeypatch.setattr(provider, "stream", fake_stream)

    emitted_sentences = []
    core.add_event_listener("speak-sentence", lambda s: emitted_sentences.append(s))

    try:
        report = await core.run("who are you")
        assert report.success is True
        assert "HeyBloopie" in report.summary
        assert report.total_steps == 0
        mock_planner.assert_not_called()
        assert len(emitted_sentences) > 0
    finally:
        core.clear_event_listeners()


@pytest.mark.asyncio
async def test_core_routes_conversation_fallback_when_stream_errors(monkeypatch):
    """Verifies fallback to dialogue_manager.process when provider.stream yields error."""
    mock_planner = AsyncMock(side_effect=AssertionError("Planner should NOT be called!"))
    monkeypatch.setattr(planner, "create_plan", mock_planner)

    mock_dm = MagicMock()
    mock_dm.process = AsyncMock(return_value="I am HeyBloopie, your desktop executive.")
    mock_dm._build_prompt = MagicMock(return_value="Prompt")
    monkeypatch.setattr(core, "get_dialogue_manager", lambda: mock_dm)

    async def fake_error_stream(prompt, options=None):
        yield "OpenAI stream error: Error code: 429 - insufficient_quota"

    monkeypatch.setattr(provider, "stream", fake_error_stream)

    report = await core.run("who are you")
    assert report.success is True
    assert "HeyBloopie" in report.summary
    mock_planner.assert_not_called()



@pytest.mark.asyncio
async def test_core_routes_file_command_to_planner(monkeypatch):
    """Verifies that FILE_COMMAND intent routes to planner and execution."""
    step = planner.PlanStep(
        tool_name="find_files",
        params={"query": "invoice"},
        risk_level="low",
        description="Find invoices",
    )
    plan = planner.Plan(steps=[step], summary="Find invoices", requires_confirmation=False)

    mock_planner = AsyncMock(return_value=plan)
    monkeypatch.setattr(planner, "create_plan", mock_planner)

    async def mock_find_files(**kwargs):
        return tools.ToolResult(
            success=True,
            data=[{"name": "invoice_1.pdf", "path": "C:\\docs\\invoice_1.pdf"}],
            message="Found 1 file",
            verified=True,
            verification_details="",
        )

    monkeypatch.setitem(core.TOOL_DISPATCH, "find_files", mock_find_files)

    report = await core.run("find my invoice")
    assert report.success is True
    assert report.steps_succeeded == 1
    mock_planner.assert_called_once()


@pytest.mark.asyncio
async def test_core_routes_other_to_cannot_do_yet(monkeypatch):
    """Verifies that OTHER intent routes to 'I can't do that yet' and logs feature request without planner."""
    mock_planner = AsyncMock(side_effect=AssertionError("Planner should NOT be called for OTHER queries!"))
    monkeypatch.setattr(planner, "create_plan", mock_planner)

    feature_requests = []
    monkeypatch.setattr(memory, "log_feature_request", lambda req: feature_requests.append(req))

    emitted_sentences = []
    core.add_event_listener("speak-sentence", lambda s: emitted_sentences.append(s))

    try:
        report = await core.run("send an email to Bob")
        assert report.success is False
        assert "I can't do that yet" in report.summary
        assert report.total_steps == 0
        mock_planner.assert_not_called()
        assert "send an email to Bob" in feature_requests
        assert any("I can't do that yet" in s for s in emitted_sentences)
    finally:
        core.clear_event_listeners()


def test_triage_router_default_model_is_flash_lite():
    """Verifies that the fastest, cheapest model (Gemini Flash-Lite) is default for triage."""
    assert triage_router.DEFAULT_TRIAGE_MODEL == "gemini-2.5-flash-lite"
    assert triage_router.get_triage_model() == "gemini-2.5-flash-lite"


def test_triage_router_set_model():
    """Verifies that triage model can be configured dynamically."""
    original = triage_router.get_triage_model()
    try:
        triage_router.set_triage_model("gemini-2.0-flash")
        assert triage_router.get_triage_model() == "gemini-2.0-flash"
    finally:
        triage_router.set_triage_model(original)


@pytest.mark.asyncio
async def test_classify_with_model_uses_fast_model_and_token_limit(monkeypatch):
    """Verifies that model triage calls provider with fast model and 20 max_tokens."""
    called_options = {}

    async def mock_generate(prompt, options=None):
        nonlocal called_options
        called_options = options or {}
        return "CONVERSATION"

    monkeypatch.setattr(provider, "generate", mock_generate)

    result = await triage_router.classify_with_model("how do I do this?")
    assert result == triage_router.INTENT_CONVERSATION
    assert called_options.get("model") == "gemini-2.5-flash-lite"
    assert called_options.get("max_tokens") == 20

