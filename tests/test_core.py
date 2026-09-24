"""Unit and integration tests for the HeyBloopie Core Loop and Planner.

Tests cover:
- TEST 1: The Planner returns a valid Plan for a supported request.
- TEST 2: The Planner returns an empty Plan for an unsupported request.
- TEST 3: The Planner does not import or call any tool.
- TEST 4: The Core executes a low-risk plan without confirmation.
- TEST 5: The Core respects the Policy Engine.
- TEST 6: The Core recovers from a tool failure.
- TEST 7: The Core reports partial success.
- TEST 8: The Core returns "I can't do that yet" for an empty plan.
"""

import ast
import json
import os
import sys
import pytest

# Ensure python directory is accessible
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from python import core, planner, policy, provider, tools


@pytest.mark.asyncio
async def test_planner_returns_valid_plan_for_supported_request(monkeypatch):
    """TEST 1: The Planner returns a valid Plan for a supported request."""
    mock_json_response = json.dumps({
        "steps": [
            {
                "tool_name": "find_files",
                "params": {"query": "report"},
                "description": "Find report files in approved folders"
            }
        ],
        "summary": "Find files matching 'report'"
    })

    async def mock_generate_plan(prompt: str) -> str:
        return mock_json_response

    monkeypatch.setattr(provider, "generate_plan", mock_generate_plan)

    plan = await planner.create_plan("find my report")
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "find_files"
    assert plan.steps[0].risk_level == "low"
    assert plan.steps[0].params == {"query": "report"}
    assert plan.requires_confirmation is False


@pytest.mark.asyncio
async def test_planner_returns_empty_plan_for_unsupported_request(monkeypatch):
    """TEST 2: The Planner returns an empty Plan for an unsupported request."""
    mock_json_response = json.dumps({
        "steps": [],
        "summary": "I cannot send emails. I am currently limited to local file operations."
    })

    async def mock_generate_plan(prompt: str) -> str:
        return mock_json_response

    monkeypatch.setattr(provider, "generate_plan", mock_generate_plan)

    plan = await planner.create_plan("send an email")
    assert len(plan.steps) == 0
    assert plan.requires_confirmation is False


def test_planner_does_not_import_or_call_tools():
    """TEST 3: The Planner does not import or call any tool."""
    planner_file = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "python", "planner.py"))
    with open(planner_file, "r", encoding="utf-8") as f:
        source_code = f.read()

    tree = ast.parse(source_code)
    imported_modules = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.append(node.module)

    for mod in imported_modules:
        parts = mod.split(".")
        assert "tools" not in parts, f"Illegal import of tools module in planner.py: {mod}"
        assert "policy" not in parts, f"Illegal import of policy module in planner.py: {mod}"


@pytest.mark.asyncio
async def test_core_executes_low_risk_plan_without_confirmation(monkeypatch):
    """TEST 4: The Core executes a low-risk plan without confirmation."""
    step = planner.PlanStep(
        tool_name="find_files",
        params={"query": "report"},
        risk_level="low",
        description="Find files matching report",
    )
    plan = planner.Plan(
        steps=[step],
        summary="Search for report files",
        requires_confirmation=False,
    )

    async def mock_create_plan(user_request: str, available_tools=None):
        return plan

    async def mock_find_files(**kwargs):
        return tools.ToolResult(
            success=True,
            data=[{"name": "report.pdf", "path": "C:\\Users\\test\\report.pdf"}],
            message="Found 1 file",
            verified=True,
            verification_details="Verified file exists",
        )

    monkeypatch.setattr(planner, "create_plan", mock_create_plan)
    monkeypatch.setattr(tools, "find_files", mock_find_files)
    monkeypatch.setitem(core.TOOL_DISPATCH, "find_files", mock_find_files)

    report = await core.run("find my report")
    assert report.success is True
    assert report.steps_succeeded == 1
    assert report.steps_failed == 0
    assert len(report.exceptions) == 0
    assert len(report.details) == 1
    assert report.details[0]["step"] == "find_files"


@pytest.mark.asyncio
async def test_core_respects_policy_engine(monkeypatch):
    """TEST 5: The Core respects the Policy Engine."""
    step = planner.PlanStep(
        tool_name="find_files",
        params={"query": "report"},
        risk_level="low",
        description="Find files matching report",
    )
    plan = planner.Plan(
        steps=[step],
        summary="Search for report files",
        requires_confirmation=False,
    )

    async def mock_create_plan(user_request: str, available_tools=None):
        return plan

    def mock_check_action(tool_name: str, params=None):
        return policy.PolicyResult(
            allowed=False,
            risk_level="low",
            reason="Blocked by security policy: Directory not approved",
            requires_confirmation=False,
        )

    monkeypatch.setattr(planner, "create_plan", mock_create_plan)
    monkeypatch.setattr(policy, "check_action", mock_check_action)

    report = await core.run("find my report")
    assert report.success is False
    assert len(report.exceptions) > 0
    assert report.steps_failed == 1
    assert "Blocked by security policy" in report.exceptions[0]["reason"]


@pytest.mark.asyncio
async def test_core_recovers_from_tool_failure(monkeypatch):
    """TEST 6: The Core recovers from a tool failure."""
    step = planner.PlanStep(
        tool_name="find_files",
        params={"query": "report"},
        risk_level="low",
        description="Find files matching report",
    )
    plan = planner.Plan(
        steps=[step],
        summary="Search for report files",
        requires_confirmation=False,
    )

    async def mock_create_plan(user_request: str, available_tools=None):
        return plan

    call_count = 0

    async def mock_find_files(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return tools.ToolResult(
                success=False,
                data=None,
                message="Transient file lock error",
                verified=False,
                verification_details="",
            )
        return tools.ToolResult(
            success=True,
            data=[{"name": "report.pdf", "path": "C:\\Users\\test\\report.pdf"}],
            message="Found 1 file",
            verified=True,
            verification_details="Verified file exists",
        )

    monkeypatch.setattr(planner, "create_plan", mock_create_plan)
    monkeypatch.setattr(tools, "find_files", mock_find_files)
    monkeypatch.setitem(core.TOOL_DISPATCH, "find_files", mock_find_files)

    report = await core.run("find my report")
    assert report.success is True
    assert report.steps_succeeded == 1
    assert call_count == 2
    assert len(report.exceptions) == 0


@pytest.mark.asyncio
async def test_core_reports_partial_success(monkeypatch):
    """TEST 7: The Core reports partial success."""
    step1 = planner.PlanStep(
        tool_name="find_files",
        params={"query": "report1"},
        risk_level="low",
        description="Find report 1",
    )
    step2 = planner.PlanStep(
        tool_name="find_files",
        params={"query": "report2"},
        risk_level="low",
        description="Find report 2",
    )
    plan = planner.Plan(
        steps=[step1, step2],
        summary="Find both reports",
        requires_confirmation=False,
    )

    async def mock_create_plan(user_request: str, available_tools=None):
        return plan

    async def mock_find_files(query, **kwargs):
        if query == "report1":
            return tools.ToolResult(
                success=True,
                data=[{"name": "report1.pdf", "path": "C:\\Users\\test\\report1.pdf"}],
                message="Found 1 file",
                verified=True,
                verification_details="",
            )
        else:
            return tools.ToolResult(
                success=False,
                data=None,
                message="Permanent IO error on report 2",
                verified=False,
                verification_details="",
            )

    monkeypatch.setattr(planner, "create_plan", mock_create_plan)
    monkeypatch.setattr(tools, "find_files", mock_find_files)
    monkeypatch.setitem(core.TOOL_DISPATCH, "find_files", mock_find_files)

    report = await core.run("find my reports")
    assert report.success is False
    assert report.steps_succeeded == 1
    assert report.steps_failed == 1
    assert len(report.exceptions) == 1
    assert "partial success" in report.summary.lower()


@pytest.mark.asyncio
async def test_core_returns_cannot_do_that_yet_for_empty_plan(monkeypatch):
    """TEST 8: The Core returns 'I can't do that yet' for an empty plan."""
    empty_plan = planner.Plan(
        steps=[],
        summary="I cannot send emails.",
        requires_confirmation=False,
    )

    async def mock_create_plan(user_request: str, available_tools=None):
        return empty_plan

    monkeypatch.setattr(planner, "create_plan", mock_create_plan)

    report = await core.run("send an email")
    assert "I can't do that yet" in report.summary
    assert report.success is False
    assert report.total_steps == 0
    assert report.steps_succeeded == 0


@pytest.mark.asyncio
async def test_planner_retries_on_malformed_json(monkeypatch):
    """Verifies that planner retries once if JSON is malformed and recovers."""
    call_count = 0

    async def mock_generate_plan(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "This is not valid JSON at all."
        return json.dumps({
            "steps": [{"tool_name": "find_files", "params": {"query": "notes"}, "description": "Search notes"}],
            "summary": "Find notes"
        })

    monkeypatch.setattr(provider, "generate_plan", mock_generate_plan)

    plan = await planner.create_plan("find notes")
    assert call_count == 2
    assert len(plan.steps) == 1
    assert plan.steps[0].tool_name == "find_files"


@pytest.mark.asyncio
async def test_planner_fails_after_two_malformed_json_attempts(monkeypatch):
    """Verifies that planner falls back to empty plan if JSON fails twice."""
    call_count = 0

    async def mock_generate_plan(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        return "Still broken JSON"

    monkeypatch.setattr(provider, "generate_plan", mock_generate_plan)

    plan = await planner.create_plan("do something")
    assert call_count == 2
    assert len(plan.steps) == 0
    assert "couldn't understand" in plan.summary.lower()


@pytest.mark.asyncio
async def test_core_handles_user_denial_on_confirmation(monkeypatch):
    """Verifies that Core halts with 'Cancelled.' if user denies confirmation."""
    step = planner.PlanStep(
        tool_name="delete_file",
        params={"path": "C:\\temp\\old.log"},
        risk_level="high",
        description="Delete log file",
    )
    plan = planner.Plan(
        steps=[step],
        summary="Delete log file",
        requires_confirmation=True,
    )

    async def mock_create_plan(user_request: str, available_tools=None):
        return plan

    monkeypatch.setattr(planner, "create_plan", mock_create_plan)
    monkeypatch.setattr(core, "show_preview", lambda p: False)

    report = await core.run("delete my old log")
    assert report.success is False
    assert report.summary == "Cancelled."
    assert report.steps_succeeded == 0

