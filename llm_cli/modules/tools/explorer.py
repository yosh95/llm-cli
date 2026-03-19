# llm_cli/modules/tools/explorer.py

import ast
from pathlib import Path

from llm_cli.modules.tool_registry import tool


def generate_repository_map(
    root_dir: str = ".", ignore_dirs: list[str] | None = None
) -> str:
    """
    Scans the repository and generates a structured map of Python symbols.

    Includes classes, methods, and functions using AST parsing.
    This function is designed to be verifiable by the AI agent itself.

    Args:
        root_dir: The root directory to start scanning.
        ignore_dirs: List of directory names to ignore (e.g., ['.git', 'venv']).

    Returns:
        A formatted string representing the repository structure.
    """
    if ignore_dirs is None:
        ignore_dirs = [".git", "__pycache__", "node_modules", ".venv", "venv", "tests"]

    repo_map = []
    root_path = Path(root_dir).resolve()

    for path in sorted(root_path.rglob("*.py")):
        # Check if any parent directory is in ignore_dirs
        if any(part in ignore_dirs or part.startswith(".") for part in path.parts):
            continue

        relative_path = path.relative_to(root_path)
        repo_map.append(f"### File: {relative_path}")

        try:
            with path.open(encoding="utf-8") as f:
                content = f.read()
                tree = ast.parse(content)

            file_symbols = []
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    doc = ast.get_docstring(node)
                    doc_line = f" - {doc.splitlines()[0]}" if doc else ""
                    file_symbols.append(f"- `class {node.name}`{doc_line}")

                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            f_doc = ast.get_docstring(item)
                            f_doc_line = f" - {f_doc.splitlines()[0]}" if f_doc else ""
                            file_symbols.append(f"  - `method {item.name}`{f_doc_line}")

                elif isinstance(node, ast.FunctionDef):
                    doc = ast.get_docstring(node)
                    doc_line = f" - {doc.splitlines()[0]}" if doc else ""
                    file_symbols.append(f"- `function {node.name}`{doc_line}")

            if file_symbols:
                repo_map.extend(file_symbols)
            else:
                repo_map.append("(No public classes or functions found)")

            repo_map.append("")  # Spacer

        except Exception as e:
            repo_map.append(f"Error parsing {relative_path}: {str(e)}")

    return "\n".join(repo_map)


@tool(
    name="get_repository_structure",
    description=(
        "Returns a comprehensive map of all Python classes, methods, and "
        "functions in the repository along with their docstrings. This is "
        "essential for understanding the project structure without "
        "reading every file."
    ),
)
def get_repository_structure(explanation: str) -> str:
    """
    Executes the repository map generation.

    Args:
        explanation: A detailed explanation of why you need to see the structure.
    """
    # Explanation is logged by the tool wrapper, but we include it in the signature
    # to enforce clarity from the AI caller.
    _ = explanation
    return generate_repository_map()
