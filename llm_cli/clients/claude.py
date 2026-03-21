# llm_cli/clients/claude.py

from typing import Any

from llm_cli.clients.base import BaseLlmClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry


class ClaudeClient(BaseLlmClient):
    """
    Client for interacting with the Anthropic Claude API.

    Supports vision, tool calling, and extended thinking modes.

    Extended thinking allows Claude to reason through complex problems
    before responding. Claude 4 models return summarized thinking content,
    while Claude Sonnet 4.6 returns full thinking output.
    """

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        """Initializes the Claude client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="anthropic",
            pdf_as_base64=True,
            **kwargs,
        )

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Sends the conversation history and new data to Claude."""
        from llm_cli.clients.config import config_manager

        messages = self._build_messages(data)
        max_tokens = int(config_manager.get("anthropic", "max_tokens") or 8192)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-31",
            "content-type": "application/json",
        }

        try:
            if self.system_prompt and self.system_prompt_enabled:
                payload["system"] = [
                    {
                        "type": "text",
                        "text": self.system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]

            if self.active_tools and self.tools_enabled:
                tools = registry.get_anthropic_spec(
                    self.active_tools, provider=self.config_section
                )
                payload["tools"] = tools

            # Always enable Prompt Caching (fixed implementation as requested)
            payload["cache_control"] = {"type": "ephemeral"}

            response = self._post(
                self.API_URL,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res = response.json()

            model_parts: list[str | ContentPart] = []
            full_text = ""
            thought_text = ""
            for block in res.get("content", []):
                if block["type"] == "text":
                    text_content = block["text"]
                    full_text += text_content
                    model_parts.append(ContentPart(text=text_content))
                elif block["type"] == "thinking":
                    thought = block["thinking"]
                    thought_text += thought
                    signature = block.get("signature")
                    model_parts.append(
                        ContentPart(thought=thought, thought_signature=signature)
                    )
                elif block["type"] == "tool_use":
                    model_parts.append(
                        ContentPart(
                            function_call={
                                "id": block["id"],
                                "name": block["name"],
                                "args": block["input"],
                            }
                        )
                    )

            model_msg = Message(role=Role.MODEL, parts=model_parts)
            self._update_history(data, model_msg)

            return (full_text.strip(), thought_text.strip()), res.get("usage")
        except Exception as e:
            self._report_error("Claude", e)
            return (None, None), None

    def _build_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        """Converts internal conversation history to Claude API format."""
        msgs: list[dict[str, Any]] = []

        # Track tool_use_ids that have responses
        responded_tool_ids = self._get_responded_tool_ids()

        for m in self.conversation:
            if m.role == Role.TOOL:
                tool_content: list[dict[str, Any]] = []
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        func_resp = p.function_response
                        tool_id = func_resp.get("id")
                        if self._is_valid_tool_id(tool_id, responded_tool_ids):
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
                        if p.thought:
                            thinking_block = {"type": "thinking", "thinking": p.thought}
                            if p.thought_signature:
                                thinking_block["signature"] = p.thought_signature
                            msg_parts.append(thinking_block)
                        if p.text and p.text.strip():
                            msg_parts.append({"type": "text", "text": p.text})
                        if p.function_call:
                            func_call = p.function_call
                            tool_id = func_call.get("id")
                            if self._is_valid_tool_id(tool_id, responded_tool_ids):
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

        # Append incoming data for the next user message
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
