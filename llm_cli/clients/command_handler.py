# llm_cli/clients/command_handler.py

import datetime
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from prompt_toolkit import prompt
from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.shortcuts import CompleteStyle
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax

from llm_cli.clients.config import get_setting, get_templates
from llm_cli.clients.exceptions import (
    CheckpointRequest,
    ExitRequest,
    TemplateRequest,
)

if TYPE_CHECKING:
    from llm_cli.clients.base import BaseLlmClient
    from llm_cli.modules.models import DataSource


SUPPORTED_COMMANDS = {
    "attach",
    "save",
    "load",
    "dump",
    "raw",
    "view",
    "v",
    "clear",
    "c",
    "quit",
    "q",
    "info",
    "i",
    "debug",
    "d",
    "model",
    "m",
    "provider",
    "p",
    "template",
    "t",
    "checkpoint",
    "cp",
    "reload",
    "tools",
    "help",
    "h",
}


def handle_command(
    client: "BaseLlmClient",
    user_input: str,
    _sources: Any,
    pending_data: list["DataSource"] | None = None,
) -> bool:
    """Handles in-chat slash commands."""
    from llm_cli.clients.base import console
    from llm_cli.modules.models import ContentPart, Role

    if not user_input.startswith("/"):
        return False

    parts = user_input[1:].split(None, 1)
    cmd = parts[0]
    args = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("m", "model"):
        if not args:
            console.print("[bold]Available Models:[/bold]")
            for alias, name in client.available_models.items():
                active = "*" if alias == client.current_alias else " "
                console.print(f" {active} [cyan]{alias:15}[/cyan] -> [dim]{name}[/dim]")
            return True

        model_alias = args
        if client.set_model(model_alias):
            console.print(
                f"[cyan]Model switched to: {client.current_alias} "
                f"({client.model})[/cyan]"
            )
        else:
            # Allow setting arbitrary models not in config
            client.set_custom_model(model_alias)
            console.print(
                f"[yellow]Custom model set: {client.model} (not in config)[/yellow]"
            )
        return True

    if cmd in ("t", "template"):
        templates = get_templates()
        if not args:
            if not templates:
                console.print(
                    "[yellow]No templates defined in [templates] section "
                    "of config.toml[/yellow]"
                )
            else:
                console.print("[bold]Available Templates:[/bold]")
                for name, text in templates.items():
                    # Show a preview of the template text
                    preview = (text[:60] + "...") if len(text) > 60 else text
                    console.print(f" [cyan]{name:15}[/cyan] -> [dim]{preview}[/dim]")
            return True

        template_name = args
        if template_name in templates:
            template_text = templates[template_name]
            if pending_data is not None:
                # Instead of sending immediately,
                # request to load it into the input buffer
                raise TemplateRequest(template_text)
            else:
                # If called from somewhere else without pending_data
                console.print(f"[cyan]Selected template '{template_name}':[/cyan]")
                console.print(Panel(template_text))
                return True
        else:
            console.print(f"[red]Template not found: {template_name}[/red]")
            return True

    if cmd in ("checkpoint", "cp"):
        raise CheckpointRequest()

    if cmd == "reload":
        from llm_cli.clients.config import reload_config
        from llm_cli.security.policy import policy_engine

        reload_config()
        client.api_key = get_setting(client._api_key_name, client.config_section)
        client._refresh_general_settings()
        client._refresh_system_prompt()
        policy_engine.reinitialize()
        console.print("[green]Configuration reloaded from disk.[/green]")
        return True

    if cmd == "save":
        path_str = args
        if not path_str:
            now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"session_{now_str}"
            try:
                user_input = prompt(
                    "Enter session filename: ",
                    default=default_filename,
                    completer=PathCompleter(expanduser=True),
                    complete_style=CompleteStyle.READLINE_LIKE,
                ).strip()
                if not user_input:
                    user_input = default_filename

                if not user_input.lower().endswith(".json"):
                    path_str = f"{user_input}.json"
                else:
                    path_str = user_input
            except (KeyboardInterrupt, EOFError):
                console.print("[yellow]Save cancelled.[/yellow]")
                return True

        try:
            save_path = Path(path_str)
            if save_path.exists():
                if not Confirm.ask(
                    f"[yellow]File {save_path} already exists. Overwrite?[/yellow]",
                    default=False,
                ):
                    console.print("[yellow]Save cancelled.[/yellow]")
                    return True

            # Ensure parent directory exists
            save_path.parent.mkdir(parents=True, exist_ok=True)

            with save_path.open("w", encoding="utf-8") as f:
                json.dump(
                    [asdict(m) for m in client.conversation],
                    f,
                    indent=2,
                    ensure_ascii=False,
                )
            console.print(f"[green]Session saved to {save_path}[/green]")
        except Exception as e:
            console.print(f"[red]Failed to save session: {e}[/red]")
        return True

    if cmd == "load":
        path_str = args
        if not path_str:
            console.print("[red]Usage: /load <path>[/red]")
            return True

        client.load_session(path_str)
        return True

    if cmd == "attach":
        path_str = args
        if not path_str:
            console.print("[red]Usage: /attach <path>[/red]")
            return True

        res = client._process_single_source(path_str)
        if res and res.is_file_or_url:
            if res.content_type == "text/plain":
                console.print(
                    f"[yellow]Notice: {path_str} is text. "
                    "Added as text context.[/yellow]"
                )
            else:
                console.print(f"[green]Attached {res.content_type}: {path_str}[/green]")
            if pending_data is not None:
                pending_data.append(res)
        else:
            console.print(
                f"[red]Failed to attach: {path_str} (File not found or "
                "invalid source)[/red]"
            )
        return True

    if cmd == "dump":
        json_str = json.dumps(
            [asdict(m) for m in client.conversation], indent=2, ensure_ascii=False
        )
        syn = Syntax(
            json_str,
            "json",
            theme="monokai",
            background_color="default",
            word_wrap=True,
        )
        console.print(Panel(syn, title="Conversation History", border_style="blue"))

        if pending_data:
            json_pending = json.dumps(
                [asdict(d) for d in pending_data], indent=2, ensure_ascii=False
            )
            syn_pending = Syntax(
                json_pending,
                "json",
                theme="monokai",
                background_color="default",
                word_wrap=True,
            )
            console.print(
                Panel(
                    syn_pending,
                    title="Pending Context (Next Request)",
                    border_style="yellow",
                )
            )
        return True

    if cmd == "raw":
        for msg in client.conversation:
            role = msg.role
            for p in msg.parts:
                role_suffix = ""
                text = ""
                if isinstance(p, str):
                    text = p
                elif isinstance(p, ContentPart):
                    if p.thought:
                        role_suffix = " (REASONING)"
                        text = p.thought
                    elif p.text:
                        text = p.text

                if text:
                    display_role = (
                        client.model
                        if role in (Role.MODEL, Role.ASSISTANT)
                        else role.upper()
                    )
                    print(f"[{display_role}{role_suffix}]\n{text}\n")
        return True

    if cmd in ("c", "clear"):
        client.clear_history()
        console.print("[yellow]Conversation history cleared.[/yellow]")
        return True

    if cmd in ("q", "quit"):
        raise ExitRequest

    if cmd == "tools":
        from llm_cli.modules.tool_registry import registry

        if args == "on":
            client.tools_enabled = True
            console.print("[green]Tools enabled.[/green]")
        elif args == "off":
            client.tools_enabled = False
            console.print("[yellow]Tools disabled.[/yellow]")
        elif not args:
            status = (
                "[green]ENABLED[/green]"
                if client.tools_enabled
                else "[red]DISABLED[/red]"
            )
            active_for_provider = registry.get_active_names(
                client.active_tools, provider=client.config_section
            )
            if active_for_provider:
                tools_list = "\n".join([f"  - {t}" for t in active_for_provider])
                tools_str = f"\n{tools_list}"
            else:
                tools_str = " None"

            console.print(f"[bold]Tools Status:[/bold] {status}")
            if client.tools_enabled:
                console.print(f"[bold]Active Tools:[/bold]{tools_str}")
            console.print("[dim]Usage: /tools on|off[/dim]")
        else:
            console.print(
                f"[red]Error: Invalid argument '{args}'. Usage: /tools on|off[/red]"
            )
        return True

    if cmd in ("debug", "d"):
        client.live_debug = not client.live_debug
        status = "ENABLED" if client.live_debug else "DISABLED"
        console.print(f"[magenta]Live debug mode {status}.[/magenta]")
        return True

    if cmd in ("info", "i"):
        from rich.table import Table

        from llm_cli.modules.tool_registry import registry
        from llm_cli.security.policy import policy_engine

        info_table = Table(show_header=False, box=None)
        info_table.add_row(
            "Provider",
            f"[bold green]{client.config_section}[/bold green]",
        )
        info_table.add_row("Model Alias", f"[cyan]{client.current_alias}[/cyan]")
        info_table.add_row("Full Model", f"[dim]{client.model}[/dim]")

        tool_status = (
            "[green]ENABLED[/green]" if client.tools_enabled else "[red]DISABLED[/red]"
        )
        info_table.add_row("Tools Status", tool_status)

        debug_status = "[green]ON[/green]" if client.live_debug else "[red]OFF[/red]"
        info_table.add_row("Live Debug", debug_status)

        if client.tools_enabled:
            active_for_provider = registry.get_active_names(
                client.active_tools, provider=client.config_section
            )
            if active_for_provider:
                tools_list = ", ".join(active_for_provider)
                info_table.add_row("Active Tools", f"[dim]{tools_list}[/dim]")

        ia_enabled = policy_engine.config.get("intent_analyzer_enabled", False)
        if ia_enabled:
            ia_provider = policy_engine.config.get("intent_analyzer_provider", "?")
            ia_model = policy_engine.config.get("intent_analyzer_model", "?")
            info_table.add_row(
                "Intent Analyzer",
                f"[bold green]ON[/bold green] ({ia_provider}/{ia_model})",
            )
        else:
            info_table.add_row("Intent Analyzer", "[dim]OFF[/dim]")

        info_table.add_row("History Length", f"{len(client.conversation)} messages")

        session = getattr(client, "_session", None)
        if session and hasattr(session, "sentinel"):
            sentinel = session.sentinel
            from llm_cli.security.integrity import current_integrity_score

            if current_integrity_score is not None:
                color = (
                    "green"
                    if current_integrity_score < 3.5
                    else "yellow"
                    if current_integrity_score < 5.0
                    else "red"
                )
                info_table.add_row(
                    "Reasoning Integrity",
                    f"[{color}]{current_integrity_score:.4f}[/{color}] (Anomaly Score)",
                )

                # Trust Trend Visualization
                if sentinel.score_history:
                    trend_chars = []
                    for s in sentinel.score_history:
                        if s < 3.5:
                            trend_chars.append("[green]█[/green]")
                        elif s < 5.0:
                            trend_chars.append("[yellow]█[/yellow]")
                        else:
                            trend_chars.append("[red]█[/red]")
                    info_table.add_row("Trust Trend", "".join(trend_chars))

                # Sentinel Latency
                if sentinel.processing_count > 0:
                    avg_time = (
                        sentinel.total_processing_time / sentinel.processing_count
                    )
                    info_table.add_row(
                        "Sentinel Latency",
                        f"[dim]{sentinel.last_processing_time * 1000:.2f}ms[/dim] "
                        f"(avg: [dim]{avg_time * 1000:.2f}ms[/dim])",
                    )
            else:
                info_table.add_row(
                    "Reasoning Integrity", "[dim]N/A (No reasoning analyzed)[/dim]"
                )

        if client.last_usage:
            usage_str = ", ".join(f"{k}: {v}" for k, v in client.last_usage.items())
            info_table.add_row("Last Usage", f"[yellow]{usage_str}[/yellow]")

        console.print(
            Panel(
                info_table,
                title="[bold]Session Info[/bold]",
                border_style="cyan",
            )
        )
        return True

    if cmd in ("help", "h"):
        print_help()
        return True

    return False


def print_help() -> None:
    from llm_cli.clients.base import console

    console.print(
        "[bold]Available Commands:[/bold]\n"
        "  /attach <path> Attach media/file to context\n"
        "  /save <path>   Save conversation history to a JSON file\n"
        "  /load <path>   Load conversation history from a JSON file\n"
        "  /clear (c)     Clear conversation history\n"
        "  /checkpoint(cp)Summarize and clear history\n"
        "  /reload        Reload config.toml from disk\n"
        "  /dump          Dump conversation history as JSON\n"
        "  /raw           Show conversation as raw text\n"
        "  /quit (q)      Exit the application\n"
        "  /info (i)      Show session info\n"
        "  /debug (d)     Toggle live debug mode\n"
        "  /model (m)     List available models or switch model\n"
        "                 (e.g. /m pro)\n"
        "  /provider (p)  List available providers or switch provider\n"
        "                 (e.g. /p openai)\n"
        "  /tools on|off  Show or toggle tool status\n"
        "\n"
        "[bold]Exit Application:[/bold]\n"
        "  Use [cyan]Ctrl+C[/cyan] or [cyan]Ctrl+D[/cyan] at any prompt to exit."
    )
