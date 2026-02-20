# llm_cli/modules/tools/web.py

import re

import requests

from llm_cli.clients.config import get_setting
from llm_cli.modules.media_utils import fetch_url_content
from llm_cli.modules.tool_registry import tool

# Check for Google Search configuration
_google_api_key = get_setting("api_key", "google")
_google_search_model = get_setting("search_model", "google") or "gemini-3-flash-preview"


if _google_api_key:

    @tool(
        name="search_web",
        description=(
            "Perform a web search using Gemini's Google Search tool "
            "to find information on the internet."
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
        if not _google_api_key:
            return "Error: Web Search configuration missing (Google API key required)."

        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{_google_search_model}:generateContent"
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "text": (
                                    "Please search the web for the following query "
                                    "and provide a comprehensive summary or answer "
                                    "based on the search results. Include source "
                                    f"URLs where applicable. Query: {query}"
                                )
                            }
                        ],
                    }
                ],
                "tools": [{"googleSearch": {}}],
            }
            headers = {
                "x-goog-api-key": _google_api_key,
                "Content-Type": "application/json",
            }

            resp = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            res_json = resp.json()

            candidates = res_json.get("candidates", [])
            if not candidates:
                return f"### Results for: {query}\nNo results found."

            content = candidates[0].get("content", {})
            parts = content.get("parts", [])

            if not parts:
                return f"### Results for: {query}\nEmpty response received."

            answer = parts[0].get("text", "")

            # Extract source URLs from grounding metadata
            grounding_metadata = candidates[0].get("groundingMetadata", {})
            grounding_chunks = grounding_metadata.get("groundingChunks", [])

            urls = []
            for chunk in grounding_chunks:
                web = chunk.get("web", {})
                uri = web.get("uri")
                title = web.get("title")
                if uri and title:
                    urls.append(f"- [{title}]({uri})")

            if urls:
                # Remove duplicates while preserving order
                urls = list(dict.fromkeys(urls))
                answer += "\n\n**Sources:**\n" + "\n".join(urls)

            return f"### Search Results for: {query}\n\n{answer}"
        except Exception as e:
            return f"Error searching '{query}': {e}"


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
            "Use 'read_pdf_from_url' for PDFs or 'read_image_from_url' for images."
        )

    # Post-processing to remove excessive newlines
    # fetch_url_content already handles markdownify for HTML
    content = re.sub(r"\n{3,}", "\n\n", content).strip()

    return content


@tool(
    name="read_pdf_from_url",
    description=("Download a PDF from a URL and add it to the context. "),
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
        },
    }


@tool(
    name="read_image_from_url",
    description="Fetch an image from a URL and return it for visual processing.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Target Image URL."}},
        "required": ["url"],
    },
)
def read_image_from_url(url: str) -> str | dict:
    # Use fetch_url_content with pdf_as_base64=True (default) to get base64
    content, ctype = fetch_url_content(url, pdf_as_base64=True)

    if content is None or ctype is None:
        return "Error: Failed to fetch content or invalid URL."

    if not ctype.startswith("image/"):
        return f"Error: URL returned {ctype}, expected an image type."

    return {
        "result": (
            f"Successfully fetched image from {url}. "
            "The content has been added to the conversation context "
            "as a binary attachment. Please analyze the attached file."
        ),
        "__llm_cli_data__": {
            "content": content,
            "content_type": ctype,
            "is_file_or_url": True,
        },
    }
