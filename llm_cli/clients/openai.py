# llm_cli/clients/openai.py

import json
from typing import Any, Dict, List, Optional, Tuple

from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.config import get_setting
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIClient(BaseLlmClient):
    """
    Client for interacting with OpenAI's Chat Completions API.

    Supports vision, tool calling, and reasoning (thinking) modes.
    """

    def __init__(self, initial_model_alias: str = "default", **kwargs):
        """Initializes the OpenAI client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="openai",
            pdf_as_base64=False,
            **kwargs,
        )
        # Load custom API URL if provided, otherwise use default
        config_url = get_setting("api_url", "openai")
        self.api_url = config_url if config_url else DEFAULT_API_URL

    def _load_model_aliases(self):
        """Loads model aliases from the configuration."""
        from llm_cli.clients.config import get_model_aliases

        self.available_models = get_model_aliases("openai")

    def _send(self, data: List[DataSource]) -> Tuple[Optional[str], Optional[Dict]]:
        """
        Sends the conversation history and new data to OpenAI.

        Args:
            data: New DataSource inputs from the user.

        Returns:
            A tuple of (response_text, usage_dict).
        """
        messages = self._build_messages(data)
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if self.active_tools and self.tools_enabled:
            payload["tools"] = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )

        # Enable reasoning effort for o1-style models if requested
        if self.reasoning_enabled:
            payload["reasoning_effort"] = "medium"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._post_with_retry(
                self.api_url,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res = response.json()

            choice = res["choices"][0]["message"]
            model_parts: List[ContentPart] = []
            full_text = ""

            # Extract reasoning/thought if present (OpenAI o1 models)
            reasoning = choice.get("reasoning_content")
            if reasoning:
                model_parts.append(ContentPart(thought=reasoning))
                if self.reasoning_enabled:
                    full_text += f"\n> **Reasoning:** {reasoning}\n\n"

            if choice.get("content"):
                text_content = choice["content"]
                full_text += text_content
                model_parts.append(ContentPart(text=text_content))

            if choice.get("tool_calls"):
                for tc in choice["tool_calls"]:
                    model_parts.append(
                        ContentPart(
                            function_call={
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                "args": json.loads(tc["function"]["arguments"]),
                            }
                        )
                    )

            model_msg = Message(role=Role.MODEL, parts=model_parts)

            self._update_history(data, model_msg)
            return full_text.strip(), res.get("usage")
        except Exception as e:
            self._report_error("OpenAI", e)
            return None, None

    def _update_history(self, data: List[DataSource], model_msg: Message):
        """Updates the internal conversation history with new messages."""
        user_parts: List[ContentPart] = []
        for d in data:
            if d.content_type == "text/plain":
                user_parts.append(ContentPart(text=str(d.content)))
            else:
                user_parts.append(
                    ContentPart(
                        inline_data={
                            "mimeType": d.content_type,
                            "data": d.content,
                        }
                    )
                )

        if user_parts:
            self.conversation.append(Message(role=Role.USER, parts=user_parts))
        self.conversation.append(model_msg)

    def _build_messages(self, data: List[DataSource]) -> List[Dict[str, Any]]:
        """Converts the internal conversation history to OpenAI API format."""
        msgs = []
        if self.system_prompt and self.system_prompt_enabled:
            msgs.append({"role": "system", "content": self.system_prompt})

        # Track tool_call_ids that have responses
        responded_tool_ids = set()
        for m in self.conversation:
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        tool_id = p.function_response.get("id")
                        if tool_id and tool_id != "unknown":
                            responded_tool_ids.add(tool_id)

        for m in self.conversation:
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        func_resp = p.function_response
                        tool_id = func_resp.get("id")
                        if (
                            tool_id
                            and tool_id != "unknown"
                            and tool_id in responded_tool_ids
                        ):
                            result = func_resp.get("response", {}).get("result", "")
                            msgs.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "content": str(result),
                                }
                            )
            else:
                role = "assistant" if m.role == Role.MODEL else m.role.value
                content_text = ""
                tool_calls = []

                for p in m.parts:
                    if isinstance(p, str):
                        content_text += p
                    elif isinstance(p, ContentPart):
                        if p.text:
                            content_text += p.text
                        if p.function_call:
                            func_call = p.function_call
                            tool_id = func_call.get("id")
                            if (
                                tool_id
                                and tool_id != "unknown"
                                and tool_id in responded_tool_ids
                            ):
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

                if content_text or tool_calls:
                    msg = {"role": role, "content": content_text or None}
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    msgs.append(msg)

        # Append incoming data for the next user message
        user_content = []
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
