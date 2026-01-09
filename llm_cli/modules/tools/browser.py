# llm_cli/modules/tools/browser.py

import base64
import time
from typing import Any, Dict

from rich.console import Console

from llm_cli.modules.tool_registry import tool

# Conditional import to prevent errors on environments like Termux where playwright is not installed.
try:
    import nest_asyncio
    from playwright.sync_api import Page, sync_playwright

    # Apply nest_asyncio to allow Playwright's event loop to run inside prompt-toolkit's event loop.
    # This resolves the "RuntimeError: asyncio.run() cannot be called from a running event loop".
    nest_asyncio.apply()
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

console = Console()

# Global state to maintain the browser session.
_state: Dict[str, Any] = {
    "playwright": None,
    "browser": None,
    "context": None,
    "page": None
}

def _get_page() -> Page:
    """
    Initializes or returns the existing browser instance in 'headed' mode (headless=False).
    This ensures the user can visually monitor the agent's actions.
    """
    if _state["page"] is None:
        if _state["playwright"] is None:
            _state["playwright"] = sync_playwright().start()
        if _state["browser"] is None:
            # We use headless=False to comply with the security policy of visibility.
            _state["browser"] = _state["playwright"].chromium.launch(headless=False)
        if _state["context"] is None:
            _state["context"] = _state["browser"].new_context(
                viewport={"width": 1280, "height": 720}
            )
        _state["page"] = _state["context"].new_page()
    return _state["page"]

if HAS_PLAYWRIGHT:

    @tool(
        name="browser_navigate",
        description=(
            "Navigates to a specified URL in the browser. "
            "Execution requires user approval at the CLI prompt level."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The destination URL."},
                "explanation": {"type": "string", "description": "Reason for navigating to this URL."}
            },
            "required": ["url", "explanation"]
        }
    )
    def browser_navigate(url: str, explanation: str) -> str:
        # User confirmation is handled by the main CLI tool-calling logic.
        try:
            page = _get_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            status = response.status if response else "unknown"
            return f"Successfully navigated to '{url}' (Status: {status}). Page title: {page.title()}"
        except Exception as e:
            return f"Navigation failed: {e}"

    @tool(
        name="browser_click",
        description="Clicks an element on the page. Requires user approval at the CLI prompt level.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "The CSS selector of the element to click."},
                "explanation": {"type": "string", "description": "Reason for clicking this element."}
            },
            "required": ["selector", "explanation"]
        }
    )
    def browser_click(selector: str, explanation: str) -> str:
        try:
            page = _get_page()
            page.click(selector, timeout=10000)
            # Short sleep to allow the user to see the result of the click.
            time.sleep(1)
            return f"Successfully clicked on '{selector}'."
        except Exception as e:
            return f"Click failed: {e}"

    @tool(
        name="browser_type",
        description="Types text into an input field. Requires user approval at the CLI prompt level.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {"type": "string", "description": "The CSS selector for the input field."},
                "text": {"type": "string", "description": "The text to type."},
                "explanation": {"type": "string", "description": "Reason for this input."},
                "press_enter": {"type": "boolean", "description": "Whether to press Enter after typing.", "default": False}
            },
            "required": ["selector", "text", "explanation"]
        }
    )
    def browser_type(selector: str, text: str, explanation: str, press_enter: bool = False) -> str:
        try:
            page = _get_page()
            page.fill(selector, text, timeout=10000)
            if press_enter:
                page.keyboard.press("Enter")
            time.sleep(1)
            return "Successfully completed the input action."
        except Exception as e:
            return f"Input failed: {e}"

    @tool(
        name="browser_get_content",
        description=(
            "Retrieves the text content of the current page. "
            "This is a read-only operation."
        ),
        parameters={"type": "object", "properties": {}}
    )
    def browser_get_content() -> str:
        try:
            page = _get_page()
            title = page.title()
            # Extracts visible text from the body, limited to 5000 characters to save tokens.
            content = page.inner_text("body")[:5000]
            return f"Page Title: {title}\n\nContent Excerpt:\n{content}"
        except Exception as e:
            return f"Failed to retrieve content: {e}"

    @tool(
        name="browser_screenshot",
        description="Captures a screenshot of the current browser view and sends it to the AI.",
        parameters={"type": "object", "properties": {}}
    )
    def browser_screenshot() -> dict:
        try:
            page = _get_page()
            screenshot_bytes = page.screenshot(type="png", full_page=False)
            b64_data = base64.b64encode(screenshot_bytes).decode("utf-8")

            return {
                "result": "Screenshot captured and added to the AI context.",
                "__llm_cli_data__": {
                    "content": b64_data,
                    "content_type": "image/png",
                    "is_file_or_url": True
                }
            }
        except Exception as e:
            return {"result": f"Failed to capture screenshot: {e}"}

    @tool(
        name="browser_close",
        description="Closes the active browser session.",
        parameters={"type": "object", "properties": {}}
    )
    def browser_close() -> str:
        global _state
        try:
            if _state["browser"]:
                _state["browser"].close()
            if _state["playwright"]:
                _state["playwright"].stop()
            _state = {"playwright": None, "browser": None, "context": None, "page": None}
            return "Browser session closed successfully."
        except Exception as e:
            return f"Error while closing the browser: {e}"
