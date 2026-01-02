# llm_cli/modules/tools/file_ops.py

from pathlib import Path
from llm_cli.modules.tool_registry import tool

@tool(
    name="list_files",
    description="List files and directories in a specific path.",
    parameters={
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "Target directory."},
            "depth": {"type": "integer", "description": "Search depth.", "default": 1}
        }
    }
)
def list_files(directory: str = ".", depth: int = 1, max_files: int = 500) -> str:
    try:
        base_path = Path(directory or ".")
        exclude = {".git", "__pycache__", "node_modules", ".venv"}
        results, file_count = [], 0

        def walk(current_path, current_depth):
            nonlocal file_count
            if depth is not None and current_depth > depth:
                return
            try:
                entries = sorted(list(current_path.iterdir()), key=lambda x: (not x.is_dir(), x.name))
            except PermissionError:
                return

            for entry in entries:
                if entry.name in exclude: continue
                if file_count >= max_files: break
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
    except Exception as e:
        return f"Error: {e}"

@tool(
    name="read_file",
    description="Read content from a text file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path."},
            "start_line": {"type": "integer", "default": 1},
            "end_line": {"type": "integer"}
        },
        "required": ["path"]
    }
)
def read_file(path: str, start_line: int = 1, end_line: int = None) -> str:
    try:
        p = Path(path)
        lines = p.read_text(encoding="utf-8").splitlines()
        start = max(1, start_line) - 1
        end = min(len(lines), end_line) if end_line else len(lines)
        content = "\n".join(lines[start:end])
        return f"--- {path} ---\n{content[:50000]}"
    except Exception as e:
        return f"Error: {e}"

@tool(
    name="write_file",
    description="Write content to a file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Save path."},
            "content": {"type": "string", "description": "Content to write."}
        },
        "required": ["path", "content"]
    }
)
def write_file(path: str, content: str) -> str:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error: {e}"
