# llm_cli/clients/claude.py

from typing import Any

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.clients.mixins import ClaudeMessagesMixin
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry


class ClaudeClient(BaseLlmClient, ClaudeMessagesMixin):
    """Client for the Anthropic Claude Messages API.

    Supports vision, tool calling, and extended thinking modes.

    Extended thinking allows Claude to reason through complex problems before
    responding.  Claude 4 models return summarised thinking content; Claude
    Sonnet 4.6 returns the full thinking output.

    Message serialisation (history → wire format) is handled by
    :class:`~llm_cli.clients.mixins.ClaudeMessagesMixin` so this class stays
    focused on HTTP concerns and response parsing.
    """

    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        super().__init__(
            initial_model_alias=initial_model_alias,
            spec=ProviderSpec(
                api_key_name="api_key",
                config_section="anthropic",
                # PDFs are sent as base64-encoded ``document`` blocks; the
                # MediaManager must decode/encode the file before sending.
                pdf_as_base64=True,
            ),
            **kwargs,
        )

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Send conversation history + *data* to the Claude Messages API."""
        from llm_cli.clients.config import config_manager

        messages = self._build_claude_messages(data)
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
                payload["tools"] = registry.get_anthropic_spec(
                    self.active_tools, provider=self.config_section
                )

            # Always enable Prompt Caching
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
