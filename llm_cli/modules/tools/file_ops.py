# llm_cli/modules/tools/file_ops.py

import difflib
import fnmatch
import re
from pathlib import Path
from typing import Dict, List, Union

from llm_cli.clients.config import get_setting
from llm_cli.modules.media_utils import process_file
from llm_cli.modules.tool_registry import tool
from llm_cli.security.path_validator import PathValidationError, validate_path


@tool(
    name="list_files",
    desc=(
        "List files in a directory. Use this to explore the project structure to "
        "find relevant files. If you are looking for specific code definitions, "
        "use 'search_files' instead."
    ),
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
            "max_files": {
                "type": "integer",
                "description": "Maximum number of files to list.",
                "default": 500,
            },
        },
        "required": [],
    },
)
def list_files(
    directory: str = ".",
    depth: int = 1,
    ignore_patterns: List[str] = None,
    max_files: int = 500,
) -> str:
    """
    Lists files in a directory tree, excluding specified patterns
    and limiting the output size for safety.
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
                ".env",
                ".DS_Store",
            ]

        results, file_count = [], 0

        def should_ignore(name: str) -> bool:
            return any(fnmatch.fnmatch(name, pattern) for pattern in ignore_patterns)

        def walk(current_path, current_depth):
            nonlocal file_count
            if depth is not None and current_depth > depth:
                return

            try:
                # Filter out ignored directories before iterating
                entries = sorted(
                    [e for e in current_path.iterdir() if not should_ignore(e.name)],
                    key=lambda x: (not x.is_dir(), x.name),
                )
            except PermissionError:
                results.append(
                    f"{'  ' * (current_depth - 1)}⚠️ "
                    f"Permission Denied: {current_path.name}"
                )
                return

            for entry in entries:
                if file_count >= max_files:
                    if file_count == max_files:
                        results.append("... (Too many files, listing truncated)")
                        file_count += 1
                    break

                rel_path = entry.relative_to(base_path)
                prefix = "  " * (current_depth - 1)

                if entry.is_dir():
                    results.append(f"{prefix}📁 {rel_path}/")
                    walk(entry, current_depth + 1)
                else:
                    results.append(f"{prefix}📄 {rel_path}")
                    file_count += 1

        walk(base_path, 1)
        return "\n".join(results) or "No files found."

    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="search_files",
    desc="Search for a text pattern in files within a directory (Grep-like).",
    params={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text or regex pattern to search for.",
            },
            "directory": {
                "type": "string",
                "description": "Directory to search in (default: current directory).",
            },
            "file_pattern": {
                "type": "string",
                "description": "Glob pattern for file names to include (e.g. '*.py').",
            },
        },
        "required": ["query"],
    },
)
def search_files(query: str, directory: str = ".", file_pattern: str = None) -> str:
    """
    Search for a text pattern in files.
    """
    try:
        validate_path(directory or ".")
        base_path = Path(directory or ".")
        if not base_path.exists():
            return f"Error: Directory '{directory}' does not exist."

        results = []

        # Default ignore patterns for search to avoid huge logs
        ignore_dirs = {".git", "__pycache__", "node_modules", "venv"}

        for path in base_path.rglob(file_pattern or "*"):
            if path.is_dir():
                continue

            # Skip hidden files/dirs and ignored dirs
            if any(part.startswith(".") or part in ignore_dirs for part in path.parts):
                continue

            try:
                # Simple check for text file
                content = path.read_text(encoding="utf-8", errors="ignore")

                lines = content.splitlines()
                for i, line in enumerate(lines):
                    if re.search(query, line):
                        # Format: FilePath:LineNumber: Content
                        results.append(f"{path}:{i + 1}: {line.strip()}")

                        if len(results) >= 100:
                            results.append("... (Too many matches, truncated)")
                            return "\n".join(results)

            except Exception:
                continue  # Skip binary or unreadable files

        return "\n".join(results) or f"No matches found for '{query}'."

    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="read_text_file",
    desc=(
        "Read content from a text file. Can read specific lines and optionally "
        "include line numbers."
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
def read_text_file(
    path: str,
    start_line: int = 1,
    end_line: int = None,
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

            max_output = int(get_setting("max_read_file_len", "general") or 50000)
            return content[:max_output]

        except UnicodeDecodeError:
            return f"Error: '{path}' appears to be a binary file."

    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="replace_lines",
    desc=(
        "Replace a range of lines in a file with new content. Returns the "
        "diff of changes."
    ),
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to edit."},
            "start_line": {
                "type": "integer",
                "description": "The first line number to replace (1-indexed).",
            },
            "end_line": {
                "type": "integer",
                "description": "The last line number to replace (inclusive).",
            },
            "replacement": {
                "type": "string",
                "description": "The new content to insert.",
            },
        },
        "required": ["path", "start_line", "end_line", "replacement"],
    },
)
def replace_lines(path: str, start_line: int, end_line: int, replacement: str) -> str:
    """
    Replaces lines in a file using 1-based indexing and returns a unified diff.
    """
    try:
        validate_path(path)
        p = Path(path)
        if not p.is_file():
            return f"Error: '{path}' is not a file."

        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        # Using keepends=True to preserve original newlines for correct diff generation

        total_lines = len(lines)

        # Validate indices
        if start_line < 1 or start_line > total_lines + 1:
            return (
                f"Error: start_line {start_line} is out of bounds "
                f"(file has {total_lines} lines)."
            )

        start_idx = start_line - 1
        end_idx = end_line  # inclusive in request, so corresponds to slice end index

        if end_line < start_line:
            return (
                f"Error: end_line {end_line} is smaller than start_line {start_line}."
            )

        # Prepare new content (ensure it has newlines)
        new_content_lines = [
            line + "\n" if not line.endswith("\n") else line
            for line in replacement.splitlines()
        ]

        # Handle case where replacement is empty but splitlines returns []
        if not replacement and not new_content_lines:
            new_content_lines = []
        elif replacement.endswith("\n") and not replacement.strip():
            # Special case for just newlines
            new_content_lines = [
                line + "\n" if not line.endswith("\n") else line
                for line in replacement.splitlines(keepends=True)
            ]

        # Construct new file content
        final_lines = lines[:start_idx] + new_content_lines + lines[end_idx:]

        # Generate diff
        diff = list(
            difflib.unified_diff(
                lines,
                final_lines,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
                n=3,  # Context lines
            )
        )

        # Write back
        p.write_text("".join(final_lines), encoding="utf-8")

        diff_text = "".join(diff)
        return f"Successfully updated {path}.\n\nDiff:\n{diff_text}"

    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="write_file",
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
def write_file(path: str, content: str) -> str:
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


def _process_and_return(path: str, expected_types: tuple = None) -> Union[str, Dict]:
    try:
        p = Path(path)
        if not p.exists():
            return f"Error: File not found: {path}"

        res = process_file(p, pdf_as_base64=True)
        if not res:
            return f"Error: Failed to process file: {path}"

        content_type = res.get("content_type", "")

        if expected_types:
            if not any(content_type.startswith(t) for t in expected_types):
                return (
                    f"Error: File '{path}' has type '{content_type}', "
                    f"but expected one of {expected_types}."
                )

        return {
            "result": f"Successfully read {path} ({content_type})",
            "__llm_cli_data__": {
                "content": res["content"],
                "content_type": res["content_type"],
                "is_file_or_url": True,
            },
        }
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="read_pdf_file",
    desc="Read a PDF file and add it to the context.",
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the PDF file."}
        },
        "required": ["path"],
    },
)
def read_pdf_file(path: str) -> Union[str, Dict]:
    return _process_and_return(path, expected_types=("application/pdf",))
