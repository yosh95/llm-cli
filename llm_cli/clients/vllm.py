# llm_cli/clients/vllm.py

import json
import re
from typing import Any

from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.config import get_setting
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

DEFAULT_API_URL = "http://localhost:8000/v1/chat/completions"


class VLLMClient(BaseLlmClient):
    """
    Client for interacting with vLLM (OpenAI Compatible) API.

    Supports OpenAI-compatible chat completion endpoint.
    """

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        """Initializes the vLLM client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="vllm",
            pdf_as_base64=False,
            **kwargs,
        )
        config_url = get_setting("api_url", "vllm")
        self.api_url = config_url if config_url else DEFAULT_API_URL

        # vLLM often requires a dummy API key if not set
        if not self.api_key:
            self.api_key = "EMPTY"

    def _load_model_aliases(self) -> None:
        """Loads model aliases from the configuration."""
        from llm_cli.clients.config import get_model_aliases

        self.available_models = get_model_aliases("vllm")

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict | None]:
        """Sends the conversation history and new data to vLLM."""
        messages = self._build_messages(data)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        # vLLM tool support depends on the model and server version
        if self.tools_enabled and self.active_tools:
            payload["tools"] = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._post(
                self.api_url,
                headers=headers,
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res_json = response.json()

            raw_content, tool_calls, reasoning = self._parse_response(res_json)
            # Ensure raw_content is a string
            raw_content = raw_content or ""

            # Handle <think> tags if present (e.g. DeepSeek models on vLLM)
            if not reasoning and raw_content and "<think>" in raw_content:
                think_match = re.search(r"<think>(.*?)</think>", raw_content, re.DOTALL)
                if think_match:
                    reasoning = think_match.group(1).strip()
                    raw_content = re.sub(
                        r"<think>.*?</think>", "", raw_content, flags=re.DOTALL
                    ).strip()

            model_parts = self._build_model_parts(raw_content, tool_calls, reasoning)

            # Update history
            user_text = "".join(str(d.content) for d in data)
            if user_text:
                user_parts: list[str | ContentPart] = [ContentPart(text=user_text)]
                self.conversation.append(Message(role=Role.USER, parts=user_parts))

            model_msg = Message(role=Role.MODEL, parts=model_parts)
            self.conversation.append(model_msg)

            return (raw_content.strip(), (reasoning or "").strip()), res_json.get(
                "usage", {}
            )
        except Exception as e:
            self._report_error("vLLM", e)
            return (None, None), None

    def _build_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        """Converts history and new data to OpenAI/vLLM API format."""
        msgs: list[dict[str, Any]] = []
        if self.system_prompt and self.system_prompt_enabled:
            msgs.append({"role": "system", "content": self.system_prompt})

        responded_tool_ids = set()
        for m in self.conversation:
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        tool_id = p.function_response.get("id")
                        if tool_id:
                            responded_tool_ids.add(tool_id)

        for m in self.conversation:
            if m.role == Role.TOOL:
                for p in m.parts:
                    if isinstance(p, ContentPart) and p.function_response:
                        tool_id = p.function_response.get("id")
                        if tool_id and tool_id in responded_tool_ids:
                            result = p.function_response.get("response", {}).get(
                                "result", ""
                            )
                            if not isinstance(result, str):
                                result = json.dumps(result, ensure_ascii=False)
                            msgs.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_id,
                                    "content": result,
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
                        if p.thought:
                            # Optionally include thought in history if needed
                            pass

                        if p.function_call:
                            tool_id = p.function_call.get("id")
                            if tool_id and tool_id in responded_tool_ids:
                                tool_calls.append(
                                    {
                                        "id": tool_id,
                                        "type": "function",
                                        "function": {
                                            "name": p.function_call.get("name"),
                                            "arguments": json.dumps(
                                                p.function_call.get("args")
                                            ),
                                        },
                                    }
                                )

                if content_text or tool_calls:
                    msg_obj: dict[str, Any] = {"role": role, "content": content_text}
                    if tool_calls:
                        msg_obj["tool_calls"] = tool_calls
                    msgs.append(msg_obj)

        user_content = "".join(str(d.content) for d in data)
        if user_content:
            msgs.append({"role": "user", "content": user_content})

        return msgs

    def _parse_response(self, res_json: dict) -> tuple[str, list, str | None]:
        """Parses vLLM API response."""
        reasoning = None
        if "choices" in res_json and len(res_json["choices"]) > 0:
            choice = res_json["choices"][0].get("message", {})
            content = choice.get("content", "")
            tool_calls = choice.get("tool_calls", [])
            reasoning = choice.get("reasoning_content")
        else:
            content = ""
            tool_calls = []
        return content, tool_calls, reasoning

    def _build_model_parts(
        self, content: str, tool_calls: list, reasoning: str | None = None
    ) -> list[str | ContentPart]:
        """Builds internal ContentPart list."""
        model_parts: list[str | ContentPart] = []
        if reasoning:
            model_parts.append(ContentPart(thought=reasoning))
        if content:
            model_parts.append(ContentPart(text=content))
        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                model_parts.append(
                    ContentPart(
                        function_call={
                            "id": tc.get("id"),
                            "name": fn.get("name"),
                            "args": (
                                json.loads(fn["arguments"])
                                if isinstance(fn.get("arguments"), str)
                                else fn.get("arguments")
                            ),
                        }
                    )
                )
        return model_parts
