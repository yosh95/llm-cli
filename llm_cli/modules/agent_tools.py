# llm_cli/modules/agent_tools.py
import subprocess
import requests
import base64
import cloudscraper
import filetype
from pathlib import Path
from llm_cli.clients.config import get_setting


def list_files(
    directory: str = ".",
    depth: int = 1,
    max_files: int = 500
) -> str:
    """
    List files and directories.
    Use depth to control how deep to go (default 1 for current dir only).
    """
    try:
        directory = directory or "."
        base_path = Path(directory)

        exclude = {
            ".git", "__pycache__", "node_modules",
            ".venv", ".pytest_cache", ".DS_Store"
        }

        results = []
        file_count = 0

        def walk(current_path, current_depth):
            nonlocal file_count
            if depth is not None and current_depth > depth:
                return

            try:
                # Get entries and sort them (dirs first, then files)
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
        return f"Error: {str(e)}"


def read_file(path: str, start_line: int = 1, end_line: int = None) -> str:
    """
    Read the content of a file.
    Optional start_line and end_line (1-indexed) can be used to read parts.
    """
    try:
        p = Path(path)
        if not p.is_file():
            return f"Error: {path} is not a file."

        lines = p.read_text(encoding="utf-8").splitlines()
        total_lines = len(lines)

        # Basic bounds checking
        start = max(1, start_line) - 1
        end = min(total_lines, end_line) if end_line else total_lines

        content = "\n".join(lines[start:end])

        if end_line or start_line > 1:
            header = (
                f"--- Reading {path} (Lines {start+1} to {end} "
                f"of {total_lines}) ---\n"
            )
        else:
            header = f"--- Reading {path} ({total_lines} lines) ---\n"
            # Hard limit for safety if not specified
            if len(content) > 50000:
                trunc_msg = "\n... (Content truncated for length) ..."
                content = content[:50000] + trunc_msg

        return header + content
    except Exception as e:
        return f"Error reading {path}: {str(e)}"


def write_file(path: str, content: str) -> str:
    """Write or overwrite content to a specified file path."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing to {path}: {str(e)}"


def execute_command(command: str) -> str:
    """Execute a shell command and return output (truncated if too long)."""
    try:
        # Use a timeout to prevent infinite loops
        result = subprocess.run(command,
                                shell=True,
                                capture_output=True,
                                text=True,
                                timeout=60)

        stdout = result.stdout
        stderr = result.stderr

        # Truncate if output is massive (e.g., > 10000 chars)
        max_chars = 10000
        if len(stdout) > max_chars:
            half = max_chars // 2
            stdout = (
                stdout[:half] +
                "\n... (Omitted for brevity) ...\n" +
                stdout[-half:]
            )

        output = f"STDOUT:\n{stdout}\n"
        if stderr:
            if len(stderr) > max_chars:
                half = max_chars // 2
                stderr = (
                    stderr[:half] +
                    "\n... (Omitted for brevity) ...\n" +
                    stderr[-half:]
                )
            output += f"STDERR:\n{stderr}\n"

        output += f"Exit Code: {result.returncode}"
        return output
    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 60 seconds."
    except Exception as e:
        return f"Error executing command: {str(e)}"


def google_search(
    queries: list[str]
) -> str:
    """
    Perform a Google Search using the Custom Search JSON API.
    """
    api_key = get_setting("api_key", "google")
    cse_id = get_setting("cse_id", "google")

    if not api_key or not cse_id:
        return ("Error: Google API key or Search Engine ID (cse_id) "
                "not configured in config.toml.")

    if isinstance(queries, str):
        queries = [queries]

    all_results = []
    search_url = "https://www.googleapis.com/customsearch/v1"

    for query in queries:
        params = {
            "key": api_key,
            "cx": cse_id,
            "q": query
        }
        try:
            response = requests.get(search_url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            items = data.get("items", [])

            results = []
            for item in items:
                title = item.get("title")
                link = item.get("link")
                snippet = item.get("snippet")
                results.append(
                    f"Title: {title}\nURL: {link}\nSnippet: {snippet}\n"
                )

            if results:
                all_results.append(f"### Results for: {query}\n" +
                                   "\n".join(results))
            else:
                all_results.append(f"No results found for: {query}")

        except Exception as e:
            all_results.append(f"Error searching for '{query}': {str(e)}")

    return "\n\n---\n\n".join(all_results)


def fetch_url(url: str) -> dict | str:
    """Fetch content from a URL."""
    scraper = cloudscraper.create_scraper()
    try:
        response = scraper.get(url, timeout=30)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '')

        if 'application/pdf' in content_type or \
           'image/' in content_type or \
           'audio/' in content_type:

            kind = filetype.guess(response.content)
            mime = kind.mime if kind else content_type.split(';')[0]
            b64_data = base64.b64encode(response.content).decode('utf-8')

            return {
                "result": f"Successfully fetched {mime} from {url}. "
                          "Content has been added to context.",
                "__llm_cli_data__": {
                    "content": b64_data,
                    "content_type": mime,
                    "is_file_or_url": True
                }
            }

        elif 'text/html' in content_type:
            return (
                f"Fetched HTML from {url} "
                f"(Length: {len(response.text)} chars):\n"
                f"{response.text[:20000]}..."
            )
        else:
            return response.text
    except Exception as e:
        return f"Error fetching {url}: {str(e)}"


# Map of function names to actual callables
TOOL_FUNCTIONS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "execute_command": execute_command,
    "google_search": google_search,
    "fetch_url": fetch_url,
}
