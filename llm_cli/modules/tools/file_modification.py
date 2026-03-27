# llm_cli/modules/tools/file_modification.py

import difflib
import re
import threading
from typing import Any

from llm_cli.modules.tool_registry import tool

from .common import file_tool_handler, validate_path

# Upper bound on the number of regex tokens produced from the search block.
# A legitimate diff hunk rarely exceeds a few hundred tokens; a much larger
# value is a strong signal of a crafted / degenerate input.
_FUZZY_MAX_TOKENS = 300

# Wall-clock seconds allowed for a single fuzzy re.finditer() call.
# Regex backtracking is CPU-bound, so this guards against ReDoS.
_FUZZY_TIMEOUT_SEC = 5.0


def _fuzzy_finditer(pattern: str, content: str) -> list[re.Match[str]] | None:
    """
    Run re.finditer(pattern, content, re.DOTALL) with a hard wall-clock
    timeout to prevent ReDoS.

    Returns the list of matches on success, or None if the timeout fires.
    The timeout is implemented via a background thread: the main thread
    joins for at most _FUZZY_TIMEOUT_SEC seconds and treats a still-running
    worker as a ReDoS indicator.

    Note: the worker thread itself cannot be forcibly killed in CPython, so
    it will keep running in the background until the GIL allows it to be
    interrupted.  This is an accepted trade-off for pure-Python regex; the
    important outcome is that *the caller* is unblocked promptly.
    """
    result: list[re.Match[str]] = []
    timed_out = threading.Event()

    def _run() -> None:
        try:
            result.extend(re.finditer(pattern, content, re.DOTALL))
        except Exception:
            pass

    worker = threading.Thread(target=_run, daemon=True)
    worker.start()
    worker.join(timeout=_FUZZY_TIMEOUT_SEC)

    if worker.is_alive():
        timed_out.set()
        return None  # Signal timeout to the caller
    return result


def validate_create_or_overwrite_file(path: str, **_kwargs: object) -> bool | str:
    """Pre-validates that the target path is writable before user approval."""
    try:
        p = validate_path(path)
        # Verify the parent directory is accessible (or can be created)
        parent = p.parent
        if parent.exists() and not parent.is_dir():
            return f"Error: Parent path '{parent}' is not a directory."
        return True
    except Exception as e:
        return f"Error during path validation: {e}"


def validate_edit_file(path: str, search: str, **_kwargs: str) -> bool | str:
    """Validates that the search block exists in the file before approval."""
    try:
        p = validate_path(path)
        if not p.is_file():
            return f"Error: '{path}' is not a file."

        content = p.read_text(encoding="utf-8")
        if search in content:
            count = content.count(search)
            if count > 1:
                return f"Error: {count} matches found in '{path}'. Use a more unique search block."
            return True

        # Fuzzy match check
        stripped_search = search.strip()
        if not stripped_search:
            return f"Error: 'search' block is empty or contains only whitespace (path: '{path}')."

        tokens = re.split(r"(\s+|[^\w])", stripped_search)
        pattern_parts = [re.escape(t) for t in tokens if t and not t.isspace()]
        if not pattern_parts:
            return f"Error: 'search' block contains no usable tokens for matching in '{path}'."

        # Guard against ReDoS: refuse excessively complex search blocks.
        if len(pattern_parts) > _FUZZY_MAX_TOKENS:
            return (
                f"Error: 'search' block is too large for fuzzy matching "
                f"({len(pattern_parts)} tokens, max {_FUZZY_MAX_TOKENS}). "
                "Use a shorter, more precise block."
            )

        pattern = r"\s*".join(pattern_parts)
        matches = _fuzzy_finditer(pattern, content)

        if matches is None:
            return (
                "Error: Fuzzy match timed out. "
                "The 'search' block may be too complex or the file too large. "
                "Use a shorter, more precise block."
            )
        if not matches:
            return f"Error: The 'search' block was not found exactly or fuzzily in '{path}'."
        if len(matches) > 1:
            return (
                f"Error: {len(matches)} fuzzy matches found in '{path}'. Use a more unique block."
            )
        return True
    except Exception as e:
        return f"Error during validation: {e}"


@tool(
    name="edit_file",
    desc=(
        "Edit a file by replacing a specific block of text. "
        "The tool first tries an exact match, and if that fails, it performs a "
        "fuzzy match (ignoring minor whitespace and indentation differences)."
    ),
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to edit."},
            "search": {
                "type": "string",
                "description": "The block of text to find in the file.",
            },
            "replace": {
                "type": "string",
                "description": "The new text to replace the found block with.",
            },
            "dry_run": {
                "type": "boolean",
                "description": "If true, show diff without applying changes.",
                "default": False,
            },
        },
        "required": ["path", "search", "replace"],
    },
    validate=validate_edit_file,
)
@file_tool_handler
def edit_file(
    path: str,
    search: str,
    replace: str,
    dry_run: bool = False,
) -> str:
    """Edit a file by replacing a block of text with fuzzy matching."""
    p = validate_path(path)
    if not p.is_file():
        return f"Error: '{path}' is not a file."

    content = p.read_text(encoding="utf-8")

    # Search mode: Try exact match first
    if search in content:
        count = content.count(search)
        if count > 1:
            return f"Error: {count} matches found in '{path}'. Use a more unique search block."
        match_start = content.find(search)
        match_end = match_start + len(search)
    else:
        # Fuzzy match: Ignore whitespace/indentation differences
        stripped_search = search.strip()
        if not stripped_search:
            return f"Error: 'search' block is empty or contains only whitespace (path: '{path}')."

        tokens = re.split(r"(\s+|[^\w])", stripped_search)
        pattern_parts = [re.escape(t) for t in tokens if t and not t.isspace()]

        if not pattern_parts:
            return f"Error: 'search' block contains no usable tokens for matching in '{path}'."

        # Guard against ReDoS: refuse excessively complex search blocks.
        if len(pattern_parts) > _FUZZY_MAX_TOKENS:
            return (
                f"Error: 'search' block is too large for fuzzy matching "
                f"({len(pattern_parts)} tokens, max {_FUZZY_MAX_TOKENS}). "
                "Use a shorter, more precise block."
            )

        pattern = r"\s*".join(pattern_parts)
        matches = _fuzzy_finditer(pattern, content)

        if matches is None:
            return (
                "Error: Fuzzy match timed out. "
                "The 'search' block may be too complex or the file too large. "
                "Use a shorter, more precise block."
            )
        if not matches:
            return f"Error: The 'search' block was not found exactly or fuzzily in '{path}'."
        if len(matches) > 1:
            return (
                f"Error: {len(matches)} fuzzy matches found in '{path}'. Use a more unique block."
            )
        match_start, match_end = matches[0].span()

    # Generate new content
    new_content = content[:match_start] + replace + content[match_end:]

    # Generate Diff Preview
    diff = "".join(
        difflib.unified_diff(
            content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )

    if dry_run:
        return f"Dry run enabled. No changes made.\n\n{diff}"

    p.write_text(new_content, encoding="utf-8")
    return f"Successfully updated {path}.\n\n{diff}"


@tool(
    name="create_or_overwrite_file",
    desc="Write full content to a file. Overwrites existing files.",
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to save the file."},
            "content": {
                "type": "string",
                "description": (
                    "The complete file content to write. "
                    "This field is REQUIRED and must contain the full "
                    "text of the file. "
                    "Do not omit this field."
                ),
            },
        },
        "required": ["path", "content"],
    },
    validate=validate_create_or_overwrite_file,
)
@file_tool_handler
def create_or_overwrite_file(path: str, content: str, **_kwargs: Any) -> str:
    """Create a new file or overwrite an existing one with the provided content."""
    p = validate_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Successfully wrote to {path}"
