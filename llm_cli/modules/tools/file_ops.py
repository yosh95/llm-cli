# llm_cli/modules/tools/file_ops.py

import difflib
import fnmatch
import os
from datetime import datetime
from pathlib import Path

from llm_cli.modules.tool_registry import tool
from llm_cli.security.path_validator import PathValidationError, validate_path


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


@tool(
    name="search_files",
    desc=(
        "Search for a regex pattern in files within a directory. "
        "Automatically excludes common junk directories like .git, node_modules, and "
        "cache to provide clean and fast results. "
    ),
    params={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Regex pattern to search for."},
            "directory": {
                "type": "string",
                "description": "Directory to search in (default: current directory).",
            },
            "file_pattern": {
                "type": "string",
                "description": "File pattern to include (e.g., '*.py').",
            },
        },
        "required": ["query"],
    },
)
def search_files(
    query: str,
    directory: str = ".",
    file_pattern: str | None = None,
) -> str:
    """
    Search for a pattern in files using Python, excluding common cache directories.
    This is more portable and allows better control over file types and sizes.
    """
    try:
        validate_path(directory or ".")
        base_path = Path(directory or ".")
        if not base_path.exists():
            return f"Error: Directory '{directory}' does not exist."

        import re
        import time

        try:
            regex = re.compile(query, re.MULTILINE)
        except re.error as e:
            return f"Error: Invalid regex pattern: {e}"

        exclude_dirs = {
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
        }

        results = []
        max_results = 300
        max_file_size = 5 * 1024 * 1024  # 5MB
        start_time = time.time()
        timeout = 55  # Slightly less than 60 to be safe

        for root, dirs, files in os.walk(base_path, topdown=True):
            # Check timeout
            if time.time() - start_time > timeout:
                results.append("Error: Search timed out after 60 seconds.")
                break

            # Filter directories in-place
            dirs[:] = [
                d for d in dirs if d not in exclude_dirs and not d.startswith(".")
            ]

            for file in files:
                if file.startswith("."):
                    continue

                if file_pattern and not fnmatch.fnmatch(file, file_pattern):
                    continue

                file_path = Path(root) / file

                try:
                    # Skip if too large
                    if file_path.stat().st_size > max_file_size:
                        continue

                    # Check for binary content by reading first 1KB
                    with file_path.open("rb") as bf:
                        chunk = bf.read(1024)
                        if b"\0" in chunk:
                            continue

                    # Read and search
                    with file_path.open("r", encoding="utf-8", errors="ignore") as f:
                        for line_no, line in enumerate(f, 1):
                            if regex.search(line):
                                rel_path = file_path.relative_to(base_path)
                                results.append(f"{rel_path}:{line_no}:{line.strip()}")
                                if len(results) >= max_results:
                                    summary = (
                                        f"\n\n... (Total {len(results)} "
                                        "matches, truncated)"
                                    )
                                    return "\n".join(results) + summary
                except (PermissionError, OSError):
                    continue

        if not results:
            return "No matches found."

        return "\n".join(results)

    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="list_files_in_directory",
    desc=("List files in a directory."),
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
                "description": (
                    "List of patterns to ignore (e.g. ['node_modules', "
                    "'*.pyc', '.git'])."
                ),
            },
            "include_hidden": {
                "type": "boolean",
                "description": (
                    "If true, show hidden files and directories "
                    "(those starting with a dot)."
                ),
                "default": False,
            },
            "max_files": {
                "type": "integer",
                "description": "Maximum number of files to list.",
                "default": 500,
            },
        },
        "required": [],
    },
)
def list_files_in_directory(
    directory: str = ".",
    depth: int = 1,
    ignore_patterns: list[str] | None = None,
    max_files: int = 500,
    include_hidden: bool = False,
) -> str:
    """
    Lists files in a directory tree with metadata, using a flat full-path format.
    Excludes specified patterns and limits the output size for safety.
    """
    try:
        validate_path(directory or ".")
        base_path = Path(directory or ".")
        if not base_path.exists():
            return f"Error: Directory '{directory}' does not exist."

        if ignore_patterns is None:
            ignore_patterns = [
                ".git",
                "__pycache__",
                "node_modules",
                "venv",
                ".venv",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                ".env",
                ".DS_Store",
            ]

        results, file_count = [], 0
        header = (
            f"{'[Type]':<7} {'[Last Modified (UTC)]':<20} "
            f"{'[Size]':>10}  {'[Full Path]'}"
        )
        results.append(header)

        def should_ignore(name: str) -> bool:
            if not include_hidden and name.startswith("."):
                return True
            return any(fnmatch.fnmatch(name, pattern) for pattern in ignore_patterns)

        def walk(current_path: Path, current_depth: int) -> None:
            nonlocal file_count
            if depth is not None and current_depth > depth:
                return

            try:
                # Sort: Directories first, then files, both alphabetically
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
                        size_str = format_size(stat.st_size)
                        results.append(
                            f"{'[F]':<7} {mtime:<20} {size_str:>10}  {rel_path}"
                        )
                        file_count += 1
                except (PermissionError, OSError):
                    continue

        walk(base_path, 1)
        if len(results) == 1:  # Only header
            return "No files found."

        return "\n".join(results)

    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="read_file_content",
    desc=(
        "Read content from a text file. Can read specific lines and optionally "
        "include line numbers. "
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
            "end_line": {"type": "integer", "description": "Last line to read."},
            "with_line_numbers": {
                "type": "boolean",
                "description": "If true, adds line numbers to the output.",
                "default": False,
            },
        },
        "required": ["path"],
    },
)
def read_file_content(
    path: str,
    start_line: int = 1,
    end_line: int | None = None,
    with_line_numbers: bool = False,
) -> str:
    try:
        validate_path(path)
        p = Path(path)
        if not p.is_file():
            return f"Error: '{path}' is not a file."

        try:
            lines = p.read_text(encoding="utf-8").splitlines()
            start = max(1, start_line) - 1
            end = min(len(lines), end_line) if end_line else len(lines)

            selected_lines = lines[start:end]

            if with_line_numbers:
                content_lines = []
                for i, line in enumerate(selected_lines):
                    content_lines.append(f"{start + i + 1:4d} | {line}")
                content = "\n".join(content_lines)
            else:
                content = "\n".join(selected_lines)

            return content

        except UnicodeDecodeError:
            return f"Error: '{path}' appears to be a binary file."

    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="edit_file",
    desc=(
        "Edit a file by replacing a specific block of text. This is safer than "
        "create_or_overwrite_file for bug fixes as it prevents unintended changes "
        "to other parts of the file."
    ),
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to edit."},
            "search": {
                "type": "string",
                "description": (
                    "The exact block of text to find. "
                    "Must match exactly including indentation. "
                ),
            },
            "replace": {
                "type": "string",
                "description": ("The new block of text to replace 'search' with. "),
            },
        },
        "required": ["path", "search", "replace"],
    },
)
def edit_file(path: str, search: str, replace: str, dry_run: bool = False) -> str:
    """
    Search and replace a specific block of text in a file.
    Ensures that only the intended part is modified.
    """
    try:
        validate_path(path)
        p = Path(path)
        if not p.is_file():
            return f"Error: '{path}' is not a file."

        content = p.read_text(encoding="utf-8")
        if search not in content:
            # Check for potential whitespace-only mismatch to provide better feedback
            import re

            def normalize(s: str) -> str:
                return re.sub(r"\s+", " ", s).strip()

            if normalize(search) in normalize(content):
                return (
                    "Error: The 'search' block was not found exactly, but a similar "
                    "match was found ignoring whitespace/indentation. "
                    "Ensure the search block matches the file content exactly, "
                    "including the specific number of spaces, tabs, and newlines."
                )

            return (
                "Error: The 'search' block was not found in the file. "
                "Ensure the search block matches the file content exactly, "
                "including indentation and whitespace."
            )

        # Count occurrences to avoid ambiguous replacements
        count = content.count(search)
        if count > 1:
            return (
                f"Error: Found {count} occurrences of the search block. "
                "Please provide a more unique/specific search block."
            )

        # Generate Diff Preview
        new_content = content.replace(search, replace)
        diff = list(
            difflib.unified_diff(
                content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=3,
            )
        )
        diff_str = "".join(diff)

        if dry_run:
            return f"Dry run enabled. No changes made.\n\n{diff_str}"

        p.write_text(new_content, encoding="utf-8")
        return f"Successfully updated {path}."

    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="create_or_overwrite_file",
    desc="Write full content to a file. Overwrites existing files.",
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to save the file."},
            "content": {
                "type": "string",
                "description": "The exact string content to write.",
            },
        },
        "required": ["path", "content"],
    },
)
def create_or_overwrite_file(path: str, content: str) -> str:
    try:
        validate_path(path)
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {path}"
    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


# End of file or next content
