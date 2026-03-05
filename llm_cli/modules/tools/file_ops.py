# llm_cli/modules/tools/file_ops.py

import difflib
import fnmatch
import subprocess
from pathlib import Path

from llm_cli.modules.media_utils import process_file
from llm_cli.modules.tool_registry import tool
from llm_cli.security.path_validator import PathValidationError, validate_path


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
    Search for a pattern using grep, excluding common cache and junk directories.
    """
    try:
        validate_path(directory or ".")

        exclude_dirs = [
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
        ]

        # Use -rnP: recursive, line number, Perl-compatible regex
        cmd = ["grep", "-rnP"]
        for d in exclude_dirs:
            cmd.append(f"--exclude-dir={d}")

        if file_pattern:
            cmd.append(f"--include={file_pattern}")

        cmd.extend(["--", query, directory or "."])

        # Limit execution time and capture output
        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if process.returncode == 1:
            return "No matches found."
        if process.returncode > 1:
            # grep returns 2 if an error occurred
            return (
                f"Error: grep failed with exit code {process.returncode}\n"
                f"{process.stderr}"
            )

        lines = process.stdout.splitlines()
        max_lines = 300
        if len(lines) > max_lines:
            summary = (
                f"\n\n... (Total {len(lines)} matches, truncated to {max_lines} lines)"
            )
            return "\n".join(lines[:max_lines]) + summary

        return process.stdout or "No matches found."

    except PathValidationError as e:
        return f"Security Error: {e}"
    except subprocess.TimeoutExpired:
        return "Error: Search timed out after 60 seconds."
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
        return final_result

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
                "metadata": {"filename": res.get("filename", p.name)},
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
