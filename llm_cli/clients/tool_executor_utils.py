# llm_cli/clients/tool_executor_utils.py

from rich.markup import escape

from llm_cli.clients.tool_executor_types import ToolExecutionContext
from llm_cli.modules.models import ContentPart
from llm_cli.ui import print_block

from .tool_executor_ui import (
    display_tool_request,
    preview_diff,
    preview_edit_diff,
    preview_python_code,
)


def display_execution_details(
    ctx: ToolExecutionContext, auto_approved: bool = False, delay: float = 0.0
) -> None:
    """Displays tool request and relevant previews (diffs, code)."""
    display_tool_request(ctx, auto_approved=auto_approved, delay=delay)
    if any(k in ctx.name for k in ("write_file", "create_or_overwrite_file")):
        preview_diff(ctx.args)
    elif "edit_file" in ctx.name:
        preview_edit_diff(ctx.args)
    elif "execute_python" in ctx.name:
        preview_python_code(ctx.args)


def truncate_output(res_str: str) -> str:
    from llm_cli.consts import MAX_OUTPUT_CHARS, MAX_OUTPUT_LINES

    original_len = len(res_str)
    original_lines = res_str.splitlines()
    original_lines_count = len(original_lines)

    if original_lines_count > MAX_OUTPUT_LINES or original_len > MAX_OUTPUT_CHARS:
        # Perform truncation
        truncated_lines = original_lines[:MAX_OUTPUT_LINES]
        res_str = "\n".join(truncated_lines)[:MAX_OUTPUT_CHARS]

        # Count lines and chars *before* appending the footer to avoid reporting
        # a truncated partial line as a full line, and to keep the char count
        # consistent with what was actually shown.
        shown_lines_count = len(truncated_lines)
        shown_chars = len(res_str)
        res_str += (
            f"\n\n... (Output truncated. Shown {shown_lines_count} of "
            f"{original_lines_count} lines, {shown_chars} of {original_len} chars.)"
        )
    return res_str


def create_error_response(ctx: ToolExecutionContext) -> ContentPart:
    err = ctx.error_message or "Unknown error"
    if (
        not err.startswith("[ERROR]")
        and not err.startswith("[DENIED]")
        and not err.startswith("Error:")
        and not err.startswith("Security Error:")
    ):
        err = f"[ERROR] {err}"
    return ContentPart(
        function_response={
            "id": ctx.tool_id,
            "call_id": ctx.call_id,
            "name": ctx.name,
            "response": {"result": err},
        },
        thought_signature=ctx.thought_signature,
    )


def print_tool_output(res_str: str) -> None:
    print_block(
        escape(res_str),
        title="[OK] Tool Output",
        style="green",
    )
