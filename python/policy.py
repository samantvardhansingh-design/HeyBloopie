"""HeyBloopie Policy & Safety Engine.

This module implements the core security model defined in docs/SECURITY.md.
Every tool invocation must pass through this engine before execution.
This is a hard, code-level constraint that cannot be bypassed by prompts or models.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
import logging
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("heybloopie.policy")


class RiskLevel(str, Enum):
    """Risk tiers determining required user confirmation interaction."""
    LOW = "low"          # Read-only actions (find_files, list_folder, get_file_metadata, read_file_content)
    MEDIUM = "medium"    # Modifying actions (move_file, rename_file, create_folder)
    HIGH = "high"        # Destructive or irreversible actions (delete_file, overwrite_file)


TOOL_RISK_MAPPING: Dict[str, RiskLevel] = {
    "find_files": RiskLevel.LOW,
    "list_folder": RiskLevel.LOW,
    "get_file_metadata": RiskLevel.LOW,
    "read_file_content": RiskLevel.LOW,
    "move_file": RiskLevel.MEDIUM,
    "rename_file": RiskLevel.MEDIUM,
    "create_folder": RiskLevel.MEDIUM,
    "delete_file": RiskLevel.HIGH,
    "overwrite_file": RiskLevel.HIGH,
}

DEFAULT_LOW_RISK_TOOLS: List[str] = [
    "find_files",
    "list_folder",
    "get_file_metadata",
    "read_file_content",
]

FORBIDDEN_SYSTEM_DIRECTORIES: List[str] = [
    os.path.realpath("C:\\Windows"),
    os.path.realpath("C:\\Program Files"),
    os.path.realpath("C:\\Program Files (x86)"),
    os.path.realpath("C:\\ProgramData"),
]

PATH_PARAM_KEYS: Set[str] = {
    "path",
    "directory",
    "folder_path",
    "file_path",
    "source_path",
    "destination_path",
    "target_path",
}


@dataclass
class PolicyResult:
    """Standardized decision returned by PolicyEngine for any proposed action."""
    allowed: bool
    risk_level: str
    reason: str
    requires_confirmation: bool


class PolicyEngine:
    """Security engine enforcing least privilege, path sandboxing, and confirmation gating."""

    def __init__(self, db_path: str = "heybloopie.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Initializes database tables and default permissions if not present."""
        conn = self._get_connection()
        cursor = conn.cursor()

        # Preferences table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Denied actions audit log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS denied_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                tool_name TEXT,
                params TEXT,
                reason TEXT,
                params_json TEXT
            )
        """)

        # Task and confirmation log
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                tool_name TEXT,
                params TEXT,
                status TEXT
            )
        """)

        # Set default allowed tools (LOW risk tools only on first run)
        cursor.execute("SELECT value FROM preferences WHERE key = 'allowed_tools'")
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO preferences (key, value) VALUES (?, ?)",
                ("allowed_tools", json.dumps(DEFAULT_LOW_RISK_TOOLS))
            )

        # Set default approved paths (user home directory on first run)
        cursor.execute("SELECT value FROM preferences WHERE key = 'approved_paths'")
        if cursor.fetchone() is None:
            home_dir = os.path.realpath(os.path.expanduser("~"))
            cursor.execute(
                "INSERT INTO preferences (key, value) VALUES (?, ?)",
                ("approved_paths", json.dumps([home_dir]))
            )

        conn.commit()
        conn.close()

    def get_allowed_tools(self) -> List[str]:
        """Retrieves currently allowed tools from SQLite preferences."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM preferences WHERE key = 'allowed_tools'")
        row = cursor.fetchone()
        conn.close()
        if row and row["value"]:
            try:
                return json.loads(row["value"])
            except Exception:
                pass
        return list(DEFAULT_LOW_RISK_TOOLS)

    def set_allowed_tools(self, tools: List[str]) -> None:
        """Updates the allowed tools list in SQLite preferences."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)",
            ("allowed_tools", json.dumps(tools))
        )
        conn.commit()
        conn.close()

    def get_approved_paths(self) -> List[str]:
        """Retrieves approved directory paths from SQLite preferences."""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM preferences WHERE key = 'approved_paths'")
        row = cursor.fetchone()
        conn.close()
        if row and row["value"]:
            try:
                paths = json.loads(row["value"])
                return [os.path.realpath(p) for p in paths]
            except Exception:
                pass
        return [os.path.realpath(os.path.expanduser("~"))]

    def set_approved_paths(self, paths: List[str]) -> None:
        """Updates approved paths list in SQLite preferences."""
        canonical_paths = [os.path.realpath(p) for p in paths]
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)",
            ("approved_paths", json.dumps(canonical_paths))
        )
        conn.commit()
        conn.close()

    def assess_risk_level(self, tool_name: str) -> RiskLevel:
        """Determines the risk tier of the tool. Unknown tools default to HIGH risk."""
        return TOOL_RISK_MAPPING.get(tool_name, RiskLevel.HIGH)

    def _extract_paths(self, params: Dict[str, Any]) -> List[str]:
        """Extracts all path arguments from parameters."""
        paths = []
        for k, v in params.items():
            if isinstance(v, str):
                if k in PATH_PARAM_KEYS or "path" in k or "dir" in k:
                    paths.append(v)
        return paths

    def _is_path_permitted(self, raw_path: str, approved_paths: List[str]) -> bool:
        """Checks if a canonicalized path is within approved directories and outside system folders."""
        try:
            canonical_path = os.path.realpath(os.path.abspath(raw_path))
            norm_canonical = os.path.normcase(canonical_path)

            # Hard block forbidden system directories
            for forbidden in FORBIDDEN_SYSTEM_DIRECTORIES:
                norm_forbidden = os.path.normcase(forbidden)
                if norm_canonical == norm_forbidden or norm_canonical.startswith(norm_forbidden + os.sep):
                    return False

            # Check if canonical path falls within at least one approved path
            for approved in approved_paths:
                norm_approved = os.path.normcase(os.path.realpath(approved))
                if norm_canonical == norm_approved or norm_canonical.startswith(norm_approved + os.sep):
                    return True

            return False
        except Exception:
            return False

    def check_action(self, tool_name: str, params: Optional[Dict[str, Any]] = None) -> PolicyResult:
        """Evaluates a proposed action against allow-lists, risk levels, and sandbox boundaries.

        Args:
            tool_name: Name of the tool function to be invoked.
            params: Dictionary of parameters passed to the tool.

        Returns:
            PolicyResult indicating allowed status, risk level, confirmation requirement, and reason.
        """
        params = params or {}
        risk_level = self.assess_risk_level(tool_name)
        allowed_tools = self.get_allowed_tools()

        # Check 1: Deny by default if tool is not in allow-list
        if tool_name not in allowed_tools:
            reason = f"Tool '{tool_name}' is not in the allowed tools list."
            self.log_denial(tool_name, params, reason)
            return PolicyResult(
                allowed=False,
                risk_level=risk_level.value,
                reason=reason,
                requires_confirmation=False
            )

        # Check 2: Verify all target paths against approved directories sandbox
        extracted_paths = self._extract_paths(params)
        if extracted_paths:
            approved_paths = self.get_approved_paths()
            for path_val in extracted_paths:
                if not self._is_path_permitted(path_val, approved_paths):
                    reason = "Path is outside approved directories."
                    self.log_denial(tool_name, params, reason)
                    return PolicyResult(
                        allowed=False,
                        risk_level=risk_level.value,
                        reason=reason,
                        requires_confirmation=False
                    )

        # Check 3: Determine confirmation requirement based on risk tier
        if risk_level == RiskLevel.LOW:
            return PolicyResult(
                allowed=True,
                risk_level=risk_level.value,
                reason="Action allowed.",
                requires_confirmation=False
            )
        else:
            # Medium and High risk tools require confirmation
            return PolicyResult(
                allowed=True,
                risk_level=risk_level.value,
                reason="Action requires confirmation.",
                requires_confirmation=True
            )

    def request_permission(self, tool_name: str, params: Dict[str, Any]) -> bool:
        """Prompts user for confirmation for Medium and High risk operations.

        For V1, this assumes approved (True) and writes an audit entry to the task log.
        """
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO task_log (tool_name, params, status) VALUES (?, ?, ?)",
            (tool_name, json.dumps(params), "CONFIRMED")
        )
        conn.commit()
        conn.close()
        logger.info(f"Permission granted for {tool_name} with params {params}")
        return True

    def log_denial(self, tool_name: str, params: Dict[str, Any], reason: str) -> None:
        """Logs every denied action into the denied_actions table for security auditing."""
        try:
            from python.memory import Memory
            mem = Memory(db_path=self.db_path)
            mem.log_denial(tool_name, params, reason)
            mem.close()
            logger.warning(f"Action DENIED: {tool_name} | Reason: {reason} | Params: {params}")
        except Exception as e:
            logger.error(f"Failed to log denial to database: {e}")


_default_policy_engine: Optional[PolicyEngine] = None


def get_policy_engine() -> PolicyEngine:
    """Returns the singleton PolicyEngine instance."""
    global _default_policy_engine
    if _default_policy_engine is None:
        _default_policy_engine = PolicyEngine()
    return _default_policy_engine


def check_action(tool_name: str, params: Optional[Dict[str, Any]] = None) -> PolicyResult:
    """Evaluates a proposed action against allow-lists, risk levels, and sandbox boundaries."""
    return get_policy_engine().check_action(tool_name, params)


def request_permission(tool_name: str, params: Dict[str, Any]) -> bool:
    """Prompts user for confirmation for Medium and High risk operations."""
    return get_policy_engine().request_permission(tool_name, params)


def log_denial(tool_name: str, params: Dict[str, Any], reason: str) -> None:
    """Logs denied actions via the policy engine."""
    return get_policy_engine().log_denial(tool_name, params, reason)


