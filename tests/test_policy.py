"""Unit tests for the HeyBloopie Policy & Safety Engine."""

import json
import os
import sqlite3
import sys
import tempfile

import pytest

# Ensure python directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from python.policy import PolicyEngine, RiskLevel


@pytest.fixture
def temp_db_and_policy():
    """Creates a PolicyEngine instance with a fresh temporary SQLite database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    policy = PolicyEngine(db_path=db_path)
    yield db_path, policy

    if os.path.exists(db_path):
        os.remove(db_path)


def test_low_risk_tool_allowed(temp_db_and_policy):
    """TEST 1: A LOW risk tool that is in the allow-list is allowed."""
    db_path, policy = temp_db_and_policy

    approved_dir = policy.get_approved_paths()[0]

    # 'find_files' is in default allow-list and is LOW risk
    result = policy.check_action("find_files", {"directory": approved_dir, "query": "sample"})

    assert result.allowed is True
    assert result.risk_level == RiskLevel.LOW.value
    assert result.requires_confirmation is False
    assert "allowed" in result.reason.lower()


def test_tool_not_in_allowlist_denied(temp_db_and_policy):
    """TEST 2: A tool that is NOT in the allow-list is denied by default."""
    db_path, policy = temp_db_and_policy

    approved_dir = policy.get_approved_paths()[0]

    # 'move_file' is NOT in the default first-run allow-list
    result_move = policy.check_action(
        "move_file",
        {
            "source_path": os.path.join(approved_dir, "a.txt"),
            "destination_path": os.path.join(approved_dir, "b.txt")
        }
    )
    assert result_move.allowed is False
    assert result_move.requires_confirmation is False
    assert "not in the allowed tools list" in result_move.reason

    # Unknown or unapproved tool
    result_unknown = policy.check_action("unregistered_tool", {})
    assert result_unknown.allowed is False
    assert "not in the allowed tools list" in result_unknown.reason


def test_medium_risk_tool_requires_confirmation(temp_db_and_policy):
    """TEST 3: A MEDIUM risk tool requires confirmation."""
    db_path, policy = temp_db_and_policy

    approved_dir = policy.get_approved_paths()[0]

    # Explicitly grant 'rename_file' (MEDIUM risk) to the user's allowed_tools
    current_allowed = policy.get_allowed_tools()
    policy.set_allowed_tools(current_allowed + ["rename_file"])

    result = policy.check_action(
        "rename_file",
        {
            "target_path": os.path.join(approved_dir, "old_name.txt"),
            "new_name": "new_name.txt"
        }
    )

    assert result.allowed is True
    assert result.risk_level == RiskLevel.MEDIUM.value
    assert result.requires_confirmation is True
    assert "requires confirmation" in result.reason.lower()

    # Verify request_permission logs confirmation and returns True
    approved = policy.request_permission(
        "rename_file",
        {"target_path": os.path.join(approved_dir, "old_name.txt")}
    )
    assert approved is True


def test_path_outside_approved_directories_denied(temp_db_and_policy):
    """TEST 4: A path outside the approved directories is denied."""
    db_path, policy = temp_db_and_policy

    with tempfile.TemporaryDirectory() as safe_sandbox:
        approved_dir = os.path.join(safe_sandbox, "allowed_project")
        os.makedirs(approved_dir, exist_ok=True)
        policy.set_approved_paths([approved_dir])

        # Target file completely outside the approved directory
        outside_file = "C:\\UnapprovedExternalFolder\\secret.txt"

        # 'read_file_content' is in allow-list, but the target path is outside approved directories
        result = policy.check_action("read_file_content", {"file_path": outside_file})

        assert result.allowed is False
        assert result.requires_confirmation is False
        assert result.reason == "Path is outside approved directories."


def test_every_denial_logged_to_database(temp_db_and_policy):
    """TEST 5: Every denial is logged to the database."""
    db_path, policy = temp_db_and_policy

    # Trigger denial 1: Tool not allowed
    policy.check_action("delete_file", {"path": "C:\\some\\path.txt"})

    # Trigger denial 2: Path outside approved sandbox
    policy.check_action("get_file_metadata", {"file_path": "Z:\\forbidden\\volume\\test.doc"})

    # Inspect the denied_actions table in SQLite
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT tool_name, params, reason FROM denied_actions ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 2

    # Check first denial
    assert rows[0][0] == "delete_file"
    assert "not in the allowed tools list" in rows[0][2]

    # Check second denial
    assert rows[1][0] == "get_file_metadata"
    assert rows[1][2] == "Path is outside approved directories."
