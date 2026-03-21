# llm_cli/clients/mixins.py

import json
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
    @property
    def pdf_as_base64(self) -> bool: ...
    @property
    def conversation(self) -> list[Message]: ...
    def _update_history(self, data: list[DataSource], model_msg: Message) -> None: ...


class OpenAICompatibleMixin:
    """Provides common message-building logic for OpenAI Chat Completions APIs.

    Used by OpenAIClient, GrokClient, OllamaClient.
    """

    def _build_openai_compatible_messages(
        self: BaseClientInterface, data: list[DataSource]
    ) -> list[dict[str, Any]]:
        """Convert internal history to the OpenAI Chat Completions messages format.

        PDF handling:
          - ``pdf_as_base64 is True``  → ``{"type": "file", "file": {...}}`` block
          - ``pdf_as_base64 is False`` → PDF is silently skipped
        """
        msgs: list[dict[str, Any]] = []

        if self.system_prompt and self.system_prompt_enabled:
            msgs.append({"role": "system", "content": self.system_prompt})

        # Pre-calculate tool IDs with responses
        responded_tool_ids = set()
        for msg in self.conversation:
            if msg.role == Role.TOOL:
                for part in msg.parts:
                    if isinstance(part, ContentPart) and part.function_response:
                        tid = part.function_response.get("id")
                        if tid:
                            responded_tool_ids.add(tid)

        for m in self.conversation:
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        func_resp = p.function_response
                        tool_id = func_resp.get("id")
                        if tool_id and tool_id in responded_tool_ids:
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

                        if p.inline_data and role == "user":
                            mime = p.inline_data.get("mimeType", "")
                            if mime.startswith("image/"):
                                content_parts.append(
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": (
                                                f"data:{mime};base64,"
                                                f"{p.inline_data.get('data', '')}"
                                            )
                                        },
                                    }
                                )
                            elif mime == "application/pdf" and self.pdf_as_base64:
                                fname = p.inline_data.get("filename", "attachment.pdf")
                                b64 = p.inline_data.get("data", "")
                                content_parts.append(
                                    {
                                        "type": "file",
                                        "file": {
                                            "filename": fname,
                                            "file_data": f"data:{mime};base64,{b64}",
                                        },
                                    }
                                )

                        if p.function_call:
                            func_call = p.function_call
                            tool_id = func_call.get("id")
                            if tool_id and tool_id in responded_tool_ids:
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
                    new_msg: dict[str, Any] = {
                        "role": role,
                        "content": content_parts or None,
                    }
                    if tool_calls:
                        new_msg["tool_calls"] = tool_calls
                    msgs.append(new_msg)

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
            elif d.content_type == "application/pdf" and self.pdf_as_base64:
                filename = d.metadata.get("filename", "attachment.pdf")
                user_content.append(
                    {
                        "type": "file",
                        "file": {
                            "filename": filename,
                            "file_data": (f"data:{d.content_type};base64,{d.content}"),
                        },
                    }
                )

        if user_content:
            msgs.append({"role": "user", "content": user_content})

        return msgs


class ClaudeMessagesMixin:
    """Provides message-building logic for the Anthropic Claude Messages API.

    Claude uses its own wire format that differs from OpenAI in several ways:

    * System prompt → top-level ``system`` field (not a message), with optional
      ``cache_control`` for prompt caching.
    * Tool invocations → ``tool_use`` content blocks (not ``tool_calls``).
    * Tool results → ``tool_result`` content blocks inside a ``user`` message
      (not a separate ``tool`` role message).
    * Extended thinking → ``thinking`` content blocks with a ``signature``.
    * Images → ``{"type": "image", "source": {"type": "base64", ...}}``
    * PDFs → ``{"type": "document", "source": {"type": "base64", ...}}``

    Because of these structural differences ClaudeClient does **not** use
    ``OpenAICompatibleMixin``.  This mixin centralises all history-serialisation
    logic so ``ClaudeClient._send`` stays focused on HTTP concerns only.
    """

    def _build_claude_messages(
        self: BaseClientInterface, data: list[DataSource]
    ) -> list[dict[str, Any]]:
        """Convert internal history + new *data* into the Claude Messages format.

        Returns a list of ``{"role": "user"|"assistant", "content": [...]}``
        dicts suitable for the ``messages`` field of a ``/v1/messages`` request.
        The system prompt is handled separately in ``_send`` and is therefore
        **not** included in the returned list.
        """
        msgs: list[dict[str, Any]] = []

        # Pre-calculate tool IDs that have responses to ensure tool-calling validity
        responded_tool_ids = set()
        for msg in self.conversation:
            if msg.role == Role.TOOL:
                for part in msg.parts:
                    if isinstance(part, ContentPart) and part.function_response:
                        tid = part.function_response.get("id")
                        if tid:
                            responded_tool_ids.add(tid)

        for m in self.conversation:
            if m.role == Role.TOOL:
                # Tool results travel inside a synthetic ``user`` message as
                # ``tool_result`` blocks – one block per tool response.
                tool_content: list[dict[str, Any]] = []
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        func_resp = p.function_response
                        tool_id = func_resp.get("id")
                        if tool_id and tool_id in responded_tool_ids:
                            result = func_resp.get("response", {}).get("result", "")
                            tool_content.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": tool_id,
                                    "content": str(result),
                                }
                            )
                if tool_content:
                    msgs.append({"role": "user", "content": tool_content})

            else:
                role = "assistant" if m.role == Role.MODEL else "user"
                msg_parts: list[dict[str, Any]] = []

                for p in m.parts:
                    if isinstance(p, str):
                        msg_parts.append({"type": "text", "text": p})
                    elif isinstance(p, ContentPart):
                        # Extended thinking block (assistant only)
                        if p.thought:
                            thinking_block: dict[str, Any] = {
                                "type": "thinking",
                                "thinking": p.thought,
                            }
                            if p.thought_signature:
                                thinking_block["signature"] = p.thought_signature
                            msg_parts.append(thinking_block)

                        # Plain text
                        if p.text and p.text.strip():
                            msg_parts.append({"type": "text", "text": p.text})

                        # Inline media (images / PDFs stored in history)
                        if p.inline_data and role == "user":
                            mime = p.inline_data.get("mimeType", "")
                            b64 = p.inline_data.get("data", "")
                            if mime.startswith("image/"):
                                msg_parts.append(
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": mime,
                                            "data": b64,
                                        },
                                    }
                                )
                            elif mime == "application/pdf":
                                msg_parts.append(
                                    {
                                        "type": "document",
                                        "source": {
                                            "type": "base64",
                                            "media_type": mime,
                                            "data": b64,
                                        },
                                    }
                                )

                        # Tool invocation (assistant only)
                        if p.function_call:
                            func_call = p.function_call
                            tool_id = func_call.get("id")
                            if tool_id and tool_id in responded_tool_ids:
                                msg_parts.append(
                                    {
                                        "type": "tool_use",
                                        "id": tool_id,
                                        "name": func_call.get("name", "unknown"),
                                        "input": func_call.get("args", {}),
                                    }
                                )

                if msg_parts:
                    msgs.append({"role": role, "content": msg_parts})

        # ------------------------------------------------------------------ #
        # Append the new user turn from *data*                                #
        # ------------------------------------------------------------------ #
        user_content: list[dict[str, Any]] = []
        for d in data:
            if d.content_type == "text/plain":
                user_content.append({"type": "text", "text": str(d.content)})
            elif d.content_type.startswith("image/"):
                user_content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": d.content_type,
                            "data": d.content,
                        },
                    }
                )
            elif d.content_type == "application/pdf":
                # Claude accepts PDFs as ``document`` blocks with base64 source.
                # No ``pdf_as_base64`` guard needed: the Claude client always
                # receives pre-encoded data from MediaManager.
                user_content.append(
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": d.content_type,
                            "data": d.content,
                        },
                    }
                )

        if user_content:
            msgs.append({"role": "user", "content": user_content})

        return msgs
