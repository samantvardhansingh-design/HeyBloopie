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
    "create",
    "make",
    "mkdir",
    "new",
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


async def route_intent(user_input: str) -> str:
    """Classifies user intent into CONVERSATION, FILE_COMMAND, or OTHER using a fast keyword heuristic.

    - If the input contains greetings, "who are you", "what can you do", "hello", etc., return "CONVERSATION".
    - If the input contains "find", "organize", "move", "rename", "delete", return "FILE_COMMAND".
    - Otherwise, return "OTHER".
    """
    if not user_input or not user_input.strip():
        return INTENT_CONVERSATION

    clean = user_input.lower().strip()

    # 1. Plan reuse triggers (always file commands)
    for trigger in REUSE_TRIGGERS:
        if trigger in clean:
            return INTENT_FILE_COMMAND

    # 2. Check exact conversational regex patterns
    for pat in CONVERSATION_EXACT_PATTERNS:
        if re.search(pat, clean):
            return INTENT_CONVERSATION

    # 3. Tokenize words with regex
    words = re.findall(r"\b\w+\b", clean)
    word_set = set(words)

    # 4. Conversational phrases and greetings
    conversational_phrases = [
        "who are you",
        "what are you",
        "what is your name",
        "whats your name",
        "your name",
        "what can you do",
        "what are your capabilities",
        "how can you help",
        "help me",
        "tell me about yourself",
        "how are you",
        "tell me a joke",
        "are you an ai",
        "are you a robot",
        "are you a bot",
    ]
    for phrase in conversational_phrases:
        if phrase in clean:
            # Prioritize file commands if user explicitly requested file action + target
            has_action = bool(word_set & FILE_ACTIONS)
            has_target = bool(word_set & FILE_TARGETS) or bool(re.search(r"\.[a-zA-Z0-9]{2,4}\b", clean))
            if has_action and has_target:
                return INTENT_FILE_COMMAND
            return INTENT_CONVERSATION

    # Common greetings
    greetings = {"hello", "hi", "hey", "howdy", "sup", "greetings", "good morning", "good afternoon", "good evening", "thank you", "thanks", "bye", "goodbye"}
    if clean in greetings or any(clean.startswith(g + " ") for g in greetings) or any(clean.endswith(" " + g) for g in greetings):
        if not (word_set & {"find", "organize", "move", "rename", "delete"}):
            return INTENT_CONVERSATION

    # 5. Non-file domains (email, music, weather, alarms, etc.) -> OTHER
    if word_set & NON_FILE_KEYWORDS:
        has_file_target = bool(word_set & FILE_TARGETS) or bool(re.search(r"\.[a-zA-Z0-9]{2,4}\b", clean))
        if not has_file_target:
            return INTENT_OTHER

    # 6. Core file command action keywords requested: find, organize, move, rename, delete
    core_actions = {"find", "organize", "move", "rename", "delete", "search", "locate", "remove", "trash", "cleanup"}
    if word_set & core_actions:
        return INTENT_FILE_COMMAND

    # 6b. Creation commands: create/make/mkdir/new with folder/directory/file
    creation_actions = {"create", "make", "mkdir", "new"}
    if (word_set & creation_actions) and (
        bool(word_set & {"folder", "folders", "directory", "directories", "dir", "file", "files"})
        or bool(re.search(r"\.[a-zA-Z0-9]{2,4}\b", clean))
    ):
        return INTENT_FILE_COMMAND

    # 7. Additional file actions + targets check
    has_action = bool(word_set & FILE_ACTIONS)
    has_target = bool(word_set & FILE_TARGETS) or bool(re.search(r"\.[a-zA-Z0-9]{2,4}\b", clean))
    has_folder_target = any(
        folder in clean
        for folder in ["in downloads", "in desktop", "in documents", "from downloads", "from desktop"]
    )
    if has_action and (has_target or has_folder_target):
        return INTENT_FILE_COMMAND

    # If targets common system folder names with in/from
    if any(folder in clean for folder in ["in downloads", "in desktop", "in documents", "from downloads", "from desktop"]):
        return INTENT_FILE_COMMAND

    return INTENT_OTHER


async def route(
    user_input: str,
    context: Optional[Dict[str, Any]] = None,
    use_model: bool = False,
) -> str:
    """Backward-compatible entry point calling route_intent or optional model triage."""
    if use_model:
        model_result = await classify_with_model(user_input)
        if model_result:
            return model_result
    return await route_intent(user_input)



