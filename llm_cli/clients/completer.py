# llm_cli/clients/completer.py

from collections.abc import Iterable
from typing import TYPE_CHECKING

from prompt_toolkit.completion import (
    CompleteEvent,
    Completer,
    Completion,
    PathCompleter,
)
from prompt_toolkit.document import Document

from llm_cli.clients.config import config_manager

if TYPE_CHECKING:
    from llm_cli.clients.base import BaseLlmClient


class LlmCliCompleter(Completer):
    """Provides completion for slash commands and their arguments."""

    def __init__(self, client: "BaseLlmClient") -> None:
        self.client = client
        self.path_completer = PathCompleter(expanduser=True)

        # self.all_cmds will be generated dynamically
        self.path_cmds = ("/attach", "/save", "/load")
        self.provider_cmds = ("/p", "/provider")
        self.model_cmds = ("/m", "/model")
        self.template_cmds = ("/t", "/template")

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:
        text = document.text_before_cursor

        # Dynamic command list from client (re-fetched every time to
        # support provider switching)
        all_cmds = ["/" + cmd for cmd in self.client.slash_commands]

        # 1. Command completion (if no space yet)
        if " " not in text and text.startswith("/"):
            for cmd in all_cmds:
                if cmd.startswith(text):
                    yield Completion(cmd, start_position=-len(text))
            return

        # 2. Argument completion
        try:
            space_idx = text.index(" ")
        except ValueError:
            return

        cmd = text[:space_idx]
        # Calculate prefix for argument completion
        # We only complete the word being typed
        arg_text_full = text[space_idx + 1 :]
        arg_prefix = (
            arg_text_full.split()[-1]
            if arg_text_full and not arg_text_full.endswith(" ")
            else ""
        )
        if arg_text_full.endswith(" "):
            arg_prefix = ""

        # Determine start position for replacement
        # It should be negative length of current word
        start_pos = -len(arg_prefix)

        if cmd in self.provider_cmds:
            from llm_cli.clients import client_registry

            for alias in client_registry.list_aliases():
                if alias.startswith(arg_prefix):
                    yield Completion(alias, start_position=start_pos)

        elif cmd in self.model_cmds:
            for alias in self.client.available_models:
                if alias.startswith(arg_prefix):
                    yield Completion(alias, start_position=start_pos)

        elif cmd in self.template_cmds:
            templates = config_manager.get_templates()
            for name in templates:
                if name.startswith(arg_prefix):
                    yield Completion(name, start_position=start_pos)

        elif cmd in self.path_cmds:
            # Path completion needs the full part after command
            if text.startswith(cmd + " "):
                sub_text = text[len(cmd) + 1 :]
                new_doc = Document(sub_text, cursor_position=len(sub_text))
                yield from self.path_completer.get_completions(new_doc, complete_event)
