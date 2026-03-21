# llm_cli/clients/ollama.py

import json
from typing import Any

from llm_cli.clients.base import BaseLlmClient, ProviderSpec
from llm_cli.clients.config import config_manager
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

DEFAULT_API_URL = "http://localhost:11434/v1/chat/completions"


class OllamaClient(BaseLlmClient):
    """
    Client for interacting with Ollama via its OpenAI-compatible API.
    """

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        """Initializes the Ollama client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            spec=ProviderSpec(
                api_key_name="api_key",
                config_section="ollama",
                pdf_as_base64=False,  # Per user instruction: don't make pdf to base64
            ),
            **kwargs,
        )
        config_url = config_manager.get("ollama", "api_url")
        self.api_url = config_url if config_url else DEFAULT_API_URL

    def _load_model_aliases(self) -> None:
        """Loads model aliases from the configuration."""
        from llm_cli.clients.config import config_manager

        self.available_models = config_manager.get_model_aliases("ollama")

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        """Sends the conversation history and new data to Ollama."""
        messages = self._build_messages(data)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }

        if self.active_tools and self.tools_enabled:
            # Note: Not all Ollama models support tool calling.
            payload["tools"] = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = self._post(
                self.api_url,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res = response.json()

            choice = res["choices"][0]["message"]
            content = choice.get("content", "")
            thought_text = choice.get("reasoning_content", "")
            model_parts: list[str | ContentPart] = []

            if thought_text:
                model_parts.append(ContentPart(thought=thought_text))

            if content:
                model_parts.append(ContentPart(text=content))

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

            return (content.strip(), thought_text.strip()), res.get("usage")
        except Exception as e:
            self._report_error("Ollama", e)
            return (None, None), None

    def _build_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        """Converts internal history to Ollama (OpenAI-compatible) format."""
        msgs: list[dict[str, Any]] = []
        if self.system_prompt and self.system_prompt_enabled:
            msgs.append({"role": "system", "content": self.system_prompt})

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
