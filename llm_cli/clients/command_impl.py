# llm_cli/clients/command_impl.py
from __future__ import annotations

import datetime
import json
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from prompt_toolkit import prompt
from prompt_toolkit.completion import PathCompleter
from rich.panel import Panel
from rich.prompt import Confirm
from rich.syntax import Syntax

from llm_cli.clients.config import config_manager
from llm_cli.clients.exceptions import (
    CheckpointRequest,
    ExitRequest,
    TemplateRequest,
)
from llm_cli.ui import console

if TYPE_CHECKING:
    from llm_cli.clients.command_dispatcher import CommandContext


def handle_model(ctx: CommandContext) -> bool:
    client, args = ctx.client, ctx.args
    if not args:
        console.print("[bold]Available Models:[/bold]")
        for alias, name in client.available_models.items():
            active = "*" if alias == client.current_alias else " "
            console.print(f" {active} [cyan]{alias:15}[/cyan] -> [dim]{name}[/dim]")
        return True

    if client.set_model(args):
        console.print(
            f"[cyan]Model switched to: {client.current_alias} ({client.model})[/cyan]"
        )
    else:
        client.set_custom_model(args)
        console.print(
            f"[yellow]Custom model set: {client.model} (not in config)[/yellow]"
        )
    return True


def handle_template(ctx: CommandContext) -> bool:
    templates = config_manager.get_templates()
    args = ctx.args
    if not args:
        console.print("[bold]Available Templates:[/bold]")
        for name, text in templates.items():
            preview = (text[:60] + "...") if len(text) > 60 else text
            console.print(f" [cyan]{name:15}[/cyan] -> [dim]{preview}[/dim]")
        return True

    if args in templates:
        if ctx.pending_data is not None:
            raise TemplateRequest(templates[args])
        console.print(Panel(templates[args]))
    else:
        console.print(f"[red]Template not found: {args}[/red]")
    return True


def handle_checkpoint(_ctx: CommandContext) -> bool:
    raise CheckpointRequest()


def handle_reload(ctx: CommandContext) -> bool:
    config_manager.load_config(reload=True)
    ctx.client.api_key = config_manager.get(
        ctx.client.config_section, ctx.client._api_key_name
    )
    ctx.client.refresh_config()
    ctx.client._refresh_system_prompt()
    from llm_cli.security.policy import policy_engine

    policy_engine.reinitialize()
    console.print("[green]Configuration reloaded from disk.[/green]")
    return True


def handle_provider(ctx: CommandContext) -> bool:
    from rich.table import Table

    from llm_cli.clients.registry import client_registry

    client, args = ctx.client, ctx.args
    active_providers = config_manager.get_active_providers()

    if not args:
        table = Table(
            title="Active Providers", show_header=True, header_style="bold magenta"
        )
        table.add_column("Status", justify="center", width=4)
        table.add_column("Alias", style="cyan", width=15)
        table.add_column("Config Section", style="dim")
        info = client_registry.get_provider_info()
        for alias in sorted(info.keys()):
            section = info[alias]
            if section not in active_providers:
                continue
            active_mark = (
                "[bold green]*[/bold green]" if section == client.config_section else ""
            )
            table.add_row(active_mark, alias, section)
        console.print(table)
        return True

    config_section = client_registry.get_config_section(args)
    if not config_section or config_section not in active_providers:
        console.print(f"[red]Error: {args} is inactive or unknown.[/red]")
        return True

    client_class = client_registry.get_client_class(args)
    if client_class:
        # Use cast to Any here to avoid mypy issues with calling class constructor
        # because each subclass has a different constructor signature from the base.
        new_client = cast(Any, client_class)(
            initial_tools=client.active_tools, live_debug=client.live_debug
        )
        session = getattr(client, "_session", None)
        if session:
            session.switch_client(new_client)
            console.print(f"[cyan]Switched to provider: {args}[/cyan]")
    return True


def handle_save(ctx: CommandContext) -> bool:
    client, args = ctx.client, ctx.args
    path_str = args
    if not path_str:
        now_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            path_str = prompt(
                "Enter filename: ",
                default=f"session_{now_str}.json",
                completer=PathCompleter(),
            ).strip()
        except (KeyboardInterrupt, EOFError):
            return True

    if Path(path_str).exists() and not Confirm.ask("Overwrite?"):
        return True
    client.save_session(path_str)
    return True


def handle_load(ctx: CommandContext) -> bool:
    if not ctx.args:
        return True
    ctx.client.load_session(ctx.args)
    return True


def handle_attach(ctx: CommandContext) -> bool:
    if not ctx.args:
        return True
    res = ctx.client._process_single_source(ctx.args)
    if res and res.is_file_or_url:
        console.print(f"[green]Attached {res.content_type}: {ctx.args}[/green]")
        if ctx.pending_data is not None:
            ctx.pending_data.append(res)
    return True


def handle_dump(ctx: CommandContext) -> bool:
    json_str = json.dumps(
        [asdict(m) for m in ctx.client.conversation], indent=2, ensure_ascii=False
    )
    console.print(Panel(Syntax(json_str, "json"), title="Conversation History"))
    return True


def handle_raw(ctx: CommandContext) -> bool:
    from llm_cli.modules.models import ContentPart, Role

    for msg in ctx.client.conversation:
        for p in msg.parts:
            text = (
                p
                if isinstance(p, str)
                else (p.text or p.thought if isinstance(p, ContentPart) else "")
            )
            if text:
                role = (
                    ctx.client.model
                    if msg.role in (Role.MODEL, Role.ASSISTANT)
                    else msg.role.upper()
                )
                print(f"[{role}]\n{text}\n")
    return True


def handle_clear(ctx: CommandContext) -> bool:
    ctx.client.clear_history()
    console.print("[yellow]Conversation history cleared.[/yellow]")
    return True


def handle_quit(_ctx: CommandContext) -> bool:
    raise ExitRequest()


def handle_tools(ctx: CommandContext) -> bool:

    client, args = ctx.client, ctx.args
    if args in ("on", "off"):
        client.tools_enabled = args == "on"
        console.print(
            f"[green]Tools {'enabled' if client.tools_enabled else 'disabled'}.[/green]"
        )
    elif not args:
        status = (
            "[green]ENABLED[/green]" if client.tools_enabled else "[red]DISABLED[/red]"
        )
        console.print(f"Tools Status: {status}")
    return True


def handle_debug(ctx: CommandContext) -> bool:
    ctx.client.live_debug = not ctx.client.live_debug
    status = "ENABLED" if ctx.client.live_debug else "DISABLED"
    console.print(f"[magenta]Live debug mode {status}.[/magenta]")
    return True


def handle_info(ctx: CommandContext) -> bool:
    from rich.table import Table

    client = ctx.client
    table = Table(show_header=False, box=None)
    table.add_row("Provider", client.config_section)
    table.add_row("Model", client.model)
    table.add_row("History", f"{len(client.conversation)} messages")
    console.print(Panel(table, title="Session Info", border_style="cyan"))
    return True


def handle_help(ctx: CommandContext) -> bool:
    from llm_cli.clients.command_dispatcher import print_help

    print_help(ctx.client)
    return True
