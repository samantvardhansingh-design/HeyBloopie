"""Unit tests for the HeyBloopie Memory Layer (Part 1).

Tests cover:
- Test that the database file is created on first init.
- Test that all 4 tables exist after init.
- Test that re-initializing does not drop existing data.
- Test that a parameterized query is used (inspect the code).
"""

import ast
import json
import os
import sqlite3
import sys
import tempfile
import pytest

# Ensure python directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from python import core, memory, planner, policy, tools
from python.memory import Memory


@pytest.fixture
def temp_db_path():
    """Provides a fresh temporary file path for database testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    if os.path.exists(path):
        os.remove(path)
    yield path
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def test_database_file_created_on_first_init(temp_db_path):
    """Test that the database file is created on first init."""
    assert not os.path.exists(temp_db_path)
    memory = Memory(db_path=temp_db_path)
    try:
        assert os.path.exists(temp_db_path)
        assert memory.conn is not None
    finally:
        memory.close()


def test_all_four_tables_exist_after_init(temp_db_path):
    """Test that all 4 tables exist after init (tasks, preferences, feature_requests, denied_actions)."""
    memory = Memory(db_path=temp_db_path)
    try:
        cursor = memory.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = {row[0] for row in cursor.fetchall()}

        expected_tables = {"tasks", "preferences", "feature_requests", "denied_actions"}
        assert expected_tables.issubset(tables), f"Missing tables. Found: {tables}"

        # Verify index exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_tasks_timestamp';")
        index = cursor.fetchone()
        assert index is not None, "Index idx_tasks_timestamp was not created"
    finally:
        memory.close()


def test_reinitializing_does_not_drop_existing_data(temp_db_path):
    """Test that re-initializing does not drop existing data."""
    # First init: insert test data
    memory1 = Memory(db_path=temp_db_path)
    with memory1.conn:
        cursor = memory1.conn.cursor()
        cursor.execute(
            "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, ?)",
            ("theme", '"dark"', "2026-09-24T10:00:00Z"),
        )
    memory1.close()

    # Second init: re-open existing DB and verify data is intact
    memory2 = Memory(db_path=temp_db_path)
    try:
        cursor = memory2.conn.cursor()
        cursor.execute("SELECT key, value FROM preferences WHERE key = ?", ("theme",))
        row = cursor.fetchone()
        assert row is not None
        assert row["key"] == "theme"
        assert row["value"] == '"dark"'
    finally:
        memory2.close()


def test_parameterized_query_used():
    """Inspect python/memory.py source code and AST to verify parameterized queries are used."""
    memory_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "python", "memory.py"))
    with open(memory_file, "r", encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Check if function called is .execute()
            if isinstance(node.func, ast.Attribute) and node.func.attr == "execute":
                args = node.args
                if args:
                    sql_arg = args[0]
                    # Ensure the SQL string is not an f-string or string formatting with % or format()
                    assert not isinstance(sql_arg, ast.JoinedStr), (
                        "Dangerous f-string detected in SQL execute call. Use parameterized query with '?' placeholders."
                    )
                    if isinstance(sql_arg, ast.BinOp) and isinstance(sql_arg.op, (ast.Mod, ast.Add)):
                        raise AssertionError(
                            "String formatting/concatenation detected in SQL execute call. Use parameterized queries."
                        )
                    if isinstance(sql_arg, ast.Call) and isinstance(sql_arg.func, ast.Attribute) and sql_arg.func.attr == "format":
                        raise AssertionError(
                            ".format() detected in SQL execute call. Use parameterized queries."
                        )


# ═══════════════════════════════════════════════════════════════════
# PART 2: Task Logging and Retrieval Tests
# ═══════════════════════════════════════════════════════════════════

def test_log_task_inserts_row(temp_db_path):
    """Test that log_task inserts a row and returns a valid task ID."""
    memory = Memory(db_path=temp_db_path)
    try:
        plan = {"steps": [{"tool_name": "find_files", "params": {"query": "receipts"}}]}
        report = {"success": True, "summary": "Found 3 files.", "steps_succeeded": 1, "steps_failed": 0}

        task_id = memory.log_task(
            user_request="find my receipts",
            plan=plan,
            report=report,
            duration_ms=120,
            provider="gemini",
            model="gemini-1.5-flash",
        )

        assert task_id is not None
        assert task_id > 0

        # Query database directly to confirm row was committed
        cursor = memory.conn.cursor()
        cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cursor.fetchone()
        assert row is not None
        assert row["user_request"] == "find my receipts"
        assert row["status"] == "success"
        assert row["duration_ms"] == 120
        assert row["provider"] == "gemini"
    finally:
        memory.close()


def test_get_recent_tasks_returns_desc_order(temp_db_path):
    """Test that get_recent_tasks returns tasks in DESC order."""
    memory = Memory(db_path=temp_db_path)
    try:
        # Insert 3 tasks
        t1 = memory.log_task("task one", {}, {"success": True}, 100)
        t2 = memory.log_task("task two", {}, {"success": True}, 200)
        t3 = memory.log_task("task three", {}, {"success": True}, 300)

        recent = memory.get_recent_tasks(limit=10)
        assert len(recent) == 3
        # Should be ordered by timestamp DESC (t3, t2, t1)
        assert recent[0]["user_request"] == "task three"
        assert recent[1]["user_request"] == "task two"
        assert recent[2]["user_request"] == "task one"

        # Verify dict keys returned
        assert {"id", "timestamp", "user_request", "status", "duration_ms"}.issubset(recent[0].keys())
    finally:
        memory.close()


def test_get_task_by_id_returns_full_task(temp_db_path):
    """Test that get_task_by_id returns the full task including plan_json and report_json."""
    memory = Memory(db_path=temp_db_path)
    try:
        plan = {"steps": [{"tool_name": "find_files"}]}
        report = {"success": True, "summary": "Done."}
        task_id = memory.log_task("organize docs", plan, report, 250, "gemini", "flash")

        task = memory.get_task_by_id(task_id)
        assert task is not None
        assert task["id"] == task_id
        assert task["user_request"] == "organize docs"
        assert "find_files" in task["plan_json"]
        assert "Done." in task["report_json"]
        assert task["status"] == "success"
        assert task["duration_ms"] == 250
        assert task["provider"] == "gemini"

        # Non-existent task returns None
        assert memory.get_task_by_id(99999) is None
    finally:
        memory.close()


def test_find_similar_task_returns_match_for_similar_request(temp_db_path):
    """Test that find_similar_task returns a match for a similar request."""
    memory = Memory(db_path=temp_db_path)
    try:
        # Log a past task: "organize my downloads folder"
        memory.log_task(
            user_request="organize my downloads folder",
            plan={"steps": []},
            report={"success": True, "summary": "Organized downloads."},
            duration_ms=400,
        )

        # Similar query: "organize my downloads"
        match = memory.find_similar_task("organize my downloads")
        assert match is not None
        assert match["user_request"] == "organize my downloads folder"
        assert match["status"] == "success"
    finally:
        memory.close()


def test_find_similar_task_returns_none_for_unrelated_request(temp_db_path):
    """Test that find_similar_task returns None for an unrelated request."""
    memory = Memory(db_path=temp_db_path)
    try:
        memory.log_task(
            user_request="organize my downloads folder",
            plan={"steps": []},
            report={"success": True, "summary": "Organized downloads."},
            duration_ms=400,
        )

        # Completely unrelated request
        match = memory.find_similar_task("send an email to team")
        assert match is None
    finally:
        memory.close()


# ═══════════════════════════════════════════════════════════════════
# PART 3: Preferences, Feature Requests, and Denials Tests
# ═══════════════════════════════════════════════════════════════════

def test_set_and_get_preference_roundtrip(temp_db_path):
    """Test that set_preference and get_preference round-trip correctly for multiple types."""
    memory = Memory(db_path=temp_db_path)
    try:
        memory.set_preference("wake_word", "hey bloopie")
        memory.set_preference("wake_word_enabled", True)
        memory.set_preference("allowed_tools", ["find_files", "list_folder"])
        memory.set_preference("config", {"timeout": 30, "debug": False})

        assert memory.get_preference("wake_word") == "hey bloopie"
        assert memory.get_preference("wake_word_enabled") is True
        assert memory.get_preference("allowed_tools") == ["find_files", "list_folder"]
        assert memory.get_preference("config") == {"timeout": 30, "debug": False}

        # Test updating an existing preference
        memory.set_preference("wake_word", "computer")
        assert memory.get_preference("wake_word") == "computer"
    finally:
        memory.close()


def test_get_preference_returns_default_when_missing(temp_db_path):
    """Test that get_preference returns the default when the key is missing."""
    memory = Memory(db_path=temp_db_path)
    try:
        assert memory.get_preference("nonexistent_key") is None
        assert memory.get_preference("nonexistent_key", "default_val") == "default_val"
        assert memory.get_preference("missing_count", 42) == 42
    finally:
        memory.close()


def test_get_all_preferences(temp_db_path):
    """Test that get_all_preferences returns all preferences as a single dictionary."""
    memory = Memory(db_path=temp_db_path)
    try:
        memory.set_preference("pref1", "val1")
        memory.set_preference("pref2", 123)

        all_prefs = memory.get_all_preferences()
        assert all_prefs == {"pref1": "val1", "pref2": 123}
    finally:
        memory.close()


def test_log_feature_request_inserts_row(temp_db_path):
    """Test that log_feature_request inserts a row with status='logged'."""
    memory = Memory(db_path=temp_db_path)
    try:
        row_id = memory.log_feature_request("sync my files to Google Drive")
        assert row_id is not None
        assert row_id > 0

        requests = memory.get_feature_requests()
        assert len(requests) == 1
        assert requests[0]["request_text"] == "sync my files to Google Drive"
        assert requests[0]["status"] == "logged"
    finally:
        memory.close()


def test_get_feature_requests_filters_by_status(temp_db_path):
    """Test that get_feature_requests filters by status."""
    memory = Memory(db_path=temp_db_path)
    try:
        memory.log_feature_request("request 1")
        memory.log_feature_request("request 2")

        # Manually update one row to 'planned'
        with memory.conn:
            cursor = memory.conn.cursor()
            cursor.execute("UPDATE feature_requests SET status = 'planned' WHERE request_text = 'request 2'")

        logged = memory.get_feature_requests(status="logged")
        assert len(logged) == 1
        assert logged[0]["request_text"] == "request 1"

        planned = memory.get_feature_requests(status="planned")
        assert len(planned) == 1
        assert planned[0]["request_text"] == "request 2"

        all_reqs = memory.get_feature_requests()
        assert len(all_reqs) == 2
    finally:
        memory.close()


def test_log_denial_inserts_row(temp_db_path):
    """Test that log_denial inserts a row and get_denials retrieves it."""
    memory = Memory(db_path=temp_db_path)
    try:
        denial_id = memory.log_denial(
            tool_name="delete_file",
            params={"path": "C:\\Windows\\System32\\calc.exe"},
            reason="Path is in forbidden system directory",
        )
        assert denial_id is not None
        assert denial_id > 0

        denials = memory.get_denials(limit=10)
        assert len(denials) == 1
        assert denials[0]["tool_name"] == "delete_file"
        assert "calc.exe" in denials[0]["params_json"]
        assert "forbidden system directory" in denials[0]["reason"]
    finally:
        memory.close()


# ═══════════════════════════════════════════════════════════════════
# PART 4: Integration with Core & Policy Engine Tests
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def mock_memory_db(temp_db_path, monkeypatch):
    """Initializes a temporary Memory instance and points memory singleton to it."""
    test_mem = Memory(db_path=temp_db_path)
    monkeypatch.setattr(memory, "_default_memory", test_mem)
    monkeypatch.setattr(memory, "get_memory", lambda db_path=None: test_mem)
    yield test_mem
    test_mem.close()


@pytest.mark.asyncio
async def test_completed_task_is_logged(mock_memory_db, monkeypatch):
    """Test that a completed task is logged to tasks table with duration and report."""
    step = planner.PlanStep(
        tool_name="find_files",
        params={"query": "invoices"},
        risk_level="low",
        description="Search for invoice documents",
    )
    plan = planner.Plan(
        steps=[step],
        summary="Find invoices",
        requires_confirmation=False,
    )

    async def mock_create_plan(user_request: str, available_tools=None):
        return plan

    async def mock_find_files(**kwargs):
        return tools.ToolResult(
            success=True,
            data=[{"name": "inv_2026.pdf", "path": "C:\\docs\\inv_2026.pdf"}],
            message="Found 1 file",
            verified=True,
            verification_details="",
        )

    monkeypatch.setattr(planner, "create_plan", mock_create_plan)
    monkeypatch.setattr(tools, "find_files", mock_find_files)
    monkeypatch.setitem(core.TOOL_DISPATCH, "find_files", mock_find_files)

    report = await core.run("find my invoices")
    assert report.success is True

    recent = mock_memory_db.get_recent_tasks(limit=5)
    assert len(recent) == 1
    assert recent[0]["user_request"] == "find my invoices"
    assert recent[0]["status"] == "success"
    assert recent[0]["duration_ms"] >= 0

    full_task = mock_memory_db.get_task_by_id(recent[0]["id"])
    assert full_task is not None
    assert "invoices" in full_task["plan_json"]
    assert "Done" in full_task["report_json"]


@pytest.mark.asyncio
async def test_same_as_last_time_reuses_past_plan(mock_memory_db, monkeypatch):
    """Test that 'same as last time' reuses a past plan without re-invoking the planner."""
    step = planner.PlanStep(
        tool_name="find_files",
        params={"query": "quarterly"},
        risk_level="low",
        description="Find quarterly report",
    )
    plan = planner.Plan(
        steps=[step],
        summary="Search quarterly report",
        requires_confirmation=False,
    )

    create_plan_calls = 0

    async def mock_create_plan(user_request: str, available_tools=None):
        nonlocal create_plan_calls
        create_plan_calls += 1
        return plan

    executed_queries = []

    async def mock_find_files(query, **kwargs):
        executed_queries.append(query)
        return tools.ToolResult(
            success=True,
            data=[{"name": "quarterly.pdf", "path": "C:\\reports\\quarterly.pdf"}],
            message="Found 1 file",
            verified=True,
            verification_details="",
        )

    monkeypatch.setattr(planner, "create_plan", mock_create_plan)
    monkeypatch.setattr(tools, "find_files", mock_find_files)
    monkeypatch.setitem(core.TOOL_DISPATCH, "find_files", mock_find_files)

    # Initial run
    report1 = await core.run("find quarterly report")
    assert report1.success is True
    assert create_plan_calls == 1
    assert executed_queries == ["quarterly"]

    # Subsequent run asking for 'same as last time'
    report2 = await core.run("same as last time")
    assert report2.success is True
    # Planner was not called again; reused plan from memory
    assert create_plan_calls == 1
    assert executed_queries == ["quarterly", "quarterly"]
    assert report2.steps_succeeded == 1


@pytest.mark.asyncio
async def test_do_it_again_reuses_past_plan(mock_memory_db, monkeypatch):
    """Test that 'do it again' reuses a past plan."""
    step = planner.PlanStep(
        tool_name="find_files",
        params={"query": "receipts"},
        risk_level="low",
        description="Find receipts",
    )
    plan = planner.Plan(steps=[step], summary="Find receipts", requires_confirmation=False)
    report = core.ExecutionReport(
        success=True,
        summary="Done. Found 2 files.",
        details=[],
        exceptions=[],
        total_steps=1,
        steps_succeeded=1,
        steps_failed=0,
    )
    mock_memory_db.log_task(
        user_request="find my receipts",
        plan=plan,
        report=report,
        duration_ms=80,
    )

    planner_called = False

    async def mock_create_plan(user_request: str, available_tools=None):
        nonlocal planner_called
        planner_called = True
        return planner.Plan(steps=[], summary="", requires_confirmation=False)

    executed_queries = []

    async def mock_find_files(query, **kwargs):
        executed_queries.append(query)
        return tools.ToolResult(
            success=True,
            data=[{"name": "receipt.pdf", "path": "C:\\receipt.pdf"}],
            message="Found 1 file",
            verified=True,
            verification_details="",
        )

    monkeypatch.setattr(planner, "create_plan", mock_create_plan)
    monkeypatch.setattr(tools, "find_files", mock_find_files)
    monkeypatch.setitem(core.TOOL_DISPATCH, "find_files", mock_find_files)

    result = await core.run("do it again")
    assert result.success is True
    assert planner_called is False
    assert executed_queries == ["receipts"]
    assert result.steps_succeeded == 1


@pytest.mark.asyncio
async def test_unsupported_request_logged_to_feature_requests(mock_memory_db, monkeypatch):
    """Test that an unsupported request (0 steps) is logged to feature_requests."""
    empty_plan = planner.Plan(
        steps=[],
        summary="I cannot send emails.",
        requires_confirmation=False,
    )

    async def mock_create_plan(user_request: str, available_tools=None):
        return empty_plan

    monkeypatch.setattr(planner, "create_plan", mock_create_plan)

    report = await core.run("send an email to Alice")
    assert report.success is False
    assert "I can't do that yet" in report.summary

    requests = mock_memory_db.get_feature_requests()
    assert len(requests) == 1
    assert requests[0]["request_text"] == "send an email to Alice"
    assert requests[0]["status"] == "logged"


def test_denied_action_logged_to_denied_actions(mock_memory_db, monkeypatch):
    """Test that a denied action is logged to denied_actions via policy engine."""
    monkeypatch.setattr(policy.get_policy_engine(), "db_path", mock_memory_db.db_path)

    policy.log_denial(
        tool_name="delete_file",
        params={"path": "C:\\Windows\\System32\\driver.sys"},
        reason="Security violation: System directory is protected",
    )

    denials = mock_memory_db.get_denials()
    assert len(denials) == 1
    assert denials[0]["tool_name"] == "delete_file"
    assert "driver.sys" in denials[0]["params_json"]
    assert "System directory is protected" in denials[0]["reason"]


def test_export_log_creates_valid_json_file(temp_db_path, tmp_path):
    """Test that export_log creates a valid JSON file containing all task records."""
    mem = Memory(db_path=temp_db_path)
    try:
        mem.log_task(
            user_request="find notes",
            plan={"steps": [{"tool_name": "find_files", "params": {"query": "notes"}}]},
            report={"success": True, "summary": "Found 1 file."},
            duration_ms=45,
            provider="gemini",
            model="gemini-1.5-flash",
        )
        mem.log_task(
            user_request="organize documents",
            plan={"steps": []},
            report={"success": False, "summary": "Cancelled."},
            duration_ms=20,
            provider="gemini",
            model="gemini-1.5-flash",
        )

        export_file = str(tmp_path / "tasks_export.json")
        mem.export_log(export_file)

        assert os.path.exists(export_file)

        with open(export_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["user_request"] == "find notes"
        assert data[0]["status"] == "success"
        assert data[0]["duration_ms"] == 45
        assert data[1]["user_request"] == "organize documents"
        assert data[1]["status"] == "cancelled"
    finally:
        mem.close()



