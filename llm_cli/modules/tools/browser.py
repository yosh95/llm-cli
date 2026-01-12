# llm_cli/modules/tools/browser.py

import asyncio
import base64
from typing import Any, Dict

from rich.console import Console

from llm_cli.clients.config import get_setting
from llm_cli.modules.tool_registry import registry, tool

# Conditional import to prevent errors on environments
# like Termux where playwright is not installed.
try:
    import nest_asyncio
    from playwright.async_api import Page, async_playwright

    HAS_PLAYWRIGHT = True
    # Apply nest_asyncio once at the module level to avoid repeated patching
    # and potential interference with signal handlers.
    nest_asyncio.apply()
except ImportError:
    HAS_PLAYWRIGHT = False

console = Console()

# Global state to maintain the browser session.
_state: Dict[str, Any] = {
    "playwright": None,
    "browser": None,
    "context": None,
    "page": None,
}


if HAS_PLAYWRIGHT:

    async def _get_page() -> Page:
        """
        Initializes or returns the existing browser instance in 'headed' mode.
        (headless=False)
        This ensures the user can visually monitor the agent's actions.
        """
        if _state["page"] is None:
            if _state["playwright"] is None:
                _state["playwright"] = await async_playwright().start()
            if _state["browser"] is None:
                # We use headless=False to comply with the security policy of
                # visibility.
                _state["browser"] = await _state["playwright"].chromium.launch(
                    headless=False
                )
            if _state["context"] is None:
                _state["context"] = await _state["browser"].new_context(
                    viewport={"width": 1280, "height": 720}
                )
            _state["page"] = await _state["context"].new_page()
        return _state["page"]

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
                "explanation": {
                    "type": "string",
                    "description": "Reason for navigating to this URL.",
                },
            },
            "required": ["url", "explanation"],
        },
    )
    async def browser_navigate(url: str, explanation: str) -> str:
        # User confirmation is handled by the main CLI tool-calling logic.
        try:
            page = await _get_page()
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=30000
            )
            status = response.status if response else "unknown"
            msg = (
                f"Successfully navigated to '{url}' (Status: {status}). "
                f"Page title: {await page.title()}"
            )
            return msg
        except Exception as e:
            return f"Navigation failed: {e}"

    @tool(
        name="browser_click",
        description=(
            "Clicks an element on the page. "
            "Requires user approval at the CLI prompt level."
        ),
        parameters={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "The CSS selector of the element to click.",
                },
                "explanation": {
                    "type": "string",
                    "description": "Reason for clicking this element.",
                },
            },
            "required": ["selector", "explanation"],
        },
    )
    async def browser_click(selector: str, explanation: str) -> str:
        try:
            page = await _get_page()
            await page.click(selector, timeout=10000)
            # Short sleep to allow the user to see the result of the click.
            await asyncio.sleep(1)
            return f"Successfully clicked on '{selector}'."
        except Exception as e:
            return f"Click failed: {e}"

    @tool(
        name="browser_type",
        description=(
            "Types text into an input field. "
            "Requires user approval at the CLI prompt level."
        ),
        parameters={
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "The CSS selector for the input field.",
                },
                "text": {"type": "string", "description": "The text to type."},
                "explanation": {
                    "type": "string",
                    "description": "Reason for this input.",
                },
                "press_enter": {
                    "type": "boolean",
                    "description": "Whether to press Enter after typing.",
                    "default": False,
                },
            },
            "required": ["selector", "text", "explanation"],
        },
    )
    async def browser_type(
        selector: str, text: str, explanation: str, press_enter: bool = False
    ) -> str:
        try:
            page = await _get_page()
            await page.fill(selector, text, timeout=10000)
            if press_enter:
                await page.keyboard.press("Enter")
            await asyncio.sleep(1)
            return "Successfully completed the input action."
        except Exception as e:
            return f"Input failed: {e}"

    @tool(
        name="browser_get_content",
        description=(
            "Retrieves the text content of the current page. "
            "This is a read-only operation."
        ),
        parameters={"type": "object", "properties": {}},
    )
    async def browser_get_content() -> str:
        try:
            page = await _get_page()
            title = await page.title()
            # Extracts visible text from the body
            max_output = int(get_setting("max_browser_content_len", "general") or 30000)
            content = await page.inner_text("body")
            content = content[:max_output]
            return f"{title}\n\n{content}"
        except Exception as e:
            return f"Failed to retrieve content: {e}"

    @tool(
        name="browser_screenshot",
        description=(
            "Captures a screenshot of the current browser view and sends it to the AI."
        ),
        parameters={"type": "object", "properties": {}},
    )
    async def browser_screenshot() -> dict:
        try:
            page = await _get_page()
            screenshot_bytes = await page.screenshot(type="png", full_page=False)
            b64_data = base64.b64encode(screenshot_bytes).decode("utf-8")

            return {
                "result": "Screenshot captured and added to the AI context.",
                "__llm_cli_data__": {
                    "content": b64_data,
                    "content_type": "image/png",
                    "is_file_or_url": True,
                },
            }
        except Exception as e:
            return {"result": f"Failed to capture screenshot: {e}"}

    @tool(
        name="browser_close",
        description="Closes the active browser session.",
        parameters={"type": "object", "properties": {}},
    )
    async def browser_close() -> str:
        global _state
        try:
            if _state["browser"]:
                await _state["browser"].close()
            if _state["playwright"]:
                await _state["playwright"].stop()
            _state = {
                "playwright": None,
                "browser": None,
                "context": None,
                "page": None,
            }
            return "Browser session closed successfully."
        except Exception as e:
            return f"Error while closing the browser: {e}"

    # Register the browser_close function as a global shutdown hook
    registry.register_shutdown_hook(browser_close)
