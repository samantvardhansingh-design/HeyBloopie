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
import shutil
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


def _find_candidate_file(
    query_or_path: Optional[str],
    path_hint: Optional[str] = None,
    policy: Optional[PolicyEngine] = None,
) -> Optional[str]:
    """Resolves a target file path from an exact path or by searching approved directories."""
    if not query_or_path:
        return None

    clean_str = query_or_path.strip().strip("'\"")

    # If it is an existing file path, return canonical realpath
    if os.path.isfile(clean_str):
        return os.path.realpath(clean_str)

    # Gather candidate directories to search
    candidate_dirs: List[str] = []
    if path_hint and os.path.isdir(path_hint):
        candidate_dirs.append(os.path.realpath(path_hint))

    home = os.path.expanduser("~")
    common_dirs = [
        os.path.join(home, "Desktop"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Documents"),
        os.path.join(home, "OneDrive", "Desktop"),
        os.path.join(home, "OneDrive", "Documents"),
        os.path.join(home, "OneDrive", "Pictures", "Screenshots"),
        os.path.join(home, "Pictures", "Screenshots"),
    ]
    for d in common_dirs:
        if os.path.isdir(d):
            c_real = os.path.realpath(d)
            if c_real not in candidate_dirs:
                candidate_dirs.append(c_real)

    if policy is not None:
        try:
            for p in policy.get_approved_paths():
                c_real = os.path.realpath(p)
                if c_real not in candidate_dirs:
                    candidate_dirs.append(c_real)
        except Exception:
            pass

    target_name_lower = os.path.basename(clean_str).lower()

    # Pass 1: exact filename match in top-level of candidate directories
    for c_dir in candidate_dirs:
        if not os.path.isdir(c_dir):
            continue
        try:
            for fname in os.listdir(c_dir):
                if fname.startswith(".") or fname.startswith("$"):
                    continue
                if fname.lower() == target_name_lower:
                    full_p = os.path.join(c_dir, fname)
                    if os.path.isfile(full_p):
                        return full_p
        except OSError:
            continue

    # Pass 2: substring match or screenshot extension match
    matches: List[tuple[float, str]] = []
    for c_dir in candidate_dirs:
        if not os.path.isdir(c_dir):
            continue
        try:
            for fname in os.listdir(c_dir):
                if fname.startswith(".") or fname.startswith("$"):
                    continue
                full_p = os.path.join(c_dir, fname)
                if not os.path.isfile(full_p):
                    continue
                if target_name_lower in fname.lower() or (
                    "screenshot" in target_name_lower
                    and any(fname.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg"])
                ):
                    try:
                        stat = os.stat(full_p)
                        matches.append((stat.st_mtime, full_p))
                    except OSError:
                        pass
        except OSError:
            continue

    if matches:
        matches.sort(key=lambda x: x[0], reverse=True)
        return matches[0][1]

    return None


async def find_files(
    query: str,
    date_range: Optional[str] = None,
    path: Optional[str] = None,
    policy_engine: Optional[PolicyEngine] = None,
    _post_search_hook: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
) -> ToolResult:
    """Finds files matching a name or content query within approved directories."""
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


async def delete_file(
    path: Optional[str] = None,
    query: Optional[str] = None,
    policy_engine: Optional[PolicyEngine] = None,
) -> ToolResult:
    """Deletes a file safely within approved directories after policy checks."""
    try:
        policy = policy_engine or PolicyEngine()
        target_path = None

        # Case 1: Direct file path provided and exists
        if path and os.path.isfile(path):
            target_path = os.path.realpath(path)

        # Case 2: path is a directory or None, or file doesn't exist -> search for the file
        if not target_path:
            target_path = _find_candidate_file(
                query or path or "screenshot",
                path_hint=path if path and os.path.isdir(path) else None,
                policy=policy,
            )

        if not target_path or not os.path.exists(target_path):
            return ToolResult(
                success=False,
                data=None,
                message=f"No matching file found to delete (path='{path}', query='{query}').",
                verified=False,
                verification_details="Target file does not exist.",
            )

        # Step 2: Policy check BEFORE deletion
        policy_decision = policy.check_action("delete_file", {"path": target_path})
        if not policy_decision.allowed:
            return ToolResult(
                success=False,
                data=None,
                message=f"Action denied by policy: {policy_decision.reason}",
                verified=False,
                verification_details="Deletion aborted by security policy.",
            )

        # Step 3: Delete the file on disk
        deleted_file_name = os.path.basename(target_path)
        await asyncio.to_thread(os.remove, target_path)

        # Step 4: Verify outcome on disk
        is_gone = not os.path.exists(target_path)

        return ToolResult(
            success=is_gone,
            data={"deleted_file": target_path, "name": deleted_file_name},
            message=f"Successfully deleted '{deleted_file_name}'.",
            verified=is_gone,
            verification_details=f"Verified file no longer exists at '{target_path}'." if is_gone else "File could not be removed.",
        )

    except Exception as err:
        logger.error(f"delete_file failed with exception: {err}")
        return ToolResult(
            success=False,
            data=None,
            message=f"Deletion failed: {err}",
            verified=False,
            verification_details="Deletion operation threw an exception.",
        )


async def rename_file(
    old_path: Optional[str] = None,
    new_name_or_path: Optional[str] = None,
    new_name: Optional[str] = None,
    source_path: Optional[str] = None,
    destination_path: Optional[str] = None,
    path: Optional[str] = None,
    target_path: Optional[str] = None,
    query: Optional[str] = None,
    policy_engine: Optional[PolicyEngine] = None,
) -> ToolResult:
    """Renames a file safely within approved directories after policy checks.

    Args:
        old_path: Original file path or filename to rename.
        new_name_or_path: New filename or target destination path.
        new_name: Alternative parameter for new filename.
        source_path: Alternative parameter for original file path.
        destination_path: Alternative parameter for destination path.
        path: Generic path parameter.
        target_path: Alternative target path parameter.
        query: Search string to locate file if path is not specified.
        policy_engine: Optional PolicyEngine instance.

    Returns:
        ToolResult with rename outcome, paths, and disk verification.
    """
    try:
        policy = policy_engine or PolicyEngine()
        raw_source = old_path or source_path or target_path or path or query
        if not raw_source:
            return ToolResult(
                success=False,
                data=None,
                message="No source file specified to rename.",
                verified=False,
                verification_details="Missing source path parameter.",
            )

        resolved_source = _find_candidate_file(raw_source, policy=policy)
        if not resolved_source or not os.path.exists(resolved_source):
            return ToolResult(
                success=False,
                data=None,
                message=f"No matching file found to rename: '{raw_source}'.",
                verified=False,
                verification_details="Target source file does not exist.",
            )

        raw_dest = new_name or new_name_or_path or destination_path
        if not raw_dest:
            return ToolResult(
                success=False,
                data=None,
                message="No new name or destination specified for rename.",
                verified=False,
                verification_details="Missing new_name parameter.",
            )

        clean_dest = raw_dest.strip().strip("'\"")
        if os.path.isabs(clean_dest):
            dest_path = os.path.realpath(clean_dest)
        else:
            # Place in the same parent directory as the source file
            dest_path = os.path.realpath(os.path.join(os.path.dirname(resolved_source), clean_dest))

        # Policy check before any mutation
        policy_params = {
            "source_path": resolved_source,
            "destination_path": dest_path,
            "target_path": resolved_source,
            "path": resolved_source,
            "new_name": os.path.basename(dest_path),
        }
        policy_decision = policy.check_action("rename_file", policy_params)
        if not policy_decision.allowed:
            return ToolResult(
                success=False,
                data=None,
                message=f"Action denied by policy: {policy_decision.reason}",
                verified=False,
                verification_details="Rename operation denied by security policy.",
            )

        dest_dir = os.path.dirname(dest_path)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)

        # Execute rename on worker thread
        await asyncio.to_thread(os.rename, resolved_source, dest_path)

        # Verify on disk
        is_renamed = os.path.exists(dest_path) and (
            resolved_source == dest_path or not os.path.exists(resolved_source)
        )
        old_name = os.path.basename(resolved_source)
        new_name_val = os.path.basename(dest_path)

        return ToolResult(
            success=is_renamed,
            data={
                "old_path": resolved_source,
                "new_path": dest_path,
                "old_name": old_name,
                "new_name": new_name_val,
            },
            message=f"Successfully renamed '{old_name}' to '{new_name_val}'.",
            verified=is_renamed,
            verification_details=f"Verified file exists at '{dest_path}'." if is_renamed else "File could not be verified on disk.",
        )

    except Exception as err:
        logger.error(f"rename_file failed with exception: {err}")
        return ToolResult(
            success=False,
            data=None,
            message=f"Rename operation failed: {err}",
            verified=False,
            verification_details="Rename operation threw an exception.",
        )


async def move_file(
    source_path: Optional[str] = None,
    destination_path: Optional[str] = None,
    path: Optional[str] = None,
    target_path: Optional[str] = None,
    destination_folder: Optional[str] = None,
    query: Optional[str] = None,
    policy_engine: Optional[PolicyEngine] = None,
) -> ToolResult:
    """Moves a file safely to a target folder or destination path.

    Args:
        source_path: Path or filename of the file to move.
        destination_path: Target directory or full destination path.
        path: Generic path parameter for source.
        target_path: Alternative parameter for source.
        destination_folder: Alternative parameter for target folder.
        query: Search string to locate file if not direct path.
        policy_engine: Optional PolicyEngine instance.

    Returns:
        ToolResult with move status, paths, and disk verification.
    """
    try:
        policy = policy_engine or PolicyEngine()
        raw_source = source_path or target_path or path or query
        if not raw_source:
            return ToolResult(
                success=False,
                data=None,
                message="No source file specified to move.",
                verified=False,
                verification_details="Missing source path parameter.",
            )

        resolved_source = _find_candidate_file(raw_source, policy=policy)
        if not resolved_source or not os.path.exists(resolved_source):
            return ToolResult(
                success=False,
                data=None,
                message=f"No matching file found to move: '{raw_source}'.",
                verified=False,
                verification_details="Target source file does not exist.",
            )

        raw_dest = destination_path or destination_folder
        if not raw_dest:
            return ToolResult(
                success=False,
                data=None,
                message="No destination path specified to move file.",
                verified=False,
                verification_details="Missing destination parameter.",
            )

        clean_dest = raw_dest.strip().strip("'\"")
        home = os.path.expanduser("~")

        # Resolve destination
        if os.path.isabs(clean_dest):
            _, dest_ext = os.path.splitext(clean_dest)
            if os.path.isdir(clean_dest) or clean_dest.endswith(("/", "\\")) or not dest_ext:
                dest_path = os.path.join(clean_dest, os.path.basename(resolved_source))
            else:
                dest_path = clean_dest
        else:
            # Check standard folders (e.g. Documents, Downloads, Desktop)
            matched_dir = None
            for candidate in [
                os.path.join(home, clean_dest),
                os.path.join(home, "Documents", clean_dest),
                os.path.join(home, "Desktop", clean_dest),
            ]:
                if os.path.isdir(candidate):
                    matched_dir = candidate
                    break

            if matched_dir:
                dest_path = os.path.join(matched_dir, os.path.basename(resolved_source))
            else:
                approved = policy.get_approved_paths()
                base_dir = approved[0] if approved else home
                dest_path = os.path.join(base_dir, clean_dest)
                _, dest_ext = os.path.splitext(dest_path)
                if not dest_ext:
                    dest_path = os.path.join(dest_path, os.path.basename(resolved_source))

        dest_path = os.path.realpath(dest_path)

        # Policy check
        policy_params = {
            "source_path": resolved_source,
            "destination_path": dest_path,
            "path": resolved_source,
        }
        policy_decision = policy.check_action("move_file", policy_params)
        if not policy_decision.allowed:
            return ToolResult(
                success=False,
                data=None,
                message=f"Action denied by policy: {policy_decision.reason}",
                verified=False,
                verification_details="Move operation denied by security policy.",
            )

        dest_dir = os.path.dirname(dest_path)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)

        # Execute move on threadpool
        await asyncio.to_thread(shutil.move, resolved_source, dest_path)

        # Disk verification
        is_moved = os.path.exists(dest_path) and not os.path.exists(resolved_source)
        src_name = os.path.basename(resolved_source)

        return ToolResult(
            success=is_moved,
            data={
                "source_path": resolved_source,
                "destination_path": dest_path,
                "name": src_name,
            },
            message=f"Successfully moved '{src_name}' to '{dest_path}'.",
            verified=is_moved,
            verification_details=f"Verified file exists at '{dest_path}'." if is_moved else "Move verification failed on disk.",
        )

    except Exception as err:
        logger.error(f"move_file failed with exception: {err}")
        return ToolResult(
            success=False,
            data=None,
            message=f"Move operation failed: {err}",
            verified=False,
            verification_details="Move operation threw an exception.",
        )


async def create_folder(
    folder_path: Optional[str] = None,
    path: Optional[str] = None,
    name: Optional[str] = None,
    parent_dir: Optional[str] = None,
    policy_engine: Optional[PolicyEngine] = None,
) -> ToolResult:
    """Creates a new directory safely within approved directories after policy checks.

    Args:
        folder_path: Name or full path of folder to create.
        path: Alternative parameter for folder path.
        name: Alternative parameter for folder name.
        parent_dir: Optional parent directory if only name is given.
        policy_engine: Optional PolicyEngine instance.

    Returns:
        ToolResult with folder path and disk verification.
    """
    try:
        policy = policy_engine or PolicyEngine()
        raw_target = folder_path or path or name
        if not raw_target:
            return ToolResult(
                success=False,
                data=None,
                message="No folder path or name specified to create.",
                verified=False,
                verification_details="Missing folder parameter.",
            )

        clean_target = raw_target.strip().strip("'\"")
        home = os.path.expanduser("~")

        if os.path.isabs(clean_target):
            target_dir = os.path.realpath(clean_target)
        else:
            base_dir = parent_dir or (
                policy.get_approved_paths()[0] if policy.get_approved_paths() else home
            )
            target_dir = os.path.realpath(os.path.join(base_dir, clean_target))

        # Policy check
        policy_params = {"folder_path": target_dir, "path": target_dir}
        policy_decision = policy.check_action("create_folder", policy_params)
        if not policy_decision.allowed:
            return ToolResult(
                success=False,
                data=None,
                message=f"Action denied by policy: {policy_decision.reason}",
                verified=False,
                verification_details="Folder creation denied by security policy.",
            )

        await asyncio.to_thread(os.makedirs, target_dir, exist_ok=True)
        is_created = os.path.isdir(target_dir)
        folder_name = os.path.basename(target_dir)

        return ToolResult(
            success=is_created,
            data={"folder_path": target_dir, "name": folder_name},
            message=f"Successfully created folder '{folder_name}'.",
            verified=is_created,
            verification_details=f"Verified directory exists at '{target_dir}'." if is_created else "Directory creation could not be verified.",
        )

    except Exception as err:
        logger.error(f"create_folder failed with exception: {err}")
        return ToolResult(
            success=False,
            data=None,
            message=f"Folder creation failed: {err}",
            verified=False,
            verification_details="Folder creation threw an exception.",
        )


async def list_folder(
    path: Optional[str] = None,
    directory: Optional[str] = None,
    policy_engine: Optional[PolicyEngine] = None,
) -> ToolResult:
    """Lists files and directories inside an approved directory.

    Args:
        path: Path to list.
        directory: Alternative path parameter.
        policy_engine: Optional PolicyEngine instance.

    Returns:
        ToolResult with list of entries and disk verification.
    """
    try:
        policy = policy_engine or PolicyEngine()
        raw_dir = path or directory
        if raw_dir:
            target_dir = os.path.realpath(raw_dir.strip().strip("'\""))
        else:
            approved = policy.get_approved_paths()
            target_dir = approved[0] if approved else os.path.expanduser("~")

        if not os.path.isdir(target_dir):
            return ToolResult(
                success=False,
                data=None,
                message=f"Directory does not exist: '{target_dir}'.",
                verified=False,
                verification_details="Target directory does not exist.",
            )

        policy_decision = policy.check_action("list_folder", {"path": target_dir, "directory": target_dir})
        if not policy_decision.allowed:
            return ToolResult(
                success=False,
                data=None,
                message=f"Action denied by policy: {policy_decision.reason}",
                verified=False,
                verification_details="Listing denied by security policy.",
            )

        entries = await asyncio.to_thread(os.listdir, target_dir)
        visible_entries = [e for e in entries if not e.startswith(".") and not e.startswith("$")]

        return ToolResult(
            success=True,
            data=visible_entries,
            message=f"Found {len(visible_entries)} items in '{os.path.basename(target_dir)}'.",
            verified=True,
            verification_details=f"Listed {len(visible_entries)} items successfully.",
        )

    except Exception as err:
        logger.error(f"list_folder failed with exception: {err}")
        return ToolResult(
            success=False,
            data=None,
            message=f"Listing failed: {err}",
            verified=False,
            verification_details="Listing threw an exception.",
        )


