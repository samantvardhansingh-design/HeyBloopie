"""HeyBloopie Planner Module.

This module is responsible for analyzing user intentions and translating them into a
structured, deterministic execution plan (a sequence of validated steps).

Architectural Constraints:
- The Planner has NO ability to execute tools or touch the file system directly.
- The Planner MUST NOT import any tool or call any tool.
- The Planner MUST NOT access the file system.
- The Planner MUST NOT call the Policy Engine. (That is the Core's job.)
- The Planner only thinks and returns a Plan.
"""

from dataclasses import dataclass
import inspect
import json
import logging
import re
from typing import Any, Dict, List, Optional

from python import provider

logger = logging.getLogger("heybloopie.planner")

# Hardcoded risk classification map
TOOL_RISK_MAP: Dict[str, str] = {
    # LOW risk tools: Read-only operations
    "find_files": "low",
    "list_folder": "low",
    "get_file_metadata": "low",
    "read_file_content": "low",
    # MEDIUM risk tools: Modifying operations
    "move_file": "medium",
    "rename_file": "medium",
    "create_folder": "medium",
    # HIGH risk tools: Destructive or irreversible operations
    "delete_file": "high",
    "overwrite_file": "high",
}


@dataclass
class PlanStep:
    """An individual atomic step in an execution plan."""
    tool_name: str
    params: dict
    risk_level: str
    description: str


@dataclass
class Plan:
    """A complete structured execution plan."""
    steps: list[PlanStep]
    summary: str
    requires_confirmation: bool


def _build_prompt(user_request: str, available_tools: list) -> str:
    """Builds the structured prompt for the LLM."""
    tools_str = json.dumps(available_tools, indent=2)
    return (
        "You are the planner for HeyBloopie, an AI desktop assistant.\n"
        "Generate a structured execution plan to fulfill the user's request.\n\n"
        f"User Request: {user_request}\n\n"
        f"Available Tools:\n{tools_str}\n\n"
        "Instructions:\n"
        "- Return ONLY a valid JSON object, without any markdown formatting, prose, or commentary.\n"
        "- If the user's request cannot be addressed with the available tools, return an empty steps list with an explanation in summary.\n"
        "- The JSON must strictly adhere to the following schema:\n"
        "{\n"
        '  "steps": [\n'
        '    {\n'
        '      "tool_name": "string",\n'
        '      "params": {},\n'
        '      "description": "human-readable description of the step"\n'
        '    }\n'
        '  ],\n'
        '  "summary": "one-sentence summary of the whole plan"\n'
        "}\n"
    )


def _parse_json_response(raw_text: str) -> Optional[dict]:
    """Extracts and parses a JSON dictionary from LLM response text."""
    if not raw_text or not isinstance(raw_text, str):
        return None

    clean_text = raw_text.strip()

    # Strip markdown code block fences if present
    if clean_text.startswith("```"):
        lines = clean_text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        clean_text = "\n".join(lines).strip()

    try:
        data = json.loads(clean_text)
        if isinstance(data, dict) and "steps" in data:
            return data
    except Exception:
        pass

    # Fallback: attempt to find the outermost JSON object via regex
    match = re.search(r"\{.*\}", clean_text, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict) and "steps" in data:
                return data
        except Exception:
            pass

    return None


async def create_plan(
    user_request: str,
    available_tools: Optional[list] = None,
    model: Optional[str] = None,
) -> Plan:
    """Receives a user request and returns a structured plan without executing anything.

    Args:
        user_request: The user's natural language request.
        available_tools: List of available tool descriptions and parameters.
        model: Optional model ID to route the planning prompt to.

    Returns:
        A Plan containing PlanSteps, a summary, and whether confirmation is required.
    """
    tools_list = available_tools if available_tools is not None else []
    prompt = _build_prompt(user_request, tools_list)
    options = {"model": model} if model else None

    parsed: Optional[dict] = None

    def _is_fallback_error(e: Exception) -> bool:
        err_str = str(e).lower()
        type_name = type(e).__name__.lower()
        return any(
            kw in err_str or kw in type_name
            for kw in [
                "rate", "limit", "429", "quota", "exhausted",
                "unavailable", "503", "connection", "connect", "timeout", "offline", "overloaded"
            ]
        )

    async def _call_generate_plan(prompt_str: str) -> str:
        sig = inspect.signature(provider.generate_plan)
        if "options" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            return await provider.generate_plan(prompt_str, options=options)
        elif options and len(sig.parameters) >= 2:
            return await provider.generate_plan(prompt_str, options)
        return await provider.generate_plan(prompt_str)

    # Step 1 & 2: Call provider.generate_plan
    try:
        raw_response = await _call_generate_plan(prompt)
        parsed = _parse_json_response(raw_response)
    except Exception as e:
        if _is_fallback_error(e):
            raise
        logger.warning(f"Initial plan generation or parsing failed: {e}")
        parsed = None

    # Step 3: If parsing fails, retry once
    if parsed is None:
        try:
            raw_response = await _call_generate_plan(prompt)
            parsed = _parse_json_response(raw_response)
        except Exception as e:
            if _is_fallback_error(e):
                raise
            logger.warning(f"Retry plan generation or parsing failed: {e}")
            parsed = None

    # If it fails again, return empty Plan with standard fallback summary
    if parsed is None:
        return Plan(
            steps=[],
            summary="I couldn't understand that request.",
            requires_confirmation=False,
        )

    # Step 4: Classify each step's risk level using hardcoded map
    raw_steps = parsed.get("steps", [])
    summary = parsed.get("summary", "")
    if not summary and not raw_steps:
        summary = "No steps to perform."

    plan_steps: list[PlanStep] = []
    for step_data in raw_steps:
        tool_name = step_data.get("tool_name", "")
        params = step_data.get("params", {})
        description = step_data.get("description", "")
        risk_level = TOOL_RISK_MAP.get(tool_name, "high")

        plan_steps.append(
            PlanStep(
                tool_name=tool_name,
                params=params,
                risk_level=risk_level,
                description=description,
            )
        )

    # Step 5: Set requires_confirmation = True if any step is MEDIUM or HIGH
    requires_confirmation = any(
        step.risk_level in ("medium", "high") for step in plan_steps
    )

    # Step 6: Return the Plan
    return Plan(
        steps=plan_steps,
        summary=summary,
        requires_confirmation=requires_confirmation,
    )
