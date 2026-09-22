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
- Core NEVER calls AI APIs directly (delegates exclusively to Planner and Provider Abstraction Layer).
- Core NEVER executes OS tools directly (delegates exclusively to Tool Layer via Dispatcher).
- Manages wake word service initialization on application launch based on user preferences.
"""

import logging
import sqlite3
from typing import Any, AsyncIterator, Callable, Dict, List, Optional

logger = logging.getLogger("heybloopie.core")

_active_wake_word_listener = None


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
    # Default to True for seamless voice activation if table exists
    return True


def on_wake_word_triggered() -> None:
    """Callback triggered by wake word listener: displays overlay and activates speech recognition."""
    logger.info("Wake word event received in Core: triggering overlay and speech recognition.")
    # IPC call or notification to Tauri overlay window to show and start Web Speech API


def start_wake_word_service(
    on_detected: Optional[Callable[[], None]] = None,
    db_path: str = "heybloopie.db"
) -> bool:
    """Initializes and starts the background wake word listener on application launch if enabled.

    Args:
        on_detected: Optional custom callback. Defaults to on_wake_word_triggered.
        db_path: SQLite database path for checking preferences.

    Returns:
        True if started successfully, False if disabled or fell back to hotkey.
    """
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


async def handle_user_request(request_text: str, context: Optional[Dict[str, Any]] = None) -> AsyncIterator[Dict[str, Any]]:
    """Receives a natural language request, manages the execution cycle, and streams status updates.

    Args:
        request_text: Natural language prompt spoken or typed by the user.
        context: Optional session context or environment state.

    Yields:
        Status update dictionaries containing current stage, plan details, or completion status.
    """
    pass


async def execute_plan_step(step: Dict[str, Any]) -> Dict[str, Any]:
    """Coordinates the safety check, dispatch, and verification of a single plan step.

    Args:
        step: A single atomic step from the Planner's ExecutionPlan.

    Returns:
        A result dictionary containing status, execution output, and verification outcome.
    """
    pass


async def verify_step_outcome(step: Dict[str, Any], tool_result: Dict[str, Any]) -> bool:
    """Verifies that the executed step achieved the expected physical state on disk.

    Args:
        step: The executed step containing expected outcome parameters.
        tool_result: Raw result returned by the Tool Layer.

    Returns:
        True if verified successfully on disk, False otherwise.
    """
    pass
