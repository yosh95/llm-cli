# llm_cli/clients/session_helper.py
from __future__ import annotations

import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from llm_cli.modules.models import DataSource, Role
from llm_cli.ui import console

if TYPE_CHECKING:
    from llm_cli.clients.session import ChatSession


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
        console.print(
            f"[bold cyan]🤔 Summarizing ({session.client.model})...[/bold cyan]"
        )
        res = session.client._send([prompt_source])
        response_tuple, _ = res if res else ((None, None), None)
        summary = response_tuple[0]

        if not summary:
            console.print("[red]Failed to generate summary.[/red]")
            session.client.set_conversation_state(original_state)
            return

        console.print("[bold cyan]Proposed Context Summary[/bold cyan]")
        console.print(CustomMarkdown(summary))

        if session.ui.confirm("Clear history and use this summary? (y/N): "):
            session.client.clear_history()
            summary_text = (
                f"SYSTEM: History cleared. Continue from this summary:\n\n{summary}"
            )
            session.client.conversation = [
                Message(
                    role=Role.USER,
                    parts=[ContentPart(text=summary_text)],
                )
            ]
            console.print("[green]✅ Context refreshed.[/green]")
        else:
            session.client.set_conversation_state(original_state)
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
