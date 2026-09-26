"""HeyBloopie Dialogue Manager.

Provides conversational intelligence, short-term context memory, and intent
classification so HeyBloopie acts as a calm, capable, conversational desktop executive
rather than just a mechanical command executor.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from python.memory import Memory
from python.provider import AIProvider, ProviderFactory

logger = logging.getLogger("heybloopie.dialogue_manager")

SYSTEM_PROMPT = (
    "You are HeyBloopie, a professional, calm, and capable desktop executive. "
    "You help users manage files. You are conversational and helpful. You never sound like a robot."
)

FILE_COMMAND_TOKEN = "[FILE_COMMAND]"


class DialogueManager:
    """Manages conversational session context, persona, and intent classification."""

    SYSTEM_PROMPT: str = SYSTEM_PROMPT
    FILE_COMMAND_TOKEN: str = FILE_COMMAND_TOKEN

    def __init__(
        self,
        memory: Optional[Memory] = None,
        provider_factory: Optional[ProviderFactory] = None,
        max_turns: int = 10,
    ):
        """Initializes the DialogueManager with memory and provider factory.

        Args:
            memory: Instance of Memory (persistence layer).
            provider_factory: Instance of ProviderFactory (LLM provider management).
            max_turns: Maximum conversation turns to retain in session history (default: 10).
        """
        self.memory = memory
        self.provider_factory = provider_factory
        self.max_turns = max_turns
        self.history: List[Dict[str, str]] = []

    def _trim_history(self) -> None:
        """Limits conversation history to the last `max_turns` entries."""
        if len(self.history) > self.max_turns:
            self.history = self.history[-self.max_turns :]

    def _get_provider(self) -> Optional[AIProvider]:
        """Resolves the active AIProvider from provider_factory or memory preferences."""
        if self.provider_factory is None:
            return None

        # Directly an AIProvider instance or duck-typed provider with generate()
        if hasattr(self.provider_factory, "generate") and callable(getattr(self.provider_factory, "generate")):
            return self.provider_factory

        # ProviderFactory instance or class
        if hasattr(self.provider_factory, "get_provider"):
            # Check preferred provider in memory
            active_prov = None
            if self.memory and hasattr(self.memory, "get_preference"):
                try:
                    active_prov = self.memory.get_preference("active_provider")
                except Exception as e:
                    logger.debug(f"Failed to read active_provider preference: {e}")

            if active_prov:
                try:
                    return self.provider_factory.get_provider(active_prov)
                except Exception as e:
                    logger.debug(f"Could not instantiate preferred provider '{active_prov}': {e}")

            # Try available providers with keys configured
            if hasattr(self.provider_factory, "list_available_providers"):
                try:
                    available = self.provider_factory.list_available_providers()
                    if available:
                        return self.provider_factory.get_provider(available[0])
                except Exception as e:
                    logger.debug(f"Could not instantiate available provider: {e}")

            # Fallbacks
            for candidate in ["gemini", "openai", "openrouter", "anthropic", "ollama"]:
                try:
                    return self.provider_factory.get_provider(candidate)
                except Exception:
                    continue

        return None

    def _build_prompt(self, user_input: str) -> str:
        """Builds a minimal, low-latency prompt for the LLM to minimize time-to-first-token.

        Args:
            user_input: The current user message.

        Returns:
            A concise prompt formatted with persona, recent context, and classification schema.
        """
        # Limit history context in prompt to last 4 turns to keep prompt small and fast
        recent = self.history[-4:] if self.history else []
        history_lines = [f"{t.get('role', 'user')}: {t.get('content', '')}" for t in recent]
        history_str = "\n".join(history_lines)
        history_part = f"\nHistory:\n{history_str}\n" if history_str else "\n"

        return (
            f"{self.SYSTEM_PROMPT}{history_part}"
            f"User: {user_input}\n"
            f"Intent: CONVERSATION (reply concisely in 1-2 sentences), FILE_COMMAND (respond '{self.FILE_COMMAND_TOKEN}'), or OTHER_COMMAND (explain limit)."
        )

    def _parse_response(self, raw_text: str) -> str:
        """Parses and sanitizes the LLM response to extract the intent and clean message.

        Args:
            raw_text: Raw string returned by the AI provider.

        Returns:
            The response string or FILE_COMMAND_TOKEN.
        """
        if not raw_text or not isinstance(raw_text, str):
            return "I'm here to help you manage your files. What can I do for you today?"

        clean_text = raw_text.strip()

        # Direct token match
        if clean_text == self.FILE_COMMAND_TOKEN or self.FILE_COMMAND_TOKEN in clean_text:
            return self.FILE_COMMAND_TOKEN

        # Check for JSON output
        unfenced = clean_text
        if unfenced.startswith("```"):
            lines = unfenced.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            unfenced = "\n".join(lines).strip()

        try:
            data = json.loads(unfenced)
            if isinstance(data, dict):
                intent = str(data.get("intent", "")).upper().strip()
                if intent == "FILE_COMMAND":
                    return self.FILE_COMMAND_TOKEN
                if intent in ("CONVERSATION", "OTHER_COMMAND"):
                    resp = data.get("response") or data.get("message") or data.get("content")
                    if resp and str(resp).strip():
                        return str(resp).strip()
                    if intent == "OTHER_COMMAND":
                        return "I can't do that yet, but I'm learning. I'm currently focused on file management."
                if "response" in data and str(data["response"]).strip():
                    return str(data["response"]).strip()
        except Exception:
            pass

        # Check for regex JSON pattern inside free text
        json_match = re.search(r"\{.*\}", clean_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if isinstance(data, dict):
                    intent = str(data.get("intent", "")).upper().strip()
                    if intent == "FILE_COMMAND":
                        return self.FILE_COMMAND_TOKEN
                    if intent in ("CONVERSATION", "OTHER_COMMAND"):
                        resp = data.get("response") or data.get("message") or data.get("content")
                        if resp and str(resp).strip():
                            return str(resp).strip()
            except Exception:
                pass

        # Check line-based output (e.g., "INTENT: FILE_COMMAND" or "INTENT: CONVERSATION\nResponse: ...")
        lines = [line.strip() for line in clean_text.splitlines() if line.strip()]
        for line in lines:
            upper_line = line.upper()
            if "INTENT:" in upper_line and "FILE_COMMAND" in upper_line:
                return self.FILE_COMMAND_TOKEN

        for idx, line in enumerate(lines):
            upper_line = line.upper()
            if upper_line.startswith("RESPONSE:"):
                resp_part = line[len("RESPONSE:") :].strip()
                remaining = [resp_part] + lines[idx + 1 :]
                return "\n".join([r for r in remaining if r]).strip()

        # Check if output is just the uppercase intent keyword
        if clean_text.upper() == "FILE_COMMAND":
            return self.FILE_COMMAND_TOKEN

        return clean_text

    @staticmethod
    def _is_provider_error(raw_response: str) -> bool:
        """Checks if the provider returned an error message string instead of a valid completion."""
        if not raw_response or not isinstance(raw_response, str):
            return True
        lower = raw_response.lower().strip()
        if (
            lower.startswith("error:")
            or lower.startswith("openai error:")
            or lower.startswith("gemini error:")
            or lower.startswith("anthropic error:")
            or lower.startswith("openrouter error:")
            or lower.startswith("ollama error:")
        ):
            return True
        if any(
            k in lower
            for k in [
                "insufficient_quota",
                "credit_balance_exhausted",
                "quota exceeded",
                "rate limit",
                "api key is not configured",
            ]
        ):
            return True
        return False

    DEFAULT_CONVERSATIONAL_MAX_TOKENS = 120

    async def process(self, user_input: str, max_tokens: int = DEFAULT_CONVERSATIONAL_MAX_TOKENS) -> str:
        """Processes user input through conversational context and intent classification.

        Steps:
            1. Appends user input to the short-term conversation history.
            2. Trims history to the last `max_turns` entries.
            3. Constructs concise prompt with HeyBloopie personality and context.
            4. Calls the LLM via provider with max_tokens limit.
            5. Evaluates intent and parses response.
            6. Appends the assistant's response to the conversation history.
            7. Trims history to the last `max_turns` entries.
            8. Returns the final response string.

        Args:
            user_input: Natural language string from the user.
            max_tokens: Maximum tokens for conversational output (default 120, between 100-150).

        Returns:
            Assistant response string or FILE_COMMAND_TOKEN.
        """
        # Step 2a: Add user's input to conversation history
        self.history.append({"role": "user", "content": user_input})
        self._trim_history()

        # Step 2b: Build prompt for the LLM
        prompt = self._build_prompt(user_input)

        # Get AI provider
        provider = self._get_provider()

        response: Optional[str] = None
        if provider is not None:
            try:
                options = {"max_tokens": max_tokens}
                raw_response = await provider.generate(prompt, options=options)
                if self._is_provider_error(raw_response):
                    logger.warning(f"AIProvider returned error message: {raw_response}")
                    response = None
                else:
                    response = self._parse_response(raw_response)
            except Exception as e:
                logger.error(f"Error invoking AIProvider in DialogueManager: {e}")
                response = None

        if response is None:
            # Fallback when provider is not configured or failed
            req_lower = user_input.lower().strip()
            conversational_starters = [
                "who are you",
                "what are you",
                "your name",
                "hello",
                "hi",
                "hey",
                "how are you",
                "good morning",
                "good evening",
                "good afternoon",
                "thank",
                "thanks",
                "what can you do",
            ]
            if any(q in req_lower for q in conversational_starters):
                response = (
                    "I am HeyBloopie, a professional, calm, and capable desktop executive. "
                    "I help you manage, find, and organize your files."
                )
            else:
                response = self.FILE_COMMAND_TOKEN

        # Step 3: Add assistant's response to conversation history
        self.history.append({"role": "assistant", "content": response})
        self._trim_history()

        # Step 4: Return the response string
        return response
