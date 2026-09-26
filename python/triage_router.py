"""HeyBloopie Triage Router.

Implements a fast, low-latency initial intent classifier similar to Siri's architecture.
Categorizes requests into:
    - CONVERSATION: Greetings, identity, small talk, questions about capabilities.
    - FILE_COMMAND: File searches, moving, deletion, organizing, renaming, etc.
    - OTHER: Any requests outside desktop file management.

For V1, uses an optimized, zero-latency keyword and pattern-based heuristic to avoid
an unnecessary extra LLM round-trip.
"""

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("heybloopie.triage_router")

INTENT_CONVERSATION = "CONVERSATION"
INTENT_FILE_COMMAND = "FILE_COMMAND"
INTENT_OTHER = "OTHER"

# Conversational phrases & patterns
CONVERSATION_EXACT_PATTERNS = [
    r"^who are you\??$",
    r"^what are you\??$",
    r"^what is your name\??$",
    r"^whats your name\??$",
    r"^your name\??$",
    r"^who made you\??$",
    r"^tell me about yourself\??$",
    r"^what can you do\??$",
    r"^what are your capabilities\??$",
    r"^how can you help\??$",
    r"^help me\??$",
    r"^how are you\??$",
    r"^how are you doing\??$",
    r"^how is it going\??$",
    r"^hows it going\??$",
    r"^how do you work\??$",
    r"^tell me a joke\??$",
    r"^are you an ai\??$",
    r"^are you a bot\??$",
    r"^are you a robot\??$",
    r"^(hello|hi|hey|howdy|sup|greetings)(\s+(heybloopie|bloopie|there))?[\.!\?]*$",
    r"^(good morning|good afternoon|good evening|good day)[\.!\?]*$",
    r"^(thank you|thanks|thanks a lot|thank you so much)[\.!\?]*$",
    r"^(bye|goodbye|see you|see ya|have a good day)[\.!\?]*$",
]

CONVERSATION_KEYWORDS = [
    "who are you",
    "what are you",
    "your name",
    "what can you do",
    "tell me about yourself",
    "how are you",
    "tell me a joke",
    "are you a robot",
    "are you an ai",
]

# File command action indicators
FILE_ACTIONS = {
    "find",
    "search",
    "locate",
    "show",
    "list",
    "open",
    "delete",
    "remove",
    "trash",
    "erase",
    "clean",
    "cleanup",
    "move",
    "relocate",
    "rename",
    "organize",
    "sort",
    "backup",
    "copy",
    "transfer",
    "compress",
    "zip",
    "unzip",
    "extract",
    "archive",
    "duplicate",
}

# File command target indicators
FILE_TARGETS = {
    "file",
    "files",
    "folder",
    "folders",
    "dir",
    "directory",
    "directories",
    "document",
    "documents",
    "doc",
    "docs",
    "pdf",
    "pdfs",
    "txt",
    "csv",
    "image",
    "images",
    "photo",
    "photos",
    "picture",
    "pictures",
    "video",
    "videos",
    "screenshot",
    "screenshots",
    "receipt",
    "receipts",
    "invoice",
    "invoices",
    "download",
    "downloads",
    "desktop",
    "drive",
    "path",
    "report",
    "reports",
    "log",
    "logs",
    "spreadsheet",
    "spreadsheets",
    "contract",
    "contracts",
    "presentation",
    "presentations",
    "slides",
    "notes",
}

# Plan reuse triggers (always file commands)
REUSE_TRIGGERS = [
    "same as last time",
    "do it again",
    "use my usual",
    "like before",
    "repeat last",
    "again",
    "usual",
]

NON_FILE_KEYWORDS = {
    "email",
    "mail",
    "gmail",
    "outlook",
    "message",
    "messages",
    "sms",
    "music",
    "song",
    "songs",
    "spotify",
    "playlist",
    "radio",
    "weather",
    "forecast",
    "temperature",
    "rain",
    "browser",
    "browse",
    "website",
    "web",
    "google",
    "alarm",
    "timer",
    "reminder",
    "calendar",
    "event",
    "meeting",
    "flight",
    "hotel",
    "uber",
    "taxi",
    "stock",
    "stocks",
    "crypto",
    "bitcoin",
    "calculate",
    "calculator",
    "math",
    "recipe",
    "recipes",
    "food",
    "order",
}


DEFAULT_TRIAGE_MODEL = "gemini-2.5-flash-lite"
TRIAGE_MAX_TOKENS = 20

_active_triage_model = DEFAULT_TRIAGE_MODEL


def get_triage_model() -> str:
    """Returns the configured model for fast triage classification (default: gemini-2.5-flash-lite)."""
    global _active_triage_model
    return _active_triage_model


def set_triage_model(model: str) -> None:
    """Configures the model used for fast triage classification."""
    global _active_triage_model
    _active_triage_model = model


async def classify_with_model(user_input: str, model: Optional[str] = None) -> Optional[str]:
    """Uses a lightweight, high-speed model (e.g., Gemini Flash-Lite) for triage classification.

    Restricted to a 20-token output limit to ensure sub-second response times and minimal cost.

    Args:
        user_input: The user request text.
        model: Optional model identifier override (defaults to get_triage_model()).

    Returns:
        One of 'CONVERSATION', 'FILE_COMMAND', 'OTHER', or None if unavailable/failed.
    """
    target_model = model or get_triage_model()
    prompt = (
        "Classify the user intent into exactly one category: CONVERSATION, FILE_COMMAND, or OTHER.\n"
        f"Input: {user_input}\n"
        "Category:"
    )
    try:
        from python import provider
        options = {"model": target_model, "max_tokens": TRIAGE_MAX_TOKENS}
        raw_response = await provider.generate(prompt, options=options)
        if not raw_response or not isinstance(raw_response, str):
            return None

        clean = raw_response.strip().upper()
        if "FILE_COMMAND" in clean or "[FILE_COMMAND]" in clean:
            return INTENT_FILE_COMMAND
        if "CONVERSATION" in clean:
            return INTENT_CONVERSATION
        if "OTHER" in clean:
            return INTENT_OTHER
    except Exception as e:
        logger.debug(f"Model triage classification error ({target_model}): {e}")
    return None


async def route(user_input: str, context: Optional[Dict[str, Any]] = None, use_model: bool = False) -> str:
    """Classifies user intent into CONVERSATION, FILE_COMMAND, or OTHER.

    Uses a two-tier approach:
    1. Instant heuristic check for common phrases, greetings, file actions, and targets (0ms).
    2. Fallback to fastest, cheapest model (Gemini Flash-Lite, 20 tokens) if explicitly requested
       or if heuristics are indeterminate.

    Args:
        user_input: The raw natural language input string.
        context: Optional dictionary containing session history, preferences, or metadata.
        use_model: Whether to invoke the fast triage model for classification.

    Returns:
        One of 'CONVERSATION', 'FILE_COMMAND', or 'OTHER'.
    """
    if not user_input or not user_input.strip():
        return INTENT_CONVERSATION

    clean = user_input.lower().strip()

    # 1. Check plan reuse triggers first (e.g. "same as last time", "do it again")
    for trigger in REUSE_TRIGGERS:
        if trigger in clean:
            return INTENT_FILE_COMMAND

    # 2. Check exact conversational regex patterns
    for pat in CONVERSATION_EXACT_PATTERNS:
        if re.search(pat, clean):
            return INTENT_CONVERSATION

    # 3. Tokenize words with regex (stripping punctuation)
    words = re.findall(r"\b\w+\b", clean)
    word_set = set(words)

    # 4. Check explicit non-file keywords (email, weather, music, alarms, etc.)
    if word_set & NON_FILE_KEYWORDS:
        # If user explicitly asked about files (e.g. "email_attachment.pdf" or "file"), let file logic take precedence
        has_file_target = bool(word_set & FILE_TARGETS) or bool(re.search(r"\.[a-zA-Z0-9]{2,4}\b", clean))
        if not has_file_target:
            return INTENT_OTHER

    # 5. Check conversational keywords
    for kw in CONVERSATION_KEYWORDS:
        if kw in clean:
            # If the user also explicitly asked to find/delete/organize files, prioritize file command
            has_action = bool(word_set & FILE_ACTIONS)
            has_target = bool(word_set & FILE_TARGETS)
            if has_action and has_target:
                return INTENT_FILE_COMMAND
            return INTENT_CONVERSATION

    # 6. Check File Command criteria:
    has_action = bool(word_set & FILE_ACTIONS)
    has_target = bool(word_set & FILE_TARGETS) or bool(re.search(r"\.[a-zA-Z0-9]{2,4}\b", clean))
    has_folder_target = any(
        folder in clean
        for folder in ["downloads", "desktop", "documents", "pictures", "videos", "music folder"]
    )

    if has_action and (has_target or has_folder_target):
        return INTENT_FILE_COMMAND

    # If starts with strong search/find/delete/move/organize:
    if words and words[0] in {"find", "search", "locate", "delete", "remove", "organize", "cleanup"}:
        return INTENT_FILE_COMMAND

    # If targets common system folder names with in/from
    if any(folder in clean for folder in ["in downloads", "in desktop", "in documents", "from downloads", "from desktop"]):
        return INTENT_FILE_COMMAND

    # 7. Check single-word greetings / pleasantries
    if clean in {"hi", "hello", "hey", "sup", "howdy", "thanks", "bye"}:
        return INTENT_CONVERSATION

    # 8. If requested or for ambiguous inputs, use the fastest triage model (Gemini Flash-Lite)
    if use_model:
        model_result = await classify_with_model(user_input)
        if model_result:
            return model_result

    # 9. Otherwise, it is an unsupported task outside desktop file management
    return INTENT_OTHER


