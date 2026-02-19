# llm_cli/modules/tools/file_ops.py

import difflib
import fnmatch
import re
import shutil
import subprocess
from pathlib import Path

from llm_cli.clients.config import get_setting
from llm_cli.modules.media_utils import process_file
from llm_cli.modules.tool_registry import tool
from llm_cli.security.path_validator import PathValidationError, validate_path


@tool(
    name="list_files_in_directory",
    desc=(
        "List files in a directory. Use this to explore the project structure to "
        "find relevant files. If you are looking for specific code definitions, "
        "use 'search_text_in_files' instead. "
        "Note: Output is truncated to 10,000 characters by default. Use "
        "'max_output_length' to increase the limit."
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
            "max_output_length": {
                "type": "integer",
                "description": (
                    "Maximum number of characters to return in the output. "
                    "Truncates if exceeded. Set to 0 for no limit."
                ),
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
    max_output_length: int | None = None,
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

        if max_output_length is None:
            max_output_length = int(
                get_setting("max_output_length", "general") or 10000
            )

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

        def should_ignore(name: str) -> bool:
            return any(fnmatch.fnmatch(name, pattern) for pattern in ignore_patterns)

        def walk(current_path: Path, current_depth: int) -> None:
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
        final_result = "\n".join(results) or "No files found."
        if max_output_length > 0 and len(final_result) > max_output_length:
            final_result = (
                final_result[:max_output_length]
                + "\n... (Listing truncated due to length limit)"
            )
        return final_result

    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="search_text_in_files",
    desc=(
        "Search for a text pattern in files within a directory (Grep-like). "
        "Note: Output is truncated to 10,000 characters by default. Use "
        "'max_output_length' to increase the limit."
    ),
    params={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text or regex pattern (ERE/PCRE) to search for.",
            },
            "directory": {
                "type": "string",
                "description": "Directory to search in (default: current directory).",
            },
            "file_pattern": {
                "type": "string",
                "description": "Glob pattern for file names to include (e.g. '*.py').",
            },
            "max_output_length": {
                "type": "integer",
                "description": (
                    "Maximum number of characters to return in the output. "
                    "Truncates if exceeded. Set to 0 for no limit."
                ),
            },
        },
        "required": ["query"],
    },
)
def search_text_in_files(
    query: str,
    directory: str = ".",
    file_pattern: str | None = None,
    max_output_length: int | None = None,
) -> str:
    """
    Search for a text pattern in files.
    Uses 'rg' or 'grep -E' if available for performance, otherwise falls back to Python.
    """
    try:
        validate_path(directory or ".")
        base_path = Path(directory or ".")
        if not base_path.exists():
            return f"Error: Directory '{directory}' does not exist."

        # Use configured max output length or default to 10000
        if max_output_length is None:
            max_output_length = int(
                str(get_setting("max_output_length", "general") or "10000")
            )

        exclude_dirs = [
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
            "__MACOSX",
        ]

        # Try using system tools for performance
        search_tool = None
        if shutil.which("rg"):
            search_tool = "rg"
            cmd = ["rg", "-nH", "--no-heading", "--smart-case", "-I"]
            for d in exclude_dirs:
                cmd.extend(["-g", f"!{d}/*"])
            if file_pattern:
                cmd.extend(["-g", file_pattern])
        elif shutil.which("grep"):
            search_tool = "grep"
            cmd = ["grep", "-rnIE"]  # -E for Extended Regular Expressions
            for d in exclude_dirs:
                cmd.extend(["--exclude-dir", d])
            if file_pattern:
                cmd.extend(["--include", file_pattern])

        if search_tool:
            try:
                # Use '--' to prevent query from being interpreted as an option
                cmd.extend(["--", query, str(base_path)])

                # Run tool with timeout for safety (ReDoS protection)
                process = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )

                if process.returncode == 0:
                    lines = process.stdout.splitlines()
                    formatted_results = []
                    for line in lines:
                        # Normalize output: remove leading ./ and ensure space after
                        # colon. format: path:line:content
                        parts = line.split(":", 2)
                        if len(parts) == 3:
                            path, line_num, content = parts
                            if path.startswith("./"):
                                path = path[2:]
                            res_line = f"{path}:{line_num}: {content.lstrip()}"
                            formatted_results.append(res_line)
                        else:
                            formatted_results.append(line)

                    final_result = "\n".join(formatted_results)
                    if len(final_result) > max_output_length:
                        final_result = (
                            final_result[:max_output_length]
                            + "\n... (Too many matches, output truncated)"
                        )
                    return final_result
                elif process.returncode == 1:
                    return f"No matches found for '{query}'."
                else:
                    # tool error, fall back to python
                    pass
            except subprocess.TimeoutExpired:
                return "Error: Search timed out after 30 seconds."
            except Exception:
                # Fall back to python on any error
                pass

        # Python Fallback Implementation
        results = []
        ignore_dirs = set(exclude_dirs)

        for file_path in base_path.rglob(file_pattern or "*"):
            if file_path.is_dir():
                continue

            if any(
                part.startswith(".") or part in ignore_dirs for part in file_path.parts
            ):
                continue

            try:
                # Check for binary file
                is_binary = False
                try:
                    with file_path.open("rb") as f_bin:
                        chunk = f_bin.read(8192)
                        if b"\x00" in chunk:
                            is_binary = True
                except Exception:
                    continue

                if is_binary:
                    continue

                with file_path.open(encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f):
                        if re.search(query, line):
                            clean_path = str(file_path)
                            if clean_path.startswith("./"):
                                clean_path = clean_path[2:]

                            results.append(f"{clean_path}:{i + 1}: {line.strip()}")

                            current_output = "\n".join(results)
                            if (
                                len(current_output) >= max_output_length
                                or len(results) >= 1000
                            ):
                                results.append("... (Too many matches, truncated)")
                                return "\n".join(results)

            except Exception:
                continue

        return "\n".join(results) or f"No matches found for '{query}'."

    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="read_file_content",
    desc=(
        "Read content from a text file. Can read specific lines and optionally "
        "include line numbers. "
        "Note: Output is truncated to 10,000 characters by default. Use "
        "'max_output_length' to increase the limit."
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
            "max_output_length": {
                "type": "integer",
                "description": (
                    "Maximum number of characters to return in the output. "
                    "Truncates if exceeded. Set to 0 for no limit."
                ),
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
    max_output_length: int | None = None,
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

            if max_output_length is None:
                max_output_length = int(
                    get_setting("max_output_length", "general") or 10000
                )

            if max_output_length > 0 and len(content) > max_output_length:
                content = (
                    content[:max_output_length]
                    + "\n... (Content truncated due to length limit)"
                )
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
                    "Use actual newlines for multi-line blocks, not '\\n'."
                ),
            },
            "replace": {
                "type": "string",
                "description": (
                    "The new block of text to replace 'search' with. "
                    "Use actual newlines for multi-line blocks, not '\\n'."
                ),
            },
            "dry_run": {
                "type": "boolean",
                "description": (
                    "If true, returns the diff without modifying the file. "
                    "Use this for preview."
                ),
                "default": False,
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
        _ = "".join(diff)

        if dry_run:
            return "Dry run enabled. No changes made."

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


def _process_and_return(path: str, expected_types: tuple | None = None) -> str | dict:
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
            "result": (
                f"Successfully read {path} ({content_type}). "
                "The file content has been added to the conversation context "
                "as a binary attachment. Please analyze the attached file."
            ),
            "__llm_cli_data__": {
                "content": res["content"],
                "content_type": res["content_type"],
                "is_file_or_url": True,
            },
        }
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="read_pdf_content",
    desc="Read a PDF file and add it to the context.",
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the PDF file."}
        },
        "required": ["path"],
    },
)
def read_pdf_content(path: str) -> str | dict:
    return _process_and_return(path, expected_types=("application/pdf",))
