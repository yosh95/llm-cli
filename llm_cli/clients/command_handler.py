# llm_cli/clients/command_handler.py

import datetime
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

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


@dataclass
class CommandContext:
    """Context passed to each command handler."""

    client: "BaseLlmClient"
    args: str
    pending_data: list["DataSource"] | None
    sources: Any


HandlerFunc = Callable[[CommandContext], bool]


class Command:
    """Defines a single slash command."""

    def __init__(
        self,
        name: str,
        handler: HandlerFunc,
        help_text: str,
        aliases: list[str] | None = None,
    ):
        self.name = name
        self.handler = handler
        self.help_text = help_text
        self.aliases = aliases or []


class CommandRegistry:
    """Manages registration and lookup of slash commands."""

    def __init__(self) -> None:
        self.commands: dict[str, Command] = {}
        self.alias_map: dict[str, str] = {}

    def register(self, command: Command) -> None:
        self.commands[command.name] = command
        for alias in command.aliases:
            self.alias_map[alias] = command.name

    def get_command(self, name_or_alias: str) -> Command | None:
        name = self.alias_map.get(name_or_alias, name_or_alias)
        return self.commands.get(name)

    @property
    def all_names_and_aliases(self) -> set[str]:
        return set(self.commands.keys()) | set(self.alias_map.keys())


# --- Command Handlers ---


def handle_model(ctx: CommandContext) -> bool:
    client, args = ctx.client, ctx.args
    from llm_cli.clients.base import console

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
    templates = get_templates()
    args = ctx.args
    from llm_cli.clients.base import console

    if not args:
        if not templates:
            console.print(
                "[yellow]No templates defined in [templates] section of "
                "config.toml[/yellow]"
            )
        else:
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
    from llm_cli.clients.base import console
    from llm_cli.clients.config import reload_config
    from llm_cli.security.policy import policy_engine

    reload_config()
    ctx.client.api_key = get_setting(
        ctx.client._api_key_name, ctx.client.config_section
    )
    ctx.client._refresh_general_settings()
    ctx.client._refresh_system_prompt()
    policy_engine.reinitialize()
    console.print("[green]Configuration reloaded from disk.[/green]")
    return True


def handle_save(ctx: CommandContext) -> bool:
    from llm_cli.clients.base import console

    client, args = ctx.client, ctx.args
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
            path_str = user_input if user_input else default_filename
            if not path_str.lower().endswith(".json"):
                path_str += ".json"
        except (KeyboardInterrupt, EOFError):
            console.print("[yellow]Save cancelled.[/yellow]")
            return True

    try:
        save_path = Path(path_str)
        if save_path.exists() and not Confirm.ask(
            f"[yellow]File {save_path} already exists. Overwrite?[/yellow]",
            default=False,
        ):
            console.print("[yellow]Save cancelled.[/yellow]")
            return True

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


def handle_load(ctx: CommandContext) -> bool:
    if not ctx.args:
        from llm_cli.clients.base import console

        console.print("[red]Usage: /load <path>[/red]")
        return True
    ctx.client.load_session(ctx.args)
    return True


def handle_attach(ctx: CommandContext) -> bool:
    from llm_cli.clients.base import console

    if not ctx.args:
        console.print("[red]Usage: /attach <path>[/red]")
        return True

    res = ctx.client._process_single_source(ctx.args)
    if res and res.is_file_or_url:
        if res.content_type == "text/plain":
            console.print(
                f"[yellow]Notice: {ctx.args} is text. Added as text context.[/yellow]"
            )
        else:
            console.print(f"[green]Attached {res.content_type}: {ctx.args}[/green]")
        if ctx.pending_data is not None:
            ctx.pending_data.append(res)
    else:
        msg = (
            f"[red]Failed to attach: {ctx.args} "
            "(File not found or invalid source)[/red]"
        )
        console.print(msg)
    return True


def handle_dump(ctx: CommandContext) -> bool:
    from llm_cli.clients.base import console

    client = ctx.client
    json_str = json.dumps(
        [asdict(m) for m in client.conversation], indent=2, ensure_ascii=False
    )
    syn = Syntax(
        json_str, "json", theme="monokai", background_color="default", word_wrap=True
    )
    console.print(Panel(syn, title="Conversation History", border_style="blue"))

    if ctx.pending_data:
        json_pending = json.dumps(
            [asdict(d) for d in ctx.pending_data], indent=2, ensure_ascii=False
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


def handle_raw(ctx: CommandContext) -> bool:
    from llm_cli.modules.models import ContentPart, Role

    client = ctx.client
    for msg in client.conversation:
        role = msg.role
        for p in msg.parts:
            role_suffix, text = "", ""
            if isinstance(p, str):
                text = p
            elif isinstance(p, ContentPart):
                if p.thought:
                    role_suffix, text = " (REASONING)", p.thought
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


def handle_clear(ctx: CommandContext) -> bool:
    ctx.client.clear_history()
    from llm_cli.clients.base import console

    console.print("[yellow]Conversation history cleared.[/yellow]")
    return True


def handle_quit(_ctx: CommandContext) -> bool:
    raise ExitRequest()


def handle_tools(ctx: CommandContext) -> bool:
    from llm_cli.clients.base import console
    from llm_cli.modules.tool_registry import registry as tool_registry

    client, args = ctx.client, ctx.args
    if args == "on":
        client.tools_enabled = True
        console.print("[green]Tools enabled.[/green]")
    elif args == "off":
        client.tools_enabled = False
        console.print("[yellow]Tools disabled.[/yellow]")
    elif not args:
        status = (
            "[green]ENABLED[/green]" if client.tools_enabled else "[red]DISABLED[/red]"
        )
        active_for_provider = tool_registry.get_active_names(
            client.active_tools, provider=client.config_section
        )
        tools_str = (
            "\n" + "\n".join([f"  - {t}" for t in active_for_provider])
            if active_for_provider
            else " None"
        )
        console.print(f"[bold]Tools Status:[/bold] {status}")
        if client.tools_enabled:
            console.print(f"[bold]Active Tools:[/bold]{tools_str}")
        console.print("[dim]Usage: /tools on|off[/dim]")
    else:
        console.print(
            f"[red]Error: Invalid argument '{args}'. Usage: /tools on|off[/red]"
        )
    return True


def handle_debug(ctx: CommandContext) -> bool:
    ctx.client.live_debug = not ctx.client.live_debug
    status = "ENABLED" if ctx.client.live_debug else "DISABLED"
    from llm_cli.clients.base import console

    console.print(f"[magenta]Live debug mode {status}.[/magenta]")
    return True


def handle_info(ctx: CommandContext) -> bool:
    from rich.table import Table

    from llm_cli.clients.base import console
    from llm_cli.modules.tool_registry import registry as tool_registry
    from llm_cli.security.policy import policy_engine

    client = ctx.client

    info_table = Table(show_header=False, box=None)
    info_table.add_row("Provider", f"[bold green]{client.config_section}[/bold green]")
    info_table.add_row("Model Alias", f"[cyan]{client.current_alias}[/cyan]")
    info_table.add_row("Full Model", f"[dim]{client.model}[/dim]")
    info_table.add_row(
        "Tools Status",
        "[green]ENABLED[/green]" if client.tools_enabled else "[red]DISABLED[/red]",
    )
    info_table.add_row(
        "Live Debug", "[green]ON[/green]" if client.live_debug else "[red]OFF[/red]"
    )

    if client.tools_enabled:
        active = tool_registry.get_active_names(
            client.active_tools, provider=client.config_section
        )
        if active:
            info_table.add_row("Active Tools", f"[dim]{', '.join(active)}[/dim]")

    ia_enabled = policy_engine.config.get("intent_analyzer_enabled", False)
    if ia_enabled:
        ia_provider = policy_engine.config.get("intent_analyzer_provider", "?")
        ia_model = policy_engine.config.get("intent_analyzer_model", "?")
        info_table.add_row(
            "Intent Analyzer", f"[bold green]ON[/bold green] ({ia_provider}/{ia_model})"
        )
    else:
        info_table.add_row("Intent Analyzer", "[dim]OFF[/dim]")

    info_table.add_row("History Length", f"{len(client.conversation)} messages")

    # Sentinel Info (Reasoning Integrity)
    session = getattr(client, "_session", None)
    if session and hasattr(session, "sentinel"):
        sentinel = session.sentinel
        current_score = sentinel.current_score
        if current_score is not None:
            t_yellow, t_red = sentinel.sentinel.get_dynamic_thresholds()
            color = (
                "green"
                if current_score < t_yellow
                else "yellow"
                if current_score < t_red
                else "red"
            )
            info_table.add_row(
                "Reasoning Integrity",
                f"[{color}]{current_score:.4f}[/{color}] (Anomaly Score)",
            )
            if sentinel.score_history:
                trend = [
                    " [green]█[/green]"
                    if s < t_yellow
                    else "[yellow]█[/yellow]"
                    if s < t_red
                    else "[red]█[/red]"
                    for s in sentinel.score_history
                ]
                info_table.add_row("Trust Trend", "".join(trend))

    if client.last_usage:
        usage_str = ", ".join(f"{k}: {v}" for k, v in client.last_usage.items())
        info_table.add_row("Last Usage", f"[yellow]{usage_str}[/yellow]")

    console.print(
        Panel(info_table, title="[bold]Session Info[/bold]", border_style="cyan")
    )
    return True


def handle_help(ctx: CommandContext) -> bool:
    print_help(ctx.client)
    return True


# --- Registry Initialization ---

registry = CommandRegistry()


def setup_standard_commands(reg: CommandRegistry) -> None:
    reg.register(Command("attach", handle_attach, "Attach media/file to context"))
    reg.register(Command("save", handle_save, "Save conversation history to JSON file"))
    reg.register(
        Command("load", handle_load, "Load conversation history from JSON file")
    )
    reg.register(Command("clear", handle_clear, "Clear conversation history", ["c"]))
    reg.register(
        Command("checkpoint", handle_checkpoint, "Summarize and clear history", ["cp"])
    )
    reg.register(Command("reload", handle_reload, "Reload config.toml from disk"))
    reg.register(Command("dump", handle_dump, "Dump conversation history as JSON"))
    reg.register(Command("raw", handle_raw, "Show conversation as raw text"))
    reg.register(Command("quit", handle_quit, "Exit the application", ["q"]))
    reg.register(Command("info", handle_info, "Show session info", ["i"]))
    reg.register(Command("debug", handle_debug, "Toggle live debug mode", ["d"]))
    reg.register(Command("model", handle_model, "List or switch models", ["m"]))
    reg.register(Command("template", handle_template, "Use a message template", ["t"]))
    reg.register(Command("tools", handle_tools, "Show or toggle tool status"))
    reg.register(Command("help", handle_help, "Show this help message", ["h"]))


setup_standard_commands(registry)

SUPPORTED_COMMANDS = registry.all_names_and_aliases


def handle_command(
    client: "BaseLlmClient",
    user_input: str,
    sources: Any,
    pending_data: list["DataSource"] | None = None,
) -> bool:
    """Handles in-chat slash commands using the command registry."""
    if not user_input.startswith("/"):
        return False

    parts = user_input[1:].split(None, 1)
    cmd_name = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    # Use instance-specific registry if available, otherwise global
    reg = getattr(client, "command_registry", registry)
    command = reg.get_command(cmd_name)

    if command:
        ctx = CommandContext(client, args, pending_data, sources)
        return command.handler(ctx)

    return False


def print_help(client: Optional["BaseLlmClient"] = None) -> None:
    from llm_cli.clients.base import console

    reg = getattr(client, "command_registry", registry) if client else registry

    help_text = "[bold]Available Commands:[/bold]\n"
    for name in sorted(reg.commands.keys()):
        cmd = reg.commands[name]
        alias_str = f"({', '.join(cmd.aliases)})" if cmd.aliases else ""
        help_text += f"  /{cmd.name:12} {alias_str:6} {cmd.help_text}\n"

    help_text += "\n[bold]Exit Application:[/bold]\n"
    help_text += (
        "  Use [cyan]Ctrl+C[/cyan] or [cyan]Ctrl+D[/cyan] at any prompt to exit."
    )
    console.print(help_text)


def setup_registry() -> None:
    """Dummy function to satisfy potential callers."""
    pass
