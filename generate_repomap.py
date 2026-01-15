#!/usr/bin/env python3

import ast
import os

# Directories to exclude from scanning
EXCLUDE_DIRS = {
    ".git", "__pycache__", "venv", ".venv", "build", "dist",
    ".egg-info", "node_modules", ".ruff_cache", ".pytest_cache"
}
# Files to exclude from scanning
EXCLUDE_FILES = {"REPOMAP.md", "generate_repomap.py"}


def get_docstring(node):
    """Extract the first line of the docstring from a node."""
    doc = ast.get_docstring(node)
    if doc:
        return doc.split("\n")[0].strip()
    return ""


def parse_python_file(file_path):
    """Parse a Python file and return a summary of its structure."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            tree = ast.parse(content)
    except Exception as e:
        return f"  (Error parsing file: {e})"

    output = []

    # Module-level docstring
    file_doc = get_docstring(tree)
    if file_doc:
        output.append(f"# {file_doc}")

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            doc = get_docstring(node)
            output.append(f"class {node.name}:" + (f"  # {doc}" if doc else ""))
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    doc_func = get_docstring(item)
                    args = [a.arg for a in item.args.args]
                    is_async = isinstance(item, ast.AsyncFunctionDef)
                    prefix = "async def" if is_async else "def"
                    line = f"    {prefix} {item.name}({', '.join(args)})"
                    if doc_func:
                        line += f"  # {doc_func}"
                    output.append(line)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = get_docstring(node)
            args = [a.arg for a in node.args.args]
            is_async = isinstance(node, ast.AsyncFunctionDef)
            prefix = "async def" if is_async else "def"
            line = f"{prefix} {node.name}({', '.join(args)})"
            if doc:
                line += f"  # {doc}"
            output.append(line)

    return "\n".join(output)


def generate_repomap():
    """Scan the project and generate REPOMAP.md."""
    repo_map = ["# Project Repository Map\n"]
    desc = "This file is an automatically generated map of the project structure."
    repo_map.append(f"{desc}\n")

    # Generate Directory Tree
    repo_map.append("## File Tree\n```text")
    tree_lines = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        level = root.replace(".", "").count(os.sep)
        indent = "  " * level
        tree_lines.append(f"{indent}{os.path.basename(root)}/")
        sub_indent = "  " * (level + 1)
        for f in sorted(files):
            if f not in EXCLUDE_FILES and not f.endswith((".pyc", ".pyo")):
                tree_lines.append(f"{sub_indent}{f}")
    repo_map.append("\n".join(tree_lines))
    repo_map.append("```\n")

    # Detailed Definitions
    repo_map.append("## Definitions\n")
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for file in sorted(files):
            if file.endswith(".py") and file not in EXCLUDE_FILES:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, ".")

                repo_map.append(f"### {rel_path}")
                repo_map.append("```python")
                structure = parse_python_file(full_path)
                if not structure:
                    structure = "# No classes or functions defined."
                repo_map.append(structure)
                repo_map.append("```\n")

    with open("REPOMAP.md", "w", encoding="utf-8") as f:
        f.write("\n".join(repo_map))

    print("REPOMAP.md has been generated successfully.")


if __name__ == "__main__":
    generate_repomap()
