# llm_cli/modules/tools/file_ops.py

from pathlib import Path

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

        exclude = {
            ".git", "__pycache__", "node_modules", ".venv", ".pytest_cache",
            ".vscode", ".idea", ".mypy_cache",
        }
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
                if entry.name in exclude:
                    continue
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
        return f"{header}\n{content[:50000]}"
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
