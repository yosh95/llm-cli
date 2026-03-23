# llm_cli/modules/tools/web.py

import functools
from collections.abc import Callable
from typing import Any

from llm_cli.consts import MAX_OUTPUT_CHARS, MAX_OUTPUT_LINES
from llm_cli.modules.tool_registry import tool
from llm_cli.security.pqc import sign_tool_result

# --- Decorator ---


def web_tool_handler(
    func: Callable[..., Any],
) -> Callable[..., Any]:
    """
    Decorator to handle common web tool logic:
    1. Exception Handling
    2. PQC Signature Signing for consistent security
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Extract PQC variant from security requirements (injected by registry)
        reqs = kwargs.pop("__security_requirements__", None)
        variant_raw = reqs.get("pqc_variant") if isinstance(reqs, dict) else None
        variant = str(variant_raw) if variant_raw else "ML-DSA-65"

        try:
            result = func(*args, **kwargs)

            # Apply PQC signing to the result (if it's a string)
            return (
                sign_tool_result(result, variant=variant)
                if isinstance(result, str)
                else result
            )
        except Exception as e:
            return sign_tool_result(f"Error: {e}", variant=variant)

    return wrapper


# --- Tools ---


@tool(
    name="read_url_content",
    desc=(
        "Fetch a web page URL or PDF URL and convert the content to Markdown or text. "
        "For PDFs, text content will be extracted. "
        f"IMPORTANT: This tool can read up to {MAX_OUTPUT_LINES} lines or "
        f"{MAX_OUTPUT_CHARS} characters at once. "
        "If the content is longer, the tail will be omitted. "
        "Use 'start_line' and 'end_line' to read specific chunks of large pages."
    ),
    params={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Target URL."},
            "start_line": {
                "type": "integer",
                "description": "First line to read (1-indexed).",
                "default": 1,
            },
            "end_line": {
                "type": "integer",
                "description": (
                    f"Last line to read (Max {MAX_OUTPUT_LINES} lines "
                    "from start_line recommended)."
                ),
            },
        },
        "required": ["url"],
    },
)
@web_tool_handler
def read_url_content(url: str, start_line: int = 1, end_line: int | None = None) -> str:
    from llm_cli.modules.media_utils import fetch_url_content

    content, ctype = fetch_url_content(url, pdf_as_base64=False)

    if content is None or ctype is None:
        return f"Error: Failed to fetch content from {url} or invalid URL."

    # fetch_url_content returns 'text/plain' for both raw text and extracted PDF text
    if "text/html" not in ctype and "text/plain" not in ctype:
        return (
            f"Error: URL returned {ctype}, expected text/html, text/plain or "
            "application/pdf."
        )

    lines = content.splitlines()
    start = max(1, start_line) - 1
    end = min(len(lines), end_line) if end_line else len(lines)
    selected_lines = lines[start:end]

    return "\n".join(selected_lines)
