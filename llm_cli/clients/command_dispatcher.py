# llm_cli/clients/command_dispatcher.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from llm_cli.ui import console

if TYPE_CHECKING:
    from llm_cli.clients.base import BaseLlmClient
    from llm_cli.modules.models import DataSource


@dataclass
class CommandContext:
    """Context passed to each command handler."""

    client: BaseLlmClient
    args: str
    pending_data: list[DataSource] | None
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


registry = CommandRegistry()


def setup_standard_commands(reg: CommandRegistry) -> None:
    from llm_cli.clients import command_impl as h

    reg.register(Command("attach", h.handle_attach, "Attach media/file to context"))
    reg.register(
        Command("save", h.handle_save, "Save conversation history to JSON file")
    )
    reg.register(
        Command("load", h.handle_load, "Load conversation history from JSON file")
    )
    reg.register(Command("clear", h.handle_clear, "Clear conversation history", ["c"]))
    reg.register(
        Command(
            "checkpoint", h.handle_checkpoint, "Summarize and clear history", ["cp"]
        )
    )
    reg.register(Command("reload", h.handle_reload, "Reload config.toml from disk"))
    reg.register(
        Command("provider", h.handle_provider, "List or switch provider", ["p"])
    )
    reg.register(Command("dump", h.handle_dump, "Dump conversation history as JSON"))
    reg.register(Command("raw", h.handle_raw, "Show conversation as raw text"))
    reg.register(Command("quit", h.handle_quit, "Exit the application", ["q"]))
    reg.register(Command("info", h.handle_info, "Show session info", ["i"]))
    reg.register(Command("debug", h.handle_debug, "Toggle live debug mode", ["d"]))
    reg.register(Command("model", h.handle_model, "List or switch models", ["m"]))
    reg.register(
        Command("template", h.handle_template, "Use a message template", ["t"])
    )
    reg.register(Command("tools", h.handle_tools, "Show or toggle tool status"))
    reg.register(
        Command("benchmark-dual", h.handle_benchmark_dual, "Benchmark Dual LLM latency")
    )
    reg.register(Command("help", h.handle_help, "Show this help message", ["h"]))


setup_standard_commands(registry)
SUPPORTED_COMMANDS = registry.all_names_and_aliases


def handle_command(
    client: BaseLlmClient,
    user_input: str,
    sources: Any,
    pending_data: list[DataSource] | None = None,
) -> bool:
    """Handles in-chat slash commands using the command registry."""
    if not user_input.startswith("/"):
        return False

    parts = user_input[1:].split(None, 1)
    cmd_name = parts[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""

    reg = getattr(client, "command_registry", registry)
    command = reg.get_command(cmd_name)
    if command:
        ctx = CommandContext(client, args, pending_data, sources)
        return command.handler(ctx)
    return False


def print_help(client: BaseLlmClient | None = None) -> None:
    """Prints a help message listing all registered commands."""
    reg = getattr(client, "command_registry", registry) if client else registry
    console.print("\n[bold]Chat Commands:[/bold]")
    for name in sorted(reg.commands.keys()):
        cmd = reg.commands[name]
        aliases = f" ({', '.join(cmd.aliases)})" if cmd.aliases else ""
        console.print(f" [cyan]/{name:12}[/cyan]{aliases:8} {cmd.help_text}")
    console.print()
