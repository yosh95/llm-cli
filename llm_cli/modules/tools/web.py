# llm_cli/modules/tools/web.py

import urllib.parse
from pathlib import Path

import requests

from llm_cli.clients.config import get_setting
from llm_cli.modules.media_utils import fetch_url_content
from llm_cli.modules.tool_registry import tool

# Check for Brave Search configuration
_brave_api_key = get_setting("api_key", "brave")


if _brave_api_key:

    @tool(
        name="search_web",
        description=(
            "Search the web using Brave Search to find information on the internet."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query (keywords or question).",
                },
            },
            "required": ["query"],
        },
    )
    def search_web(query: str) -> str:
        if not _brave_api_key:
            return "Error: Brave Search API key required."

        try:
            url = "https://api.search.brave.com/res/v1/web/search"
            headers = {
                "Accept": "application/json",
                "X-Subscription-Token": _brave_api_key,
            }
            params = {"q": query}
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("web", {}).get("results", [])
            if not results:
                return f"### Search Results for: {query}\n\nNo results found."

            output = [f"### Search Results for: {query}\n"]
            for i, res in enumerate(results[:10], 1):
                title = res.get("title", "No Title")
                link = res.get("url", "#")
                snippet = res.get("description", "No description available.")
                output.append(f"{i}. **[{title}]({link})**")
                output.append(f"   {snippet}\n")

            return "\n".join(output)
        except Exception as e:
            return f"Error searching '{query}' with Brave Search: {e}"


@tool(
    name="read_html_from_url",
    description=(
        "Fetch a web page URL and convert the HTML content to Markdown text. "
    ),
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Target URL."}},
        "required": ["url"],
    },
)
def read_html_from_url(url: str) -> str:
    content, ctype = fetch_url_content(url, pdf_as_base64=False)

    if content is None or ctype is None:
        return f"Error: Failed to fetch content from {url} or invalid URL."

    if "text/html" not in ctype and "text/plain" not in ctype:
        return (
            f"Error: URL returned {ctype}, expected text/html or text/plain. "
            "Use 'read_pdf_from_url' for PDFs or 'read_pdf_text_from_url' for text."
        )

    return content


@tool(
    name="read_pdf_from_url",
    description=(
        "Download a PDF from a URL and add it to the conversation context "
        "as a binary attachment. Use this if you have vision capabilities "
        "to analyze diagrams or charts."
    ),
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Target PDF URL."}},
        "required": ["url"],
    },
)
def read_pdf_from_url(url: str) -> str | dict:
    # Use fetch_url_content with pdf_as_base64=True to get base64
    content, ctype = fetch_url_content(url, pdf_as_base64=True)

    if content is None or ctype is None:
        return "Error: Failed to fetch content or invalid URL."

    if "application/pdf" not in ctype:
        return f"Error: Expected PDF but got {ctype}. Content might not be a PDF."

    parsed_url = urllib.parse.urlparse(url)
    filename = Path(parsed_url.path).name or "downloaded_file.pdf"
    if not filename.lower().endswith(".pdf"):
        filename += ".pdf"

    return {
        "result": (
            f"Successfully fetched PDF from {url}. "
            "The content has been added to the conversation context "
            "as a binary attachment. Please analyze the attached file."
        ),
        "__llm_cli_data__": {
            "content": content,
            "content_type": ctype,
            "is_file_or_url": True,
            "metadata": {"filename": filename},
        },
    }


@tool(
    name="read_pdf_text_from_url",
    description=(
        "Download a PDF from a URL and extract its text content. Use this "
        "if you only need the text or do not have vision capabilities."
    ),
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Target PDF URL."}},
        "required": ["url"],
    },
)
def read_pdf_text_from_url(url: str) -> str:
    # Use fetch_url_content with pdf_as_base64=False to get text
    content, ctype = fetch_url_content(url, pdf_as_base64=False)

    if content is None or ctype is None:
        return "Error: Failed to fetch content or invalid URL."

    if "application/pdf" not in ctype and ctype != "text/plain":
        return f"Error: Expected PDF but got {ctype}."

    return content
