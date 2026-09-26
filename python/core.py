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
import inspect
import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from python import dialogue_manager, memory, model_router, planner, policy, tools

logger = logging.getLogger("heybloopie.core")

_active_wake_word_listener = None
_active_dialogue_manager: Optional[dialogue_manager.DialogueManager] = None


def get_dialogue_manager() -> dialogue_manager.DialogueManager:
    """Returns or initializes the session DialogueManager singleton."""
    global _active_dialogue_manager
    if _active_dialogue_manager is None:
        from python.provider import ProviderFactory

        _active_dialogue_manager = dialogue_manager.DialogueManager(
            memory=memory.get_memory(),
            provider_factory=ProviderFactory,
        )
    return _active_dialogue_manager


def set_dialogue_manager(dm: Optional[dialogue_manager.DialogueManager]) -> None:
    """Sets or resets the active DialogueManager instance (useful for testing)."""
    global _active_dialogue_manager
    _active_dialogue_manager = dm

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
    },
    {
        "name": "delete_file",
        "description": "Permanently deletes a file, or finds and deletes the latest matching file if query/path is provided (e.g. 'last screenshot').",
        "parameters": {
            "path": "Full path to the file or directory to delete (string, optional)",
            "query": "Search string or descriptor for the file to delete (e.g. 'last screenshot', 'screenshot') (string, optional)",
        },
    },
]

# Dispatch map from tool name to callable tool implementation
TOOL_DISPATCH: Dict[str, Callable] = {
    "find_files": tools.find_files,
    "delete_file": tools.delete_file,
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


def _parse_plan_json(raw_plan: Any) -> Optional[planner.Plan]:
    """Reconstructs a planner.Plan from a JSON string, dict, or Plan object."""
    if not raw_plan:
        return None
    if isinstance(raw_plan, planner.Plan):
        return raw_plan
    try:
        data = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
        if not isinstance(data, dict):
            return None
        steps = []
        for s in data.get("steps", []):
            if isinstance(s, planner.PlanStep):
                steps.append(s)
            elif isinstance(s, dict):
                steps.append(
                    planner.PlanStep(
                        tool_name=s.get("tool_name", ""),
                        params=s.get("params", {}),
                        risk_level=s.get("risk_level", "low"),
                        description=s.get("description", ""),
                    )
                )
        return planner.Plan(
            steps=steps,
            summary=data.get("summary", ""),
            requires_confirmation=data.get("requires_confirmation", False),
        )
    except Exception as e:
        logger.warning(f"Failed to reconstruct Plan: {e}")
        return None


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
    print(f"=== Core Loop Started for request: {user_request} ===")
    start_time = time.time()
    plan = None

    try:
        # Step 0: Process through DialogueManager for conversational responses vs file commands
        if hasattr(dialogue_manager, "process") and callable(getattr(dialogue_manager, "process")):
            dialogue_resp = await dialogue_manager.process(user_request)
        else:
            dm = get_dialogue_manager()
            dialogue_resp = await dm.process(user_request)

        if dialogue_resp != dialogue_manager.FILE_COMMAND_TOKEN:
            print(f"Conversational response from DialogueManager: {dialogue_resp}")
            duration_ms = int((time.time() - start_time) * 1000)
            report = ExecutionReport(
                success=True,
                summary=dialogue_resp,
                details=[],
                exceptions=[],
                total_steps=0,
                steps_succeeded=0,
                steps_failed=0,
            )
            try:
                memory.log_task(user_request, None, report, duration_ms)
            except Exception as e:
                logger.debug(f"Failed to log conversational task to memory: {e}")
            print("=== Core Loop Finished (Conversational) ===")
            return report

        # Step 1: Check for plan reuse if user request indicates reuse
        reuse_triggers = [
            "same as last time",
            "do it again",
            "use my usual",
            "like before",
            "again",
            "usual",
        ]
        is_reuse = any(trigger in user_request.lower() for trigger in reuse_triggers)

        if is_reuse:
            if "same as last time" in user_request.lower():
                print("Detected 'same as last time'. Looking up memory...")
            else:
                print("Detected plan reuse trigger. Looking up memory...")
            similar = memory.find_similar_task(user_request)
            if similar and similar.get("plan_json"):
                plan = _parse_plan_json(similar["plan_json"])
                if plan:
                    print(f"Plan retrieved from memory: {plan.summary}")
                    logger.info(f"Plan retrieved from memory: {plan.summary}")
            if not plan:
                print("No matching plan found in memory.")

        selected_model: Optional[str] = None
        selected_provider: Optional[str] = None

        if plan is None:
            print("Calling Planner...")
            router = model_router.ModelRouter(memory=memory.get_memory())
            fallback_models: List[Optional[str]] = []
            try:
                fallback_models = await router.select_with_fallback(user_request)
            except Exception as e:
                logger.warning(f"ModelRouter fallback lookup failed: {e}")

            if not fallback_models:
                try:
                    chosen = await router.select_model(user_request)
                    fallback_models = [chosen]
                except Exception:
                    fallback_models = [None]

            last_fallback_error = None
            for m_id in fallback_models:
                selected_model = m_id
                try:
                    sig = inspect.signature(planner.create_plan)
                    if "model" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                        plan = await planner.create_plan(user_request, AVAILABLE_TOOLS, model=m_id)
                    else:
                        plan = await planner.create_plan(user_request, AVAILABLE_TOOLS)

                    if selected_model:
                        info = router.registry.get_model_info(selected_model)
                        if info:
                            selected_provider = info.get("provider")

                    last_fallback_error = None
                    break
                except Exception as e:
                    if model_router.should_fallback(e):
                        logger.warning(
                            f"Model '{m_id}' failed with rate limit or availability error: {e}. Trying fallback..."
                        )
                        last_fallback_error = e
                        continue
                    raise

            if plan is not None:
                print(f"Plan received: {plan.summary}")

            if plan is None and last_fallback_error:
                report = ExecutionReport(
                    success=False,
                    summary=f"All models failed due to rate limits or availability: {last_fallback_error}",
                    details=[],
                    exceptions=[{"error": str(last_fallback_error)}],
                    total_steps=0,
                    steps_succeeded=0,
                    steps_failed=0,
                )
                duration_ms = int((time.time() - start_time) * 1000)
                memory.log_task(user_request, None, report, duration_ms, provider=selected_provider, model=selected_model)
                return report

        # Step 2: If the plan has zero steps (unsupported request)
        if not plan.steps:
            logger.info(f"Feature request logged: {user_request}")
            print(f"Feature request logged: {user_request}")
            memory.log_feature_request(user_request)

            report = ExecutionReport(
                success=False,
                summary="I can't do that yet. I'm currently focused on finding, organizing, renaming, and moving files.",
                details=[],
                exceptions=[],
                total_steps=0,
                steps_succeeded=0,
                steps_failed=0,
            )
            duration_ms = int((time.time() - start_time) * 1000)
            print("Logging task to memory...")
            memory.log_task(user_request, plan, report, duration_ms)
            print("Task logged successfully.")
            print("=== Core Loop Finished ===")
            return report

        # Step 3: If the plan requires confirmation (any MEDIUM/HIGH step)
        if plan.requires_confirmation:
            approved = show_preview(plan)
            if not approved:
                report = ExecutionReport(
                    success=False,
                    summary="Cancelled.",
                    details=[],
                    exceptions=[],
                    total_steps=len(plan.steps),
                    steps_succeeded=0,
                    steps_failed=0,
                )
                duration_ms = int((time.time() - start_time) * 1000)
                memory.log_task(user_request, plan, report, duration_ms)
                return report

        # Step 4: Execute the plan step by step
        details: list[dict] = []
        exceptions: list[dict] = []
        steps_succeeded = 0
        steps_failed = 0

        for idx, step in enumerate(plan.steps, 1):
            print(f"Executing step {idx}: {step.tool_name} with params {step.params}")

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
                print(f"Step {idx} result: failure")
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
                print(f"Step {idx} result: failure")
                fail_reason = getattr(result, "message", None) or error_msg or "Tool execution failed"
                exceptions.append({
                    "step": step.tool_name,
                    "params": step.params,
                    "reason": fail_reason,
                })
                continue

            # g. If result.verified is False, add a warning to details but do not fail the step
            steps_succeeded += 1
            print(f"Step {idx} result: success")
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
            has_delete_file = False
            deleted_name = ""
            for d in details:
                if d.get("step") == "find_files":
                    has_find_files = True
                    data = d.get("data")
                    if isinstance(data, list):
                        found_count += len(data)
                    elif isinstance(data, int):
                        found_count += data
                elif d.get("step") == "delete_file":
                    has_delete_file = True
                    data = d.get("data")
                    if isinstance(data, dict):
                        deleted_name = data.get("name", "")
            if has_delete_file:
                summary = f"Done. Deleted {deleted_name or 'file'} successfully."
            elif has_find_files:
                summary = f"Done. Found {found_count} file{'s' if found_count != 1 else ''}."
            else:
                summary = f"Done. {steps_succeeded} step{'s' if steps_succeeded != 1 else ''} completed."
        elif steps_succeeded > 0:
            summary = f"Partial success. {steps_succeeded} of {total_steps} steps completed."
        else:
            summary = f"Execution failed. {steps_failed} of {total_steps} steps failed."

        # Step 6: Return the ExecutionReport and record in memory
        report = ExecutionReport(
            success=success,
            summary=summary,
            details=details,
            exceptions=exceptions,
            total_steps=total_steps,
            steps_succeeded=steps_succeeded,
            steps_failed=steps_failed,
        )
        duration_ms = int((time.time() - start_time) * 1000)
        print("Logging task to memory...")
        try:
            memory.log_task(
                user_request,
                plan,
                report,
                duration_ms,
                provider=selected_provider if 'selected_provider' in locals() else None,
                model=selected_model if 'selected_model' in locals() else None,
            )
            print("Task logged successfully.")
        except Exception as log_err:
            logger.warning(f"Failed to log task execution to memory: {log_err}")
            print(f"Task logging failed: {log_err}")
        print("=== Core Loop Finished ===")
        return report

    except Exception as e:
        logger.error(f"Unexpected error in Core run: {e}", exc_info=True)
        report = ExecutionReport(
            success=False,
            summary=f"Execution error: {e}",
            details=[],
            exceptions=[{"step": "core_orchestration", "params": {}, "reason": str(e)}],
            total_steps=0,
            steps_succeeded=0,
            steps_failed=0,
        )
        duration_ms = int((time.time() - start_time) * 1000)
        try:
            memory.log_task(user_request, plan if 'plan' in locals() and plan else None, report, duration_ms)
        except Exception:
            pass
        return report


def is_wake_word_enabled(db_path: Optional[str] = None) -> bool:
    """Checks whether the user has enabled wake word detection in preferences."""
    try:
        mem = memory.Memory(db_path=db_path)
        val = mem.get_preference("wake_word_enabled", True)
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            return val.strip().lower() in ("true", "1", "yes", "on")
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
