# llm_cli/clients/mixins.py

import json
from collections.abc import Generator
from typing import TYPE_CHECKING, Any, Protocol

from llm_cli.modules.models import ContentPart, DataSource, Message, Role

if TYPE_CHECKING:
    from llm_cli.modules.models import Message


class BaseClientInterface(Protocol):
    """Protocol for BaseLlmClient features used by Mixins."""

    @property
    def system_prompt(self) -> str: ...
    @property
    def system_prompt_enabled(self) -> bool: ...
    def _iter_history(self) -> Generator[tuple[Message, set[str]]]: ...
    def _is_valid_tool_id(self, tool_id: str | None, responded: set[str]) -> bool: ...


class OpenAICompatibleMixin:
    """Provides common logic for OpenAI-compatible (Chat Completions) APIs."""

    def _build_openai_compatible_messages(
        self: BaseClientInterface, data: list[DataSource], include_thought: bool = False
    ) -> list[dict[str, Any]]:
        """
        Converts internal history to standard OpenAI-compatible messages format.
        Used by Grok, Ollama, and potentially others.
        """
        msgs: list[dict[str, Any]] = []

        # Accessing properties from the base client
        if (
            hasattr(self, "system_prompt")
            and self.system_prompt
            and self.system_prompt_enabled
        ):
            msgs.append({"role": "system", "content": self.system_prompt})

        # iterate through history (using self._iter_history which should
        # be available on BaseLlmClient)
        for m, responded_tool_ids in self._iter_history():
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        func_resp = p.function_response
                        tool_id = func_resp.get("id")
                        if self._is_valid_tool_id(tool_id, responded_tool_ids):
                            result = func_resp.get("response", {}).get("result", "")
                            msgs.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": str(tool_id),
                                    "content": str(result),
                                }
                            )
            else:
                role = "assistant" if m.role == Role.MODEL else m.role.value
                content_parts: list[dict[str, Any]] = []
                tool_calls = []

                for p in m.parts:
                    if isinstance(p, str):
                        content_parts.append({"type": "text", "text": p})
                    elif isinstance(p, ContentPart):
                        if p.text:
                            content_parts.append({"type": "text", "text": p.text})

                        if include_thought and p.thought:
                            content_parts.append(
                                {
                                    "type": "text",
                                    "text": f"<thought>\n{p.thought}\n</thought>",
                                }
                            )

                        if p.inline_data and role == "user":
                            mime = p.inline_data.get("mimeType", "")
                            if mime.startswith("image/"):
                                content_parts.append(
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:{mime};base64,"
                                            f"{p.inline_data.get('data', '')}"
                                        },
                                    }
                                )

                        if p.function_call:
                            func_call = p.function_call
                            tool_id = func_call.get("id")
                            if self._is_valid_tool_id(tool_id, responded_tool_ids):
                                tool_calls.append(
                                    {
                                        "id": tool_id,
                                        "type": "function",
                                        "function": {
                                            "name": func_call.get("name", "unknown"),
                                            "arguments": json.dumps(
                                                func_call.get("args", {})
                                            ),
                                        },
                                    }
                                )

                if content_parts or tool_calls:
                    msg: dict[str, Any] = {
                        "role": role,
                        "content": content_parts or None,
                    }
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    msgs.append(msg)

        user_content: list[dict[str, Any]] = []
        for d in data:
            if d.content_type == "text/plain":
                user_content.append({"type": "text", "text": str(d.content)})
            elif d.content_type.startswith("image/"):
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{d.content_type};base64,{d.content}"
                        },
                    }
                )

        if user_content:
            msgs.append({"role": "user", "content": user_content})

        return msgs
