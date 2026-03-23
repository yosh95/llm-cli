# llm_cli/modules/tools/file_ops.py

import fnmatch
import functools
import os
import re
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_cli.consts import MAX_OUTPUT_CHARS, MAX_OUTPUT_LINES
from llm_cli.modules.media_utils import process_file
from llm_cli.modules.tool_registry import tool
from llm_cli.security.path_validator import PathValidationError, validate_path
from llm_cli.security.pqc import sign_tool_result

# --- Constants ---
DEFAULT_EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    "cache",
    ".cache",
    "__pycache__",
    "venv",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".tox",
    ".idea",
    ".vscode",
    ".env",
    ".DS_Store",
}

MAX_FILE_READ_SIZE = 5 * 1024 * 1024  # 5MB
SEARCH_TIMEOUT = 55
MAX_SEARCH_RESULTS = 300


def format_size(size_bytes: int) -> str:
    """Helper to format file size in human-readable form."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def file_tool_handler(
    func: Callable[..., Any],
) -> Callable[..., Any]:
    """Decorator to handle common file tool logic."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        reqs = kwargs.pop("__security_requirements__", None)
        variant_raw = reqs.get("pqc_variant") if isinstance(reqs, dict) else None
        variant = str(variant_raw) if variant_raw else "ML-DSA-65"

        try:
            result = func(*args, **kwargs)
            return (
                sign_tool_result(result, variant=variant)
                if isinstance(result, str)
                else result
            )
        except PathValidationError as e:
            return sign_tool_result(f"Security Error: {e}", variant=variant)
        except Exception as e:
            return sign_tool_result(f"Error: {e}", variant=variant)

    return wrapper


@tool(
    name="search_files",
    desc=(
        "Search for a regex pattern in files within a directory. "
        "Automatically excludes common junk directories like .git, node_modules, and "
        "cache to provide clean and fast results."
    ),
    params={
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Directory to search in (default: current directory).",
            },
            "query": {"type": "string", "description": "Regex pattern to search for."},
            "file_pattern": {
                "type": "string",
                "description": "File pattern to include (e.g., '*.py').",
            },
        },
        "required": ["query"],
    },
)
@file_tool_handler
def search_files(
    directory: str = ".",
    query: str = "",
    file_pattern: str | None = None,
) -> str:
    """Search for a pattern in files, excluding common cache directories."""
    validate_path(directory or ".")
    base_path = Path(directory or ".")
    if not base_path.exists():
        return f"Error: Directory '{directory}' does not exist."

    try:
        regex = re.compile(query, re.MULTILINE)
    except re.error as e:
        return f"Error: Invalid regex pattern: {e}"

    results = []
    start_time = time.time()

    for root, dirs, files in os.walk(base_path, topdown=True):
        if time.time() - start_time > SEARCH_TIMEOUT:
            results.append("Error: Search timed out after 60 seconds.")
            break

        dirs[:] = [
            d for d in dirs if d not in DEFAULT_EXCLUDE_DIRS and not d.startswith(".")
        ]

        for file in files:
            if file.startswith(".") or (
                file_pattern and not fnmatch.fnmatch(file, file_pattern)
            ):
                continue

            file_path = Path(root) / file
            try:
                if file_path.stat().st_size > MAX_FILE_READ_SIZE:
                    continue

                with file_path.open("rb") as bf:
                    if b"\0" in bf.read(1024):
                        continue

                with file_path.open("r", encoding="utf-8", errors="ignore") as f:
                    for line_no, line in enumerate(f, 1):
                        if regex.search(line):
                            rel_path = file_path.relative_to(base_path)
                            results.append(f"{rel_path}:{line_no}:{line.strip()}")
                            if len(results) >= MAX_SEARCH_RESULTS:
                                msg = (
                                    f"\n\n... (Total {len(results)} matches, truncated)"
                                )
                                return "\n".join(results) + msg
            except (PermissionError, OSError):
                continue

    return "\n".join(results) if results else "No matches found."


@tool(
    name="list_files_in_directory",
    desc="List files in a directory.",
    params={
        "type": "object",
        "properties": {
            "directory": {
                "type": "string",
                "description": "Target directory (default: current directory).",
            },
            "depth": {
                "type": "integer",
                "description": "Maximum depth for recursive listing.",
                "default": 1,
            },
            "ignore_patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of patterns to ignore (e.g. ['node_modules']).",
            },
            "include_hidden": {
                "type": "boolean",
                "description": "If true, show hidden files and directories.",
                "default": False,
            },
            "max_files": {
                "type": "integer",
                "description": (
                    f"Maximum number of files to list. (Default: {MAX_OUTPUT_LINES})"
                ),
                "default": MAX_OUTPUT_LINES,
            },
        },
    },
)
@file_tool_handler
def list_files_in_directory(
    directory: str = ".",
    depth: int = 1,
    ignore_patterns: list[str] | None = None,
    include_hidden: bool = False,
    max_files: int = MAX_OUTPUT_LINES,
) -> str:
    """Lists files in a directory tree with metadata."""
    validate_path(directory or ".")
    base_path = Path(directory or ".")
    if not base_path.exists():
        return f"Error: Directory '{directory}' does not exist."

    if ignore_patterns is None:
        ignore_patterns = list(DEFAULT_EXCLUDE_DIRS)

    results, file_count = [], 0
    results.append(
        f"{'[Type]':<7} {'[Last Modified (UTC)]':<20} {'[Size]':>10}  {'[Full Path]'}"
    )

    def should_ignore(name: str) -> bool:
        if not include_hidden and name.startswith("."):
            return True
        return any(fnmatch.fnmatch(name, pattern) for pattern in ignore_patterns)

    def walk(current_path: Path, current_depth: int) -> None:
        nonlocal file_count
        if depth is not None and current_depth > depth:
            return

        try:
            all_entries = sorted(
                [e for e in current_path.iterdir() if not should_ignore(e.name)],
                key=lambda x: (not x.is_dir(), x.name.lower()),
            )
        except PermissionError:
            results.append(
                f"{'[ERR]':<7} {' ' * 20} {' ' * 10}  "
                f"Permission Denied: {current_path.name}"
            )
            return

        for entry in all_entries:
            if file_count >= max_files:
                if file_count == max_files:
                    results.append("\n... (Too many files, listing truncated)")
                    file_count += 1
                return

            try:
                stat = entry.stat()
                mtime = datetime.fromtimestamp(stat.st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                rel_path = entry.relative_to(base_path)

                if entry.is_dir():
                    results.append(f"{'[D]':<7} {mtime:<20} {'-':>10}  {rel_path}/")
                    file_count += 1
                    walk(entry, current_depth + 1)
                else:
                    sz = format_size(stat.st_size)
                    results.append(f"{'[F]':<7} {mtime:<20} {sz:>10}  {rel_path}")
                    file_count += 1
            except (PermissionError, OSError):
                continue

    walk(base_path, 1)
    return "\n".join(results) if len(results) > 1 else "No files found."


def validate_read_file(path: str, **_kwargs: Any) -> bool | str:
    """Validates that the file exists and is readable before approval."""
    try:
        validate_path(path)
        p = Path(path)
        if not p.is_file():
            return f"Error: '{path}' is not a file."
        return True
    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error during validation: {e}"


@tool(
    name="read_file_content",
    desc=(
        "Read content from a text file or PDF. "
        "For PDFs, text content will be extracted. "
        f"IMPORTANT: This tool can read up to {MAX_OUTPUT_LINES} lines or "
        f"{MAX_OUTPUT_CHARS} characters at once. "
        "If a file is longer, the tail will be omitted. "
        "Use 'start_line' and 'end_line' to read specific chunks of large files."
    ),
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path."},
            "start_line": {
                "type": "integer",
                "description": "First line to read (1-indexed).",
                "default": 1,
            },
            "end_line": {
                "type": "integer",
                "description": (
                    f"Last line to read (Max {MAX_OUTPUT_LINES} lines "
                    "from start_line recommended)."
                ),
            },
            "with_line_numbers": {
                "type": "boolean",
                "description": "If true, adds line numbers to the output.",
                "default": False,
            },
        },
        "required": ["path"],
    },
    validate=validate_read_file,
)
@file_tool_handler
def read_file_content(
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
    with_line_numbers: bool = False,
) -> str:
    """Read content from a file, with support for line selection and numbering."""
    validate_path(path)
    p = Path(path)
    if not p.is_file():
        return f"Error: '{path}' is not a file."

    res = process_file(p, pdf_as_base64=False)
    if not res or "content" not in res:
        return f"Error: Could not read content from '{path}'."

    if res.get("content_type") != "text/plain":
        return f"Error: '{path}' is a binary file and cannot be read as text."

    lines = res["content"].splitlines()
    start = max(1, start_line) - 1
    end = min(len(lines), end_line) if end_line else len(lines)
    selected_lines = lines[start:end]

    if with_line_numbers:
        return "\n".join(
            [f"{start + i + 1:4d} | {line}" for i, line in enumerate(selected_lines)]
        )

    return "\n".join(selected_lines)
