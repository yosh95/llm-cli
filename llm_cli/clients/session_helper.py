# llm_cli/clients/session_helper.py
from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.rule import Rule

from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.ui import console

if TYPE_CHECKING:
    from llm_cli.clients.session import ChatSession


def sanitize_tool_history(conversation: list[Message]) -> list[Message]:
    """Remove or flatten orphaned tool_use / tool_result pairs.

    When switching providers (e.g. OpenAI → Claude) the conversation may contain
    tool-call messages that were produced by the previous provider.  Claude
    requires that every ``tool_result`` block is immediately preceded by an
    ``assistant`` message that contains a matching ``tool_use`` block with the
    same ``id``.  If that invariant is violated (different ID schemes, a 503
    that interrupted the response, etc.) Claude returns a 400 error.

    This function collapses any MODEL message that carries *only* tool-call
    parts (no visible text) together with the following TOOL message into a
    single plain-text USER message that summarises what happened.  Pairs that
    *do* match are left intact so that a Claude-originated tool sequence
    continues to work correctly after an in-session provider switch.
    """
    if not conversation:
        return conversation

    # Build a set of tool-use ids that appear in MODEL messages so we can
    # verify that the subsequent TOOL messages actually match.
    sanitized: list[Message] = []
    i = 0
    while i < len(conversation):
        msg = conversation[i]

        # Only inspect proper Message objects with function_call parts.
        # Plain dicts (e.g. from legacy sessions or tests) are passed through.
        if not isinstance(msg, Message):
            sanitized.append(msg)
            i += 1
            continue

        if msg.role == Role.MODEL:
            call_parts = [p for p in msg.parts if isinstance(p, ContentPart) and p.function_call]
            text_parts = [
                p
                for p in msg.parts
                if (isinstance(p, str) and p.strip())
                or (isinstance(p, ContentPart) and p.text and not p.is_diagnostic)
            ]

            if call_parts:
                # Collect the IDs that *this* assistant message advertises.
                advertised_ids: set[str] = set()
                for cp in call_parts:
                    fc = cp.function_call or {}
                    uid = fc.get("call_id") or fc.get("id")
                    if uid:
                        advertised_ids.add(uid)

                # Look ahead: is the next message a TOOL message?
                next_msg = conversation[i + 1] if i + 1 < len(conversation) else None
                if not next_msg or next_msg.role != Role.TOOL:
                    # Orphaned tool_use with no following tool_result at all
                    summary_lines: list[str] = []
                    if text_parts:
                        for p in text_parts:
                            t = p if isinstance(p, str) else (p.text or "")
                            if t.strip():
                                summary_lines.append(t.strip())
                    for cp in call_parts:
                        fc = cp.function_call or {}
                        summary_lines.append(
                            f"[Tool call: {fc.get('name', '?')} "
                            f"(id={fc.get('call_id') or fc.get('id', '?')}) — "
                            f"cancelled, no result]"
                        )
                    combined = "\n".join(summary_lines)
                    sanitized.append(
                        Message(
                            role=Role.MODEL,
                            parts=[ContentPart(text=combined)],
                        )
                    )
                    i += 1
                    continue
                if next_msg.role == Role.TOOL:
                    result_ids: set[str] = set()
                    for p in next_msg.parts:
                        if isinstance(p, ContentPart) and p.function_response:
                            fr = p.function_response
                            uid = fr.get("call_id") or fr.get("id")
                            if uid:
                                result_ids.add(uid)

                    # If IDs match (or both sets are empty) keep the pair as-is.
                    if advertised_ids == result_ids or (not advertised_ids and not result_ids):
                        sanitized.append(msg)
                        sanitized.append(next_msg)
                        i += 2
                        continue

                    # Mismatch — flatten both messages into descriptive text.
                    summary_lines = []
                    if text_parts:
                        for p in text_parts:
                            t = p if isinstance(p, str) else (p.text or "")
                            if t.strip():
                                summary_lines.append(t.strip())
                    for cp in call_parts:
                        fc = cp.function_call or {}
                        summary_lines.append(
                            f"[Tool call: {fc.get('name', '?')} "
                            f"(id={fc.get('call_id') or fc.get('id', '?')})]"
                        )
                    for p in next_msg.parts:
                        if isinstance(p, ContentPart) and p.function_response:
                            fr = p.function_response
                            result = fr.get("response", {}).get("result", "") or ""
                            summary_lines.append(
                                f"[Tool result: {fr.get('name', '?')} → {str(result)[:200]}]"
                            )
                    combined = "\n".join(summary_lines)
                    sanitized.append(
                        Message(
                            role=Role.MODEL,
                            parts=[ContentPart(text=combined)],
                        )
                    )
                    sanitized.append(
                        Message(
                            role=Role.USER,
                            parts=["(Tool results incorporated above.)"],
                        )
                    )
                    i += 2
                    continue

        sanitized.append(msg)
        i += 1

    return sanitized


def handle_checkpoint(session: ChatSession) -> None:
    """Perform a summary and history compression."""
    from llm_cli.modules.custom_markdown import CustomMarkdown
    from llm_cli.modules.models import ContentPart, Message

    summarize_prompt = (
        "Summarize the conversation so far, preserving key context, "
        "decisions, code changes, and remaining tasks. "
        "Be comprehensive but concise."
    )

    original_state = session.client.get_conversation_state()
    prompt_source = DataSource(content=summarize_prompt, content_type="text/plain")

    try:
        console.print(f"[bold cyan]Summarizing ({session.client.model})...[/bold cyan]")
        res = session.client._send([prompt_source])
        response_tuple, _ = res if res else ((None, None), None)
        summary = response_tuple[0]

        if not summary:
            console.print("[red]Failed to generate summary.[/red]")
            session.client.set_conversation_state(original_state)
            return

        console.print("[bold cyan]Proposed Context Summary[/bold cyan]")
        console.print(CustomMarkdown(summary))

        console.print(Rule(style="dim"))
        if session.ui.confirm("Clear history and use this summary? (y/N): "):
            session.client.clear_history()
            summary_text = f"SYSTEM: History cleared. Continue from this summary:\n\n{summary}"
            session.client.conversation = [
                Message(
                    role=Role.USER,
                    parts=[ContentPart(text=summary_text)],
                )
            ]
            console.print("[green][bold green]OK[/bold green] Context refreshed.[/green]")
            console.print(Rule(style="dim"))
        else:
            session.client.set_conversation_state(original_state)
            console.print(Rule(style="dim"))
    except Exception as e:
        console.print(f"[bold red]Checkpoint failed: {e}[/bold red]")
        session.client.set_conversation_state(original_state)


def log_chat(session: ChatSession, content: Any, role: str) -> None:
    """Write chat interactions to a persistent log file."""
    if not session.client.chat_log_path:
        return

    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        path = Path(session.client.chat_log_path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

        text_content = ""
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, DataSource):
                    parts.append(str(item.content))
                else:
                    parts.append(str(item))
            text_content = "\n".join(parts)
        else:
            text_content = str(content)

        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {timestamp} [{role}] ---\n{text_content}\n")
    except Exception:
        pass
