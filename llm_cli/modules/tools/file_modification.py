# llm_cli/modules/tools/file_modification.py

import difflib
import re

from llm_cli.modules.tool_registry import tool

from .common import file_tool_handler, validate_path


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
                return (
                    f"Error: {count} matches found in '{path}'. "
                    "Use a more unique search block."
                )
            return True

        # Fuzzy match check
        stripped_search = search.strip()
        if not stripped_search:
            return (
                f"Error: 'search' block is empty or contains "
                f"only whitespace (path: '{path}')."
            )

        tokens = re.split(r"(\s+|[^\w])", stripped_search)
        pattern_parts = [re.escape(t) for t in tokens if t and not t.isspace()]
        if not pattern_parts:
            return (
                f"Error: 'search' block contains no usable "
                f"tokens for matching in '{path}'."
            )

        pattern = r"\s*".join(pattern_parts)
        matches = list(re.finditer(pattern, content, re.DOTALL))

        if not matches:
            return (
                f"Error: The 'search' block was not found "
                f"exactly or fuzzily in '{path}'."
            )
        if len(matches) > 1:
            return (
                f"Error: {len(matches)} fuzzy matches found in '{path}'. "
                "Use a more unique block."
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
            return (
                f"Error: {count} matches found in '{path}'. "
                "Use a more unique search block."
            )
        match_start = content.find(search)
        match_end = match_start + len(search)
    else:
        # Fuzzy match: Ignore whitespace/indentation differences
        stripped_search = search.strip()
        if not stripped_search:
            return (
                f"Error: 'search' block is empty or contains "
                f"only whitespace (path: '{path}')."
            )

        tokens = re.split(r"(\s+|[^\w])", stripped_search)
        pattern_parts = [re.escape(t) for t in tokens if t and not t.isspace()]

        if not pattern_parts:
            return (
                f"Error: 'search' block contains no usable "
                f"tokens for matching in '{path}'."
            )

        pattern = r"\s*".join(pattern_parts)
        matches = list(re.finditer(pattern, content, re.DOTALL))

        if not matches:
            return (
                f"Error: The 'search' block was not found "
                f"exactly or fuzzily in '{path}'."
            )
        if len(matches) > 1:
            return (
                f"Error: {len(matches)} fuzzy matches found in '{path}'. "
                "Use a more unique block."
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
)
@file_tool_handler
def create_or_overwrite_file(path: str, content: str) -> str:
    """Create a new file or overwrite an existing one with the provided content."""
    p = validate_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Successfully wrote to {path}"
