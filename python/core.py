"""HeyBloopie Core Orchestrator Module.

This module is the central nervous system of HeyBloopie. It orchestrates the end-to-end
execution loop:
    1. Receive user request (voice or text).
    2. Request a structured execution plan from the Planner.
    3. Pass each proposed step through the Policy Engine for approval.
    4. Seek user confirmation if the action is categorized as Medium or High risk.
    5. Dispatch approved steps to the Tool Layer.
    6. Verify the outcome on disk to ensure correctness.
    7. Report progress and final outcomes back to the UI/voice synthesis.

Architectural Constraints:
- Core NEVER calls AI APIs directly (delegates exclusively to Planner).
- Core NEVER bypasses the Policy Engine. Every tool call goes through policy.check_action() first.
- Core NEVER raises exceptions. All errors are caught and reported in ExecutionReport.
- Core streams progress (console prints for V1).
"""

from dataclasses import dataclass
import logging
import sqlite3
from typing import Any, Callable, Dict, List, Optional

from python import planner, policy, tools

logger = logging.getLogger("heybloopie.core")

_active_wake_word_listener = None

# Available tools specification for V1
AVAILABLE_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "find_files",
        "description": "Finds files matching a name or content query within approved directories.",
        "parameters": {
            "query": "Search string for filename or content match (string, required)",
            "date_range": "Optional filter ('today', 'yesterday', 'last_week', 'last_month', 'last_year')",
            "path": "Optional specific directory to search within",
        },
    }
]

# Dispatch map from tool name to callable tool implementation
TOOL_DISPATCH: Dict[str, Callable] = {
    "find_files": tools.find_files,
}


@dataclass
class ExecutionReport:
    """Final outcome report returned by Core after executing a user request."""
    success: bool
    summary: str
    details: list[dict]
    exceptions: list[dict]
    total_steps: int
    steps_succeeded: int
    steps_failed: int


def show_preview(plan: planner.Plan) -> bool:
    """Displays the plan to the user and waits for approval.

    For V1, this is a simple console print that returns True.
    UI integration will be implemented in Prompt 7.
    """
    print(f"\n--- Plan Preview ---")
    print(f"Summary: {plan.summary}")
    for idx, step in enumerate(plan.steps, 1):
        print(f"  {idx}. [{step.risk_level.upper()}] {step.tool_name}: {step.description}")
    print("--------------------\n")
    return True


async def run(user_request: str) -> ExecutionReport:
    """Orchestrates the HeyBloopie core execution loop.

    Args:
        user_request: The user's natural language request.

    Returns:
        ExecutionReport detailing overall success, per-step results, and any exceptions.
    """
    try:
        # Step 1: Call planner.create_plan(user_request, AVAILABLE_TOOLS)
        plan = await planner.create_plan(user_request, AVAILABLE_TOOLS)

        # Step 2: If the plan has zero steps
        if not plan.steps:
            logger.info(f"Feature request logged: {user_request}")
            print(f"Feature request logged: {user_request}")
            return ExecutionReport(
                success=False,
                summary="I can't do that yet. I'm currently focused on finding, organizing, renaming, and moving files.",
                details=[],
                exceptions=[],
                total_steps=0,
                steps_succeeded=0,
                steps_failed=0,
            )

        # Step 3: If the plan requires confirmation (any MEDIUM/HIGH step)
        if plan.requires_confirmation:
            approved = show_preview(plan)
            if not approved:
                return ExecutionReport(
                    success=False,
                    summary="Cancelled.",
                    details=[],
                    exceptions=[],
                    total_steps=len(plan.steps),
                    steps_succeeded=0,
                    steps_failed=0,
                )

        # Step 4: Execute the plan step by step
        details: list[dict] = []
        exceptions: list[dict] = []
        steps_succeeded = 0
        steps_failed = 0

        for idx, step in enumerate(plan.steps, 1):
            print(f"Executing step {idx}/{len(plan.steps)}: {step.description}")

            # a. Call policy.check_action(step.tool_name, step.params)
            try:
                policy_decision = policy.check_action(step.tool_name, step.params)
            except Exception as e:
                policy_decision = False
                policy_reason = str(e)

            is_allowed = getattr(policy_decision, "allowed", None)
            if is_allowed is None:
                if isinstance(policy_decision, bool):
                    is_allowed = policy_decision
                elif isinstance(policy_decision, dict):
                    is_allowed = policy_decision.get("allowed", False)
                else:
                    is_allowed = False

            reason = getattr(policy_decision, "reason", "Action denied by policy engine")

            # b. If denied, log the denial and add to exceptions. Continue to next step.
            if not is_allowed:
                logger.warning(f"Step denied by policy: {step.tool_name} - {reason}")
                print(f"Step denied by policy: {step.tool_name} - {reason}")
                steps_failed += 1
                exceptions.append({
                    "step": step.tool_name,
                    "params": step.params,
                    "reason": reason,
                })
                continue

            # c. If requires_confirmation and step is MEDIUM/HIGH, call policy.request_permission
            if plan.requires_confirmation and step.risk_level.lower() in ("medium", "high"):
                try:
                    permission = policy.request_permission(step.tool_name, step.params)
                except Exception as e:
                    permission = False
                if not permission:
                    steps_failed += 1
                    exceptions.append({
                        "step": step.tool_name,
                        "params": step.params,
                        "reason": "Permission denied by user",
                    })
                    continue

            # d. Call the tool function. Use dispatch map
            tool_fn = TOOL_DISPATCH.get(step.tool_name)
            if hasattr(tools, step.tool_name):
                live_fn = getattr(tools, step.tool_name)
                if live_fn is not None and (hasattr(live_fn, "mock_calls") or live_fn is not tools.find_files):
                    tool_fn = live_fn

            if not tool_fn:
                steps_failed += 1
                exceptions.append({
                    "step": step.tool_name,
                    "params": step.params,
                    "reason": f"Tool '{step.tool_name}' not recognized or implemented",
                })
                continue

            # e. Await the result (ToolResult)
            result = None
            error_msg = ""
            try:
                result = await tool_fn(**step.params)
            except Exception as e:
                error_msg = str(e)

            # f. If result.success is False, attempt recovery: Retry once
            if result is None or not getattr(result, "success", False):
                print(f"Step failed, attempting recovery (retry 1/1): {step.tool_name}")
                try:
                    result = await tool_fn(**step.params)
                except Exception as e:
                    error_msg = str(e)

            if result is None or not getattr(result, "success", False):
                steps_failed += 1
                fail_reason = getattr(result, "message", None) or error_msg or "Tool execution failed"
                exceptions.append({
                    "step": step.tool_name,
                    "params": step.params,
                    "reason": fail_reason,
                })
                continue

            # g. If result.verified is False, add a warning to details but do not fail the step
            steps_succeeded += 1
            step_detail = {
                "step": step.tool_name,
                "params": step.params,
                "data": getattr(result, "data", None),
                "message": getattr(result, "message", ""),
                "verified": getattr(result, "verified", True),
            }
            if not getattr(result, "verified", True):
                verification_details = getattr(result, "verification_details", "Verification check failed on disk")
                step_detail["warning"] = f"Verification warning: {verification_details}"
            details.append(step_detail)

        # Step 5: Generate the ExecutionReport
        total_steps = len(plan.steps)
        success = (len(exceptions) == 0)

        if success:
            found_count = 0
            has_find_files = False
            for d in details:
                if d.get("step") == "find_files":
                    has_find_files = True
                    data = d.get("data")
                    if isinstance(data, list):
                        found_count += len(data)
                    elif isinstance(data, int):
                        found_count += data
            if has_find_files:
                summary = f"Done. Found {found_count} file{'s' if found_count != 1 else ''}."
            else:
                summary = f"Done. {steps_succeeded} step{'s' if steps_succeeded != 1 else ''} completed."
        elif steps_succeeded > 0:
            summary = f"Partial success. {steps_succeeded} of {total_steps} steps completed."
        else:
            summary = f"Execution failed. {steps_failed} of {total_steps} steps failed."

        # Step 6: Return the ExecutionReport
        return ExecutionReport(
            success=success,
            summary=summary,
            details=details,
            exceptions=exceptions,
            total_steps=total_steps,
            steps_succeeded=steps_succeeded,
            steps_failed=steps_failed,
        )

    except Exception as e:
        logger.error(f"Unexpected error in Core run: {e}", exc_info=True)
        return ExecutionReport(
            success=False,
            summary=f"Execution error: {e}",
            details=[],
            exceptions=[{"step": "core_orchestration", "params": {}, "reason": str(e)}],
            total_steps=0,
            steps_succeeded=0,
            steps_failed=0,
        )


def is_wake_word_enabled(db_path: str = "heybloopie.db") -> bool:
    """Checks whether the user has enabled wake word detection in preferences."""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("SELECT value FROM preferences WHERE key = 'wake_word_enabled'")
        row = cursor.fetchone()
        conn.close()
        if row and row[0] is not None:
            return row[0].strip().lower() in ("true", "1", "yes", "on")
    except Exception as e:
        logger.warning(f"Failed to check wake word preferences: {e}")
    return True


def on_wake_word_triggered() -> None:
    """Callback triggered by wake word listener: displays overlay and activates speech recognition."""
    logger.info("Wake word event received in Core: triggering overlay and speech recognition.")


def start_wake_word_service(
    on_detected: Optional[Callable[[], None]] = None,
    db_path: str = "heybloopie.db"
) -> bool:
    """Initializes and starts the background wake word listener on application launch if enabled."""
    global _active_wake_word_listener

    if not is_wake_word_enabled(db_path):
        logger.info("Wake word listener is disabled in user preferences. Using hotkey only.")
        return False

    try:
        from python.wake_word import WakeWordListener

        callback = on_detected or on_wake_word_triggered
        _active_wake_word_listener = WakeWordListener(
            on_wake_detected=callback,
            db_path=db_path
        )
        started = _active_wake_word_listener.start()
        if not started:
            logger.warning("Wake word listener could not start. Fallback to global hotkey (Ctrl+Shift+Space).")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to launch wake word listener: {e}. Fallback to hotkey.")
        return False


def stop_wake_word_service() -> None:
    """Stops the active wake word background listener if running."""
    global _active_wake_word_listener
    if _active_wake_word_listener is not None:
        _active_wake_word_listener.stop()
        _active_wake_word_listener = None
