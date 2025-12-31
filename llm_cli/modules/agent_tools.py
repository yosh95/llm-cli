# llm_cli/modules/agent_tools.py
import subprocess
import os
import requests
import base64
import cloudscraper
import filetype
from pathlib import Path
from llm_cli.clients.config import get_setting


def list_files(directory: str = ".") -> str:
    """List all files in the given directory recursively."""
    try:
        # Handle empty/None passed from some providers by falling back to CWD
        directory = directory or "."

        paths = []
        # Exclude common large or sensitive folders
        exclude = {".git",
                   "__pycache__",
                   "node_modules",
                   ".venv",
                   ".pytest_cache"}
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if d not in exclude]
            for file in files:
                paths.append(os.path.relpath(os.path.join(root, file),
                                             directory))
        return "\n".join(paths) if paths else "No files found."
    except Exception as e:
        return f"Error: {str(e)}"


def read_file(path: str) -> str:
    """Read and return the content of a file."""
    try:
        return Path(path).read_text(encoding="utf-8")
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
    """Execute a shell command and return its output."""
    try:
        # Use a timeout to prevent infinite loops
        result = subprocess.run(command,
                                shell=True,
                                capture_output=True,
                                text=True,
                                timeout=60)
        output = f"STDOUT:\n{result.stdout}\n"
        if result.stderr:
            output += f"STDERR:\n{result.stderr}\n"
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


def checkpoint_conversation(summary: str) -> str:
    """
    Consolidate the current session into a summary and reset history.
    This helps keep the context window clean while maintaining vital info.
    """
    # The actual history clearing logic is handled in session.py
    return summary


# Map of function names to actual callables
TOOL_FUNCTIONS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "execute_command": execute_command,
    "google_search": google_search,
    "fetch_url": fetch_url,
    "checkpoint_conversation": checkpoint_conversation,
}
