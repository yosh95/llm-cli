# llm_cli/modules/agent_tools.py
import subprocess
import requests
import base64
import cloudscraper
import filetype
from pathlib import Path
from llm_cli.clients.config import get_setting


def list_files(
    directory: str = ".", depth: int = 1, max_files: int = 500
) -> str:
    """List files and directories."""
    try:
        base_path = Path(directory or ".")
        exclude = {
            ".git", "__pycache__", "node_modules", ".venv",
            ".pytest_cache", ".DS_Store"
        }
        results, file_count = [], 0

        def walk(current_path, current_depth):
            nonlocal file_count
            if depth is not None and current_depth > depth:
                return
            try:
                entries = sorted(
                    list(current_path.iterdir()),
                    key=lambda x: (not x.is_dir(), x.name)
                )
            except PermissionError:
                return

            for entry in entries:
                if entry.name in exclude:
                    continue
                if file_count >= max_files:
                    if file_count == max_files:
                        results.append(
                            f"\n... (Limit of {max_files} files reached) ..."
                        )
                        file_count += 1
                    continue
                rel_path = entry.relative_to(base_path)
                prefix = "  " * (current_depth - 1)
                if entry.is_dir():
                    results.append(f"{prefix}📁 {rel_path}/")
                    walk(entry, current_depth + 1)
                else:
                    results.append(f"{prefix}📄 {rel_path}")
                    file_count += 1

        walk(base_path, 1)
        if not results:
            return "No files found."
        header = f"Listing contents of {directory} (depth={depth}):\n"
        return header + "\n".join(results)
    except Exception as e:
        return f"Error: {e}"


def read_file(path: str, start_line: int = 1, end_line: int = None) -> str:
    """Read file content with optional line range."""
    try:
        p = Path(path)
        if not p.is_file():
            return f"Error: {path} is not a file."
        lines = p.read_text(encoding="utf-8").splitlines()
        total = len(lines)
        start = max(1, start_line) - 1
        end = min(len(lines), end_line) if end_line else len(lines)
        content = "\n".join(lines[start:end])
        if end_line or start_line > 1:
            header = (
                f"--- Reading {path} (Lines {start+1} to {end} "
                f"of {total}) ---\n"
            )
        else:
            header = f"--- Reading {path} ({total} lines) ---\n"
            if len(content) > 50000:
                content = content[:50000] + "\n... (Content truncated) ..."
        return header + content
    except Exception as e:
        return f"Error reading {path}: {e}"


def write_file(path: str, content: str) -> str:
    """Write content to a file."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing to {path}: {e}"


def execute_command(command: str) -> str:
    """Execute shell command and return output."""
    try:
        res = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=60
        )

        def truncate(s, limit=10000):
            if len(s) <= limit:
                return s
            return (
                s[:limit // 2] + "\n... (Omitted) ...\n" + s[-limit // 2:]
            )

        output = f"STDOUT:\n{truncate(res.stdout)}"
        if res.stderr:
            output += f"\nSTDERR:\n{truncate(res.stderr)}"
        return f"{output}\nExit Code: {res.returncode}"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out (60s)."
    except Exception as e:
        return f"Error executing command: {e}"


def google_search(queries: list[str]) -> str:
    """Perform Google Search."""
    api_key = get_setting("api_key", "google")
    cse_id = get_setting("cse_id", "google")
    if not api_key or not cse_id:
        return "Error: Google API/CSE ID not configured."
    if isinstance(queries, str):
        queries = [queries]
    all_results = []
    for q in queries:
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={"key": api_key, "cx": cse_id, "q": q},
                timeout=15
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            results = [
                f"Title: {i.get('title')}\nURL: {i.get('link')}\n"
                f"Snippet: {i.get('snippet')}\n"
                for i in items
            ]
            if results:
                title = f"### Results for: {q}\n"
                all_results.append(title + "\n".join(results))
            else:
                all_results.append(f"No results for: {q}")
        except Exception as e:
            all_results.append(f"Error searching '{q}': {e}")
    return "\n\n---\n\n".join(all_results)


def fetch_url(url: str) -> dict | str:
    """Fetch URL content."""
    try:
        resp = cloudscraper.create_scraper().get(url, timeout=30)
        resp.raise_for_status()
        ctype = resp.headers.get('Content-Type', '')
        if any(t in ctype for t in ['pdf', 'image/', 'audio/']):
            kind = filetype.guess(resp.content)
            mime = kind.mime if kind else ctype.split(';')[0]
            b64 = base64.b64encode(resp.content).decode('utf-8')
            return {
                "result": f"Fetched {mime} from {url}. Added to context.",
                "__llm_cli_data__": {
                    "content": b64, "content_type": mime,
                    "is_file_or_url": True
                }
            }
        if 'text/html' in ctype:
            return (
                f"Fetched HTML from {url} (Length: {len(resp.text)}):\n"
                f"{resp.text[:20000]}..."
            )
        return resp.text
    except Exception as e:
        return f"Error fetching {url}: {e}"


TOOL_FUNCTIONS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "execute_command": execute_command,
    "google_search": google_search,
    "fetch_url": fetch_url,
}
