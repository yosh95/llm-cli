# llm_cli/modules/tools/file_ops.py

from pathlib import Path

import whatthepatch

from llm_cli.clients.config import get_setting
from llm_cli.modules.tool_registry import tool
from llm_cli.security.path_validator import PathValidationError, validate_path


@tool(
    name="list_files",
    desc="List files in a directory with safety limits. "
    "Use this to explore the project structure.",
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
            "max_files": {
                "type": "integer",
                "description": "Maximum number of files to list to prevent "
                "context overflow.",
                "default": 500,
            },
        },
        "required": [],
    },
)
def list_files(directory: str = ".", depth: int = 1, max_files: int = 500) -> str:
    """
    Lists files in a directory tree, excluding common noise directories
    and limiting the output size for safety.
    """
    try:
        # Validate path for sandboxing
        validate_path(directory or ".")

        base_path = Path(directory or ".")
        if not base_path.exists():
            return f"Error: Directory '{directory}' does not exist."

        results, file_count = [], 0

        def walk(current_path, current_depth):
            nonlocal file_count
            if depth is not None and current_depth > depth:
                return
            try:
                entries = sorted(
                    list(current_path.iterdir()), key=lambda x: (not x.is_dir(), x.name)
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
    name="read_file",
    desc="Read content from a text file with optional line range.",
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
        },
        "required": ["path"],
    },
)
def read_file(path: str, start_line: int = 1, end_line: int = None) -> str:
    try:
        # Validate path for sandboxing
        validate_path(path)

        p = Path(path)
        if not p.is_file():
            return f"Error: '{path}' is not a file."

        lines = p.read_text(encoding="utf-8").splitlines()
        start = max(1, start_line) - 1
        end = min(len(lines), end_line) if end_line else len(lines)
        content = "\n".join(lines[start:end])

        header = f"--- {path} (Lines {start + 1} to {end}) ---"
        max_output = int(get_setting("max_read_file_len", "general") or 10000)
        return f"{header}\n{content[:max_output]}"
    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="write_file",
    desc="Write content to a file. Automatically creates directories if needed.",
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
        # Validate path for sandboxing
        validate_path(path)

        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {path}"
    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="edit_file",
    desc="Edit a file by replacing a specific block of text. "
    "This is safer than write_file for bug fixes as it prevents unintended changes "
    "to other parts of the file.",
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to edit."},
            "search": {
                "type": "string",
                "description": (
                    "The exact block of text to find. "
                    "Must match exactly including indentation."
                ),
            },
            "replace": {
                "type": "string",
                "description": "The new block of text to replace 'search' with.",
            },
        },
        "required": ["path", "search", "replace"],
    },
)
def edit_file(path: str, search: str, replace: str) -> str:
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

        new_content = content.replace(search, replace)
        p.write_text(new_content, encoding="utf-8")
        return f"Successfully updated {path}"
    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="apply_diff",
    desc="Apply a Unified Diff (patch) to a file. This is more robust than edit_file "
    "as it uses surrounding context to locate the changes. Supports multiple hunks.",
    params={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to the file to patch."},
            "diff": {
                "type": "string",
                "description": "The unified diff content to apply.",
            },
        },
        "required": ["path", "diff"],
    },
)
def apply_diff(path: str, diff: str) -> str:
    """
    Apply a unified diff (patch) to a file using the whatthepatch library.
    This is a native Python implementation that doesn't require the 'patch' command.
    """
    try:
        validate_path(path)
        p = Path(path)
        if not p.is_file():
            return f"Error: '{path}' is not a file."

        original_content = p.read_text(encoding="utf-8")
        original_lines = original_content.splitlines()

        # Parse the diff
        patches = list(whatthepatch.parse_patch(diff))
        if not patches:
            return (
                "Error: Could not parse the provided diff. "
                "Ensure it is in Unified Diff format."
            )

        patch = patches[0]

        # Check for context mismatches before applying
        if patch.changes:
            for change in patch.changes:
                if change.old is not None:
                    # This is a context line or a deleted line
                    # Check if the line in the file matches
                    line_idx = change.old - 1
                    if line_idx < 0 or line_idx >= len(original_lines):
                        return (
                            f"Error: Line number {change.old} is out of range "
                            f"in hunk #{change.hunk}."
                        )
                    if original_lines[line_idx] != change.line:
                        return (
                            f"Error: context line {change.old}, "
                            f'"{original_lines[line_idx]}" does not match '
                            f'"{change.line}", in hunk #{change.hunk}'
                        )

        # Apply the patch
        new_lines = whatthepatch.apply_diff(patch, original_lines)

        if new_lines is None:
            return (
                f"Error: Failed to apply the diff to {path}. "
                "This usually happens if the context lines in the diff don't match "
                "the current file content."
            )

        new_content = "\n".join(new_lines)

        # Preserve the original trailing newline if it existed
        if original_content.endswith("\n") and not new_content.endswith("\n"):
            new_content += "\n"

        p.write_text(new_content, encoding="utf-8")
        return f"Successfully applied diff to {path}"

    except PathValidationError as e:
        return f"Security Error: {e}"
    except Exception as e:
        return f"Error: {e}"
