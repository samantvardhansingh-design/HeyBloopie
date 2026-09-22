"""Unit tests for the HeyBloopie Sandboxed Tool Layer."""

import os
import shutil
import sys
import tempfile
import time
from unittest.mock import MagicMock

import pytest

# Ensure python directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from python.policy import PolicyEngine, PolicyResult
from python.tools import ToolResult, find_files


@pytest.fixture
def sandbox_env():
    """Sets up a temporary sandbox directory and PolicyEngine for isolated tool testing."""
    temp_dir = tempfile.mkdtemp()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
        db_path = tmp_db.name

    policy = PolicyEngine(db_path=db_path)
    policy.set_approved_paths([temp_dir])

    yield temp_dir, policy

    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_find_files_by_name(sandbox_env):
    """TEST 1: find_files returns matching files by name."""
    temp_dir, policy = sandbox_env

    # Create 5 files
    file_names = ["report_1.txt", "report_2.txt", "notes.txt", "image.png", "data.csv"]
    for fname in file_names:
        with open(os.path.join(temp_dir, fname), "w", encoding="utf-8") as f:
            f.write(f"Sample content for {fname}")

    result = await find_files("report", path=temp_dir, policy_engine=policy)

    assert result.success is True
    assert len(result.data) == 2
    matched_names = {item["name"] for item in result.data}
    assert matched_names == {"report_1.txt", "report_2.txt"}
    assert result.verified is True
    assert "All 2 files verified" in result.verification_details


@pytest.mark.asyncio
async def test_find_files_by_content(sandbox_env):
    """TEST 2: find_files returns matching files by content."""
    temp_dir, policy = sandbox_env

    target_file = os.path.join(temp_dir, "physics_notes.txt")
    with open(target_file, "w", encoding="utf-8") as f:
        f.write("Important breakthroughs in quantum physics research and computing.")

    other_file = os.path.join(temp_dir, "recipe.txt")
    with open(other_file, "w", encoding="utf-8") as f:
        f.write("Ingredients: chocolate, butter, sugar.")

    result = await find_files("quantum", path=temp_dir, policy_engine=policy)

    assert result.success is True
    assert len(result.data) == 1
    assert result.data[0]["name"] == "physics_notes.txt"
    assert "quantum" in result.data[0]["snippet"].lower()
    assert result.verified is True


@pytest.mark.asyncio
async def test_find_files_respects_policy(sandbox_env):
    """TEST 3: find_files respects the policy engine."""
    temp_dir, policy = sandbox_env

    mock_policy = MagicMock(spec=PolicyEngine)
    mock_policy.check_action.return_value = PolicyResult(
        allowed=False,
        risk_level="low",
        reason="Tool find_files is temporarily locked by policy administrator.",
        requires_confirmation=False,
    )

    result = await find_files("report", path=temp_dir, policy_engine=mock_policy)

    assert result.success is False
    assert result.data is None
    assert "denied" in result.message.lower()


@pytest.mark.asyncio
async def test_find_files_respects_date_range(sandbox_env):
    """TEST 4: find_files respects date_range."""
    temp_dir, policy = sandbox_env

    yesterday_file = os.path.join(temp_dir, "yesterday_doc.txt")
    with open(yesterday_file, "w", encoding="utf-8") as f:
        f.write("Created yesterday.")

    # Set modification date to ~24 hours ago
    past_timestamp = time.time() - 86400
    os.utime(yesterday_file, (past_timestamp, past_timestamp))

    result = await find_files("", date_range="yesterday", path=temp_dir, policy_engine=policy)

    assert result.success is True
    assert any(item["name"] == "yesterday_doc.txt" for item in result.data)
    assert result.verified is True


@pytest.mark.asyncio
async def test_find_files_no_matches(sandbox_env):
    """TEST 5: find_files returns empty list when no matches."""
    temp_dir, policy = sandbox_env

    result = await find_files("zzzznonexistent", path=temp_dir, policy_engine=policy)

    assert result.success is True
    assert result.data == []
    assert result.verified is True
    assert "Found 0 files" in result.message


@pytest.mark.asyncio
async def test_find_files_verifies_results(sandbox_env):
    """TEST 6: find_files verifies results."""
    temp_dir, policy = sandbox_env

    disappearing_file = os.path.join(temp_dir, "temporary_doc.txt")
    with open(disappearing_file, "w", encoding="utf-8") as f:
        f.write("This file will vanish during verification.")

    def delete_file_between_steps(found_items):
        if os.path.exists(disappearing_file):
            os.remove(disappearing_file)

    result = await find_files(
        "temporary_doc",
        path=temp_dir,
        policy_engine=policy,
        _post_search_hook=delete_file_between_steps,
    )

    # Search found it, but disk verification must detect it was removed
    assert result.verified is False
    assert "verification failed" in result.verification_details.lower()
    assert disappearing_file in result.verification_details


@pytest.mark.asyncio
async def test_find_files_handles_unapproved_path(sandbox_env):
    """TEST 7: find_files handles a path outside approved directories."""
    temp_dir, policy = sandbox_env

    unapproved_path = "C:\\RandomUnauthorizedDir\\subfolder"

    result = await find_files("report", path=unapproved_path, policy_engine=policy)

    assert result.success is False
    assert result.data is None
    assert "outside" in result.message.lower()
