"""HeyBloopie Memory Layer (SQLite Persistence).

This module manages all persistent storage and relational data access using Python's built-in
sqlite3 database engine. This is the ONLY module in the entire application that interacts with SQLite.
Every other module must go through this one.

Key Tables:
- tasks: History of executed tasks, plans, execution reports, and metrics.
- preferences: User preferences and configuration settings.
- feature_requests: Logged user requests outside currently supported tool capabilities.
- denied_actions: Security audit log recording actions blocked by the Policy Engine.

Architectural & Safety Constraints:
- Database connection created once and reused.
- All write operations use transactions (`with self.conn:`).
- Retries on database locks up to 3 times with a 100ms delay.
- All database operations use parameterized queries.
- Never raises exceptions to the caller; logs errors and returns None/empty results.
"""

import dataclasses
from datetime import datetime, timezone
import json
import logging
import os
import re
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("heybloopie.memory")


def get_default_db_path() -> str:
    """Returns the default database path in %APPDATA%/HeyBloopie/heybloopie.db."""
    app_data = os.environ.get("APPDATA")
    if app_data:
        base_dir = os.path.join(app_data, "HeyBloopie")
    else:
        base_dir = os.path.expanduser(os.path.join("~", ".heybloopie"))
    return os.path.join(base_dir, "heybloopie.db")


def get_iso_timestamp() -> str:
    """Returns the current UTC ISO 8601 timestamp string."""
    return datetime.now(timezone.utc).isoformat()


def _serialize_to_json(obj: Any) -> str:
    """Converts a dataclass, dict, list, or primitive to a JSON string."""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    try:
        if dataclasses.is_dataclass(obj):
            return json.dumps(dataclasses.asdict(obj))
        return json.dumps(obj)
    except Exception:
        return json.dumps(str(obj))


def _extract_status(report: Any) -> str:
    """Determines task status string ('success', 'partial', 'failed', 'cancelled') from report."""
    if report is None:
        return "failed"
    if isinstance(report, dict):
        if "status" in report:
            return str(report["status"]).lower()
        if report.get("summary") == "Cancelled.":
            return "cancelled"
        if report.get("success") is True:
            return "success"
        if report.get("steps_succeeded", 0) > 0 and report.get("steps_failed", 0) > 0:
            return "partial"
        return "failed"

    if hasattr(report, "status"):
        return str(report.status).lower()
    if getattr(report, "summary", "") == "Cancelled.":
        return "cancelled"
    if getattr(report, "success", False) is True:
        return "success"
    if getattr(report, "steps_succeeded", 0) > 0 and getattr(report, "steps_failed", 0) > 0:
        return "partial"
    return "failed"


class Memory:
    """Encapsulates all SQLite persistence and relational querying for HeyBloopie."""

    def __init__(self, db_path: Optional[str] = None):
        """Opens or creates the database and runs migrations.

        Args:
            db_path: Path to SQLite database file. Defaults to %APPDATA%/HeyBloopie/heybloopie.db.
        """
        self.db_path = db_path or get_default_db_path()
        self.conn: Optional[sqlite3.Connection] = None

        try:
            dir_name = os.path.dirname(os.path.abspath(self.db_path))
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            # Enable WAL mode for high concurrency
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self._migrate()
        except Exception as e:
            logger.error(f"Failed to initialize Memory database at {self.db_path}: {e}")

    def _execute_with_retry(self, operation: Callable[..., Any], *args, **kwargs) -> Any:
        """Executes an operation with up to 3 retries and 100ms delay on database lock."""
        max_retries = 3
        delay_seconds = 0.1

        for attempt in range(max_retries):
            try:
                return operation(*args, **kwargs)
            except sqlite3.OperationalError as err:
                if "locked" in str(err).lower() and attempt < max_retries - 1:
                    logger.warning(
                        f"Database is locked, retrying in 100ms (attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(delay_seconds)
                else:
                    logger.error(f"Database operational error: {err}")
                    return None
            except Exception as err:
                logger.error(f"Unexpected database error: {err}")
                return None
        return None

    def _migrate(self) -> None:
        """Creates tables and indexes if they do not exist. Never drops tables."""
        if not self.conn:
            return

        def run_migration():
            with self.conn:
                cursor = self.conn.cursor()

                # 1. tasks table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        user_request TEXT NOT NULL,
                        plan_json TEXT,
                        status TEXT NOT NULL,
                        report_json TEXT,
                        duration_ms INTEGER,
                        provider TEXT,
                        model TEXT
                    );
                """)

                # 2. preferences table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS preferences (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                """)

                # 3. feature_requests table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS feature_requests (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        request_text TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'logged'
                    );
                """)

                # 4. denied_actions table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS denied_actions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        params_json TEXT,
                        reason TEXT NOT NULL,
                        params TEXT
                    );
                """)

                # Ensure backward-compatible columns exist if table pre-existed
                cursor.execute("PRAGMA table_info(denied_actions);")
                existing_cols = {row[1] for row in cursor.fetchall()}
                if "params_json" not in existing_cols:
                    cursor.execute("ALTER TABLE denied_actions ADD COLUMN params_json TEXT;")
                if "params" not in existing_cols:
                    cursor.execute("ALTER TABLE denied_actions ADD COLUMN params TEXT;")

                # Index on tasks(timestamp DESC) for fast query performance
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_tasks_timestamp ON tasks(timestamp DESC);
                """)

                # 5. models table
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS models (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        is_free INTEGER NOT NULL DEFAULT 0,
                        context_length INTEGER DEFAULT 0,
                        input_price REAL DEFAULT 0.0,
                        output_price REAL DEFAULT 0.0,
                        last_updated TEXT NOT NULL
                    );
                """)
                cursor.execute("""
                    CREATE INDEX IF NOT EXISTS idx_models_provider ON models(provider);
                """)

        self._execute_with_retry(run_migration)

    # ═══════════════════════════════════════════════════════════════════
    # PART 2: Task Logging and Retrieval
    # ═══════════════════════════════════════════════════════════════════

    def log_task(
        self,
        user_request: str,
        plan: Any,
        report: Any,
        duration_ms: int,
        provider: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[int]:
        """Inserts a completed or cancelled task into the tasks table within a transaction.

        Args:
            user_request: Original user request string.
            plan: Plan object or dict.
            report: ExecutionReport object or dict.
            duration_ms: Time taken in milliseconds.
            provider: Name of AI provider used (optional).
            model: Name of model used (optional).

        Returns:
            The newly inserted task record ID, or None if failed.
        """
        if not self.conn:
            return None

        def execute_log():
            with self.conn:
                cursor = self.conn.cursor()
                now_iso = get_iso_timestamp()

                plan_json = _serialize_to_json(plan)
                report_json = _serialize_to_json(report)
                status = _extract_status(report)

                cursor.execute(
                    """
                    INSERT INTO tasks (
                        timestamp, user_request, plan_json, status, report_json, duration_ms, provider, model
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        now_iso,
                        user_request,
                        plan_json,
                        status,
                        report_json,
                        duration_ms,
                        provider,
                        model,
                    ),
                )
                return cursor.lastrowid

        return self._execute_with_retry(execute_log)

    def get_recent_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Returns the most recent N tasks ordered by timestamp DESC.

        Args:
            limit: Maximum number of recent tasks to return.

        Returns:
            List of dictionaries containing id, timestamp, user_request, status, duration_ms.
        """
        if not self.conn:
            return []

        def execute_get():
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, user_request, status, duration_ms
                FROM tasks
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

        result = self._execute_with_retry(execute_get)
        return result if result is not None else []

    def get_task_by_id(self, task_id: int) -> Optional[Dict[str, Any]]:
        """Returns the full task record including plan_json and report_json.

        Args:
            task_id: Integer task ID.

        Returns:
            Dictionary with all task columns or None if not found.
        """
        if not self.conn:
            return None

        def execute_get():
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, user_request, plan_json, status, report_json, duration_ms, provider, model
                FROM tasks
                WHERE id = ?
                """,
                (task_id,),
            )
            row = cursor.fetchone()
            return dict(row) if row else None

        return self._execute_with_retry(execute_get)

    def find_similar_task(self, user_request: str) -> Optional[Dict[str, Any]]:
        """Searches tasks table for a past task with a similar user_request.

        Supports reuse phrases:
        - "same as last time"
        - "do it again"
        - "use my usual"
        - "like before"
        - "again"
        - "usual"

        If the request is a pure reuse phrase (or has no specific task keywords),
        it returns the most recent task with a valid plan.
        If the request combines keywords with a reuse phrase, it looks up the most recent
        matching task with a valid plan.
        Otherwise, similarity in V1 is a lowercase substring match on the first 3 words.

        Args:
            user_request: Current user prompt string.

        Returns:
            The most recent matching task dictionary, or None.
        """
        if not self.conn or not user_request:
            return None

        def execute_find():
            req_lower = user_request.lower()
            reuse_patterns = [
                r"\bsame as last time\b",
                r"\bdo it again\b",
                r"\buse my usual\b",
                r"\blike before\b",
                r"\bagain\b",
                r"\busual\b",
            ]
            is_reuse = any(re.search(pat, req_lower) for pat in reuse_patterns)

            # Strip out reuse triggers to find underlying task description
            cleaned = req_lower
            for pat in reuse_patterns:
                cleaned = re.sub(pat, " ", cleaned)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()

            non_content_words = {
                "do", "that", "it", "this", "my", "the", "please", "just", "and", "a", "an", "for", "me", "to"
            }
            content_words = [w for w in re.findall(r"\b[a-zA-Z0-9_-]+\b", cleaned) if w not in non_content_words]

            cursor = self.conn.cursor()

            # If user request was purely a reuse phrase (e.g. "same as last time", "do it again"),
            # return the most recent past task that has an execution plan
            if is_reuse and not content_words:
                cursor.execute(
                    """
                    SELECT id, timestamp, user_request, plan_json, status, report_json, duration_ms, provider, model
                    FROM tasks
                    WHERE plan_json IS NOT NULL AND TRIM(plan_json) != ''
                    ORDER BY timestamp DESC, id DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
                return dict(row) if row else None

            raw_words = re.findall(r"\b[a-zA-Z0-9_-]+\b", user_request.lower())
            if not raw_words:
                return None

            search_phrase = " ".join(raw_words[: min(3, len(raw_words))])

            # 1. Search if search_phrase is a substring of a past user_request
            cursor.execute(
                """
                SELECT id, timestamp, user_request, plan_json, status, report_json, duration_ms, provider, model
                FROM tasks
                WHERE LOWER(user_request) LIKE ?
                ORDER BY timestamp DESC, id DESC
                LIMIT 1
                """,
                (f"%{search_phrase}%",),
            )
            row = cursor.fetchone()
            if row:
                return dict(row)

            # 2. Check if any past task's first 3 words match current user_request
            cursor.execute(
                """
                SELECT id, timestamp, user_request, plan_json, status, report_json, duration_ms, provider, model
                FROM tasks
                ORDER BY timestamp DESC, id DESC
                LIMIT 50
                """
            )
            for r in cursor.fetchall():
                past_words = re.findall(r"\b[a-zA-Z0-9_-]+\b", r["user_request"].lower())
                if past_words:
                    past_prefix = " ".join(past_words[: min(3, len(past_words))])
                    if past_prefix in user_request.lower():
                        return dict(r)

            # 3. If explicit reuse was requested and no specific match was found, fall back to most recent task
            if is_reuse:
                cursor.execute(
                    """
                    SELECT id, timestamp, user_request, plan_json, status, report_json, duration_ms, provider, model
                    FROM tasks
                    WHERE plan_json IS NOT NULL AND TRIM(plan_json) != ''
                    ORDER BY timestamp DESC, id DESC
                    LIMIT 1
                    """
                )
                fallback_row = cursor.fetchone()
                if fallback_row:
                    return dict(fallback_row)

            return None

        return self._execute_with_retry(execute_find)

    # ═══════════════════════════════════════════════════════════════════
    # PART 3: Preferences, Feature Requests, and Denied Actions
    # ═══════════════════════════════════════════════════════════════════

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Returns the JSON-decoded value for the key, or default if not found."""
        if not self.conn:
            return default

        def execute_get():
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT value FROM preferences WHERE key = ?",
                (key,),
            )
            row = cursor.fetchone()
            if row and row["value"]:
                try:
                    return json.loads(row["value"])
                except Exception:
                    return row["value"]
            return default

        result = self._execute_with_retry(execute_get)
        return result if result is not None else default

    def set_preference(self, key: str, value: Any) -> None:
        """JSON-encodes the value and upserts the preference row."""
        if not self.conn:
            return

        def execute_set():
            with self.conn:
                cursor = self.conn.cursor()
                json_val = json.dumps(value)
                now_iso = get_iso_timestamp()

                cursor.execute(
                    """
                    INSERT INTO preferences (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (key, json_val, now_iso),
                )

        self._execute_with_retry(execute_set)

    def get_all_preferences(self) -> Dict[str, Any]:
        """Returns all preferences as a single dictionary."""
        if not self.conn:
            return {}

        def execute_get_all():
            cursor = self.conn.cursor()
            cursor.execute("SELECT key, value FROM preferences")
            prefs = {}
            for row in cursor.fetchall():
                try:
                    prefs[row["key"]] = json.loads(row["value"])
                except Exception:
                    prefs[row["key"]] = row["value"]
            return prefs

        result = self._execute_with_retry(execute_get_all)
        return result if result is not None else {}

    def log_feature_request(self, request_text: str) -> Optional[int]:
        """Inserts a row into feature_requests with status='logged'."""
        if not self.conn:
            return None

        def execute_log():
            with self.conn:
                cursor = self.conn.cursor()
                now_iso = get_iso_timestamp()
                cursor.execute(
                    """
                    INSERT INTO feature_requests (timestamp, request_text, status)
                    VALUES (?, ?, 'logged')
                    """,
                    (now_iso, request_text),
                )
                return cursor.lastrowid

        return self._execute_with_retry(execute_log)

    def get_feature_requests(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns feature requests, optionally filtered by status, ordered by timestamp DESC."""
        if not self.conn:
            return []

        def execute_get():
            cursor = self.conn.cursor()
            if status:
                cursor.execute(
                    """
                    SELECT id, timestamp, request_text, status
                    FROM feature_requests
                    WHERE status = ?
                    ORDER BY timestamp DESC, id DESC
                    """,
                    (status,),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, timestamp, request_text, status
                    FROM feature_requests
                    ORDER BY timestamp DESC, id DESC
                    """
                )
            return [dict(row) for row in cursor.fetchall()]

        result = self._execute_with_retry(execute_get)
        return result if result is not None else []

    def log_denial(self, tool_name: str, params: Any, reason: str) -> Optional[int]:
        """Inserts a row into denied_actions whenever Policy Engine blocks an action."""
        if not self.conn:
            return None

        def execute_log():
            with self.conn:
                cursor = self.conn.cursor()
                now_iso = get_iso_timestamp()
                params_json = _serialize_to_json(params)

                cursor.execute(
                    """
                    INSERT INTO denied_actions (timestamp, tool_name, params_json, reason, params)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (now_iso, tool_name, params_json, reason, params_json),
                )
                return cursor.lastrowid

        return self._execute_with_retry(execute_log)

    def get_denials(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Returns the most recent denials ordered by timestamp DESC."""
        if not self.conn:
            return []

        def execute_get():
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, tool_name, params_json, reason
                FROM denied_actions
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

        result = self._execute_with_retry(execute_get)
        return result if result is not None else []

    def export_log(self, file_path: str) -> None:
        """Exports the entire tasks table to a JSON file at the given path."""
        if not self.conn or not file_path:
            return

        def execute_export():
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT id, timestamp, user_request, plan_json, status, report_json, duration_ms, provider, model
                FROM tasks
                ORDER BY timestamp ASC, id ASC
                """
            )
            rows = [dict(row) for row in cursor.fetchall()]
            dir_name = os.path.dirname(os.path.abspath(file_path))
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2)

        self._execute_with_retry(execute_export)

    # ═══════════════════════════════════════════════════════════════════
    # PART 6: Models Registry Persistence
    # ═══════════════════════════════════════════════════════════════════

    def save_models(self, models: List[Dict[str, Any]]) -> bool:
        """Upserts a list of model records into the models table within a transaction.

        Args:
            models: List of model dictionaries matching the models table schema.

        Returns:
            True if successful, False otherwise.
        """
        if not self.conn or not models:
            return False

        def op():
            with self.conn:
                cursor = self.conn.cursor()
                cursor.executemany(
                    """
                    INSERT INTO models (id, name, provider, is_free, context_length, input_price, output_price, last_updated)
                    VALUES (:id, :name, :provider, :is_free, :context_length, :input_price, :output_price, :last_updated)
                    ON CONFLICT(id) DO UPDATE SET
                        name=excluded.name,
                        provider=excluded.provider,
                        is_free=excluded.is_free,
                        context_length=excluded.context_length,
                        input_price=excluded.input_price,
                        output_price=excluded.output_price,
                        last_updated=excluded.last_updated;
                    """,
                    models,
                )
                return True

        res = self._execute_with_retry(op)
        return bool(res)

    def get_models(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves models, optionally filtered by provider.

        Args:
            provider: Provider name to filter by (e.g. 'gemini', 'openrouter'), or None for all.

        Returns:
            List of model dictionaries ordered by is_free DESC, name ASC.
        """
        if not self.conn:
            return []

        def op():
            cursor = self.conn.cursor()
            if provider:
                cursor.execute(
                    """
                    SELECT id, name, provider, is_free, context_length, input_price, output_price, last_updated
                    FROM models
                    WHERE LOWER(provider) = LOWER(?)
                    ORDER BY is_free DESC, name ASC;
                    """,
                    (provider,),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, name, provider, is_free, context_length, input_price, output_price, last_updated
                    FROM models
                    ORDER BY provider ASC, is_free DESC, name ASC;
                    """
                )
            rows = cursor.fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "provider": row["provider"],
                    "is_free": row["is_free"],
                    "context_length": row["context_length"],
                    "input_price": row["input_price"],
                    "output_price": row["output_price"],
                    "last_updated": row["last_updated"],
                }
                for row in rows
            ]

        res = self._execute_with_retry(op)
        return res if res is not None else []

    def get_model(self, model_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a single model by ID.

        Args:
            model_id: Unique model identifier.

        Returns:
            Model dictionary if found, None otherwise.
        """
        if not self.conn:
            return None

        def op():
            cursor = self.conn.cursor()
            cursor.execute(
                """
                SELECT id, name, provider, is_free, context_length, input_price, output_price, last_updated
                FROM models
                WHERE id = ?
                LIMIT 1;
                """,
                (model_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "name": row["name"],
                "provider": row["provider"],
                "is_free": row["is_free"],
                "context_length": row["context_length"],
                "input_price": row["input_price"],
                "output_price": row["output_price"],
                "last_updated": row["last_updated"],
            }

        return self._execute_with_retry(op)

    def get_models_last_updated(self, provider: str) -> Optional[str]:
        """Gets the most recent last_updated timestamp for a provider's models."""
        if not self.conn:
            return None

        def op():
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT MAX(last_updated) as latest FROM models WHERE LOWER(provider) = LOWER(?);",
                (provider,),
            )
            row = cursor.fetchone()
            return row["latest"] if row and row["latest"] else None

        return self._execute_with_retry(op)

    def close(self) -> None:
        """Closes the connection cleanly."""
        if self.conn:
            try:
                self.conn.close()
            except Exception as e:
                logger.warning(f"Error while closing database connection: {e}")
            self.conn = None


# Module-level singleton helper
_default_memory: Optional[Memory] = None


def get_memory(db_path: Optional[str] = None) -> Memory:
    """Returns or initializes the singleton Memory instance."""
    global _default_memory
    if _default_memory is None or (db_path and _default_memory.db_path != db_path):
        _default_memory = Memory(db_path=db_path)
    return _default_memory


def log_task(*args, **kwargs):
    return get_memory().log_task(*args, **kwargs)


def get_recent_tasks(*args, **kwargs):
    return get_memory().get_recent_tasks(*args, **kwargs)


def get_task_by_id(*args, **kwargs):
    return get_memory().get_task_by_id(*args, **kwargs)


def find_similar_task(*args, **kwargs):
    return get_memory().find_similar_task(*args, **kwargs)


def get_preference(*args, **kwargs):
    return get_memory().get_preference(*args, **kwargs)


def set_preference(*args, **kwargs):
    return get_memory().set_preference(*args, **kwargs)


def get_all_preferences(*args, **kwargs):
    return get_memory().get_all_preferences(*args, **kwargs)


def log_feature_request(*args, **kwargs):
    return get_memory().log_feature_request(*args, **kwargs)


def get_feature_requests(*args, **kwargs):
    return get_memory().get_feature_requests(*args, **kwargs)


def log_denial(*args, **kwargs):
    return get_memory().log_denial(*args, **kwargs)


def get_denials(*args, **kwargs):
    return get_memory().get_denials(*args, **kwargs)


def export_log(*args, **kwargs):
    return get_memory().export_log(*args, **kwargs)


def save_models(*args, **kwargs):
    return get_memory().save_models(*args, **kwargs)


def get_models(*args, **kwargs):
    return get_memory().get_models(*args, **kwargs)


def get_model(*args, **kwargs):
    return get_memory().get_model(*args, **kwargs)


def get_models_last_updated(*args, **kwargs):
    return get_memory().get_models_last_updated(*args, **kwargs)


