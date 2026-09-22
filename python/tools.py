"""HeyBloopie Sandboxed Tool Layer.

This module contains isolated, single-purpose, asynchronous file operations.
Each tool function executes deterministically without any knowledge of AI models, prompt
engineering, or planning logic.

Architectural & Performance Constraints:
- Every tool MUST be asynchronous and non-blocking (asyncio.to_thread for disk I/O).
- Every tool MUST call policy.check_action() BEFORE performing any file access.
- Every tool MUST verify outcome on disk and return a standardized ToolResult.
- Tools NEVER import or communicate with AI providers.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
import os
from typing import Any, Callable, Dict, List, Optional

from python.policy import PolicyEngine, PolicyResult

logger = logging.getLogger("heybloopie.tools")

MAX_RESULTS = 50
MAX_CONTENT_BYTES = 64 * 1024  # Read at most first 64 KB of text files

TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".py", ".js", ".ts",
    ".html", ".css", ".xml", ".yaml", ".yml"
}


@dataclass
class ToolResult:
    """Standardized result returned by all tools in the Tool Layer."""
    success: bool
    data: Any
    message: str
    verified: bool
    verification_details: str


def _matches_date_range(mtime: float, date_range: Optional[str]) -> bool:
    """Evaluates whether a file modification timestamp matches the requested date range."""
    if not date_range:
        return True

    range_clean = date_range.strip().lower()
    now = datetime.now()
    today_midnight = datetime(now.year, now.month, now.day)
    yesterday_midnight = today_midnight - timedelta(days=1)

    if range_clean == "today":
        return mtime >= today_midnight.timestamp()
    elif range_clean == "yesterday":
        return (yesterday_midnight.timestamp() <= mtime < today_midnight.timestamp()) or (
            now.timestamp() - 172800 <= mtime <= now.timestamp() - 43200
        )
    elif range_clean == "last_week":
        return mtime >= (now - timedelta(days=7)).timestamp()
    elif range_clean == "last_month":
        return mtime >= (now - timedelta(days=30)).timestamp()
    elif range_clean == "last_year":
        return mtime >= (now - timedelta(days=365)).timestamp()

    return True


def _sync_find_files(
    directories: List[str],
    query: str,
    date_range: Optional[str] = None,
    max_results: int = MAX_RESULTS,
) -> List[Dict[str, Any]]:
    """Synchronous file-system walker executed within a worker thread."""
    query_lower = query.strip().lower() if query else ""
    results = []

    for root_dir in directories:
        if not os.path.exists(root_dir):
            continue

        for dirpath, dirnames, filenames in os.walk(root_dir):
            # Skip hidden directories and system volume folders
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".") and not d.startswith("$") and d != "System Volume Information"
            ]

            for fname in filenames:
                if fname.startswith("."):
                    continue

                full_path = os.path.join(dirpath, fname)

                try:
                    stat = os.stat(full_path)
                except OSError:
                    continue

                # 1. Check date range filter
                if not _matches_date_range(stat.st_mtime, date_range):
                    continue

                # 2. Check filename or content match
                matched = False
                snippet = ""

                # Filename match (case-insensitive substring match)
                if query_lower == "" or query_lower in fname.lower():
                    matched = True

                # File content match (for supported text files only)
                if not matched and query_lower:
                    _, ext = os.path.splitext(fname)
                    if ext.lower() in TEXT_EXTENSIONS:
                        try:
                            with open(full_path, "rb") as f:
                                raw_bytes = f.read(MAX_CONTENT_BYTES)
                            text_content = raw_bytes.decode("utf-8", errors="ignore")
                            idx = text_content.lower().find(query_lower)
                            if idx != -1:
                                matched = True
                                start = max(0, idx - 40)
                                end = min(len(text_content), idx + len(query_lower) + 40)
                                snippet = text_content[start:end].strip()
                        except Exception:
                            pass

                if matched:
                    results.append({
                        "path": full_path,
                        "name": fname,
                        "size": stat.st_size,
                        "modified_date": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        "snippet": snippet,
                    })

                    if len(results) >= max_results:
                        return results

    return results


async def find_files(
    query: str,
    date_range: Optional[str] = None,
    path: Optional[str] = None,
    policy_engine: Optional[PolicyEngine] = None,
    _post_search_hook: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
) -> ToolResult:
    """Finds files matching a name or content query within approved directories.

    Args:
        query: Search string for filename or content match.
        date_range: Optional filter ('today', 'yesterday', 'last_week', 'last_month', 'last_year').
        path: Optional specific directory to search within (must be in approved directories).
        policy_engine: Optional policy engine instance (defaults to standard instance).
        _post_search_hook: Optional test hook called between search and verification.

    Returns:
        ToolResult with found files, verification status, and details.
    """
    try:
        policy = policy_engine or PolicyEngine()

        # Step 1: Policy check BEFORE any file system access
        policy_params = {"query": query}
        if path is not None:
            policy_params["path"] = path

        policy_decision = policy.check_action("find_files", policy_params)
        if not policy_decision.allowed:
            return ToolResult(
                success=False,
                data=None,
                message="Action denied by policy: " + policy_decision.reason,
                verified=False,
                verification_details="",
            )

        # Step 2: Determine target directories
        if path is not None:
            directories = [os.path.realpath(path)]
        else:
            directories = policy.get_approved_paths()

        # Execute file walker in threadpool to keep event loop responsive
        found_files = await asyncio.to_thread(
            _sync_find_files,
            directories=directories,
            query=query,
            date_range=date_range,
            max_results=MAX_RESULTS,
        )

        # Test hook to simulate file mutation between search and verification
        if _post_search_hook is not None:
            _post_search_hook(found_files)

        # Step 3: Verify results exist on disk
        verified_items = []
        failed_paths = []
        for item in found_files:
            if os.path.exists(item["path"]):
                verified_items.append(item)
            else:
                failed_paths.append(item["path"])

        all_verified = len(failed_paths) == 0
        if all_verified:
            verification_details = f"All {len(verified_items)} files verified."
        else:
            verification_details = (
                f"Verification failed: {len(failed_paths)} file(s) no longer exist: {', '.join(failed_paths)}"
            )

        # Step 4: Return structured ToolResult
        return ToolResult(
            success=True,
            data=verified_items,
            message=f"Found {len(verified_items)} files matching '{query}'.",
            verified=all_verified,
            verification_details=verification_details,
        )

    except Exception as err:
        logger.error(f"find_files failed with exception: {err}")
        return ToolResult(
            success=False,
            data=None,
            message=f"Search operation failed: {err}",
            verified=False,
            verification_details="Search aborted due to unexpected error.",
        )


async def move_file(source_path: str, destination_path: str) -> Dict[str, Any]:
    """Moves a file from a source path to a destination path asynchronously."""
    raise NotImplementedError("move_file will be implemented in subsequent phase.")


async def rename_file(target_path: str, new_name: str) -> Dict[str, Any]:
    """Renames an existing file within its parent directory."""
    raise NotImplementedError("rename_file will be implemented in subsequent phase.")


async def create_folder(folder_path: str) -> Dict[str, Any]:
    """Creates a new folder or nested directory path."""
    raise NotImplementedError("create_folder will be implemented in subsequent phase.")


async def list_folder(folder_path: str, recursive: bool = False, max_depth: int = 1) -> Dict[str, Any]:
    """Lists entries and subdirectories within an approved folder."""
    raise NotImplementedError("list_folder will be implemented in subsequent phase.")


async def get_file_metadata(file_path: str) -> Dict[str, Any]:
    """Retrieves file system attributes and metadata for a specific path."""
    raise NotImplementedError("get_file_metadata will be implemented in subsequent phase.")


async def read_file_content(file_path: str, max_bytes: int = 1048576) -> Dict[str, Any]:
    """Reads safe, text-based file contents up to a specified maximum byte limit."""
    raise NotImplementedError("read_file_content will be implemented in subsequent phase.")
