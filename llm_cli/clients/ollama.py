# llm_cli/clients/ollama.py

import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from llm_cli.clients.base import BaseLlmClient
from llm_cli.clients.config import get_setting
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

DEFAULT_API_URL = "http://localhost:11434/v1/chat/completions"


class OllamaClient(BaseLlmClient):
    """
    Client for interacting with the Ollama API.

    Supports OpenAI-compatible chat completion endpoint.
    Specially handles <think> tags for models like DeepSeek-R1.
    """

    def __init__(self, initial_model_alias: str = "default", **kwargs):
        """Initializes the Ollama client."""
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="ollama",
            pdf_as_base64=False,
            **kwargs,
        )
        config_url = get_setting("api_url", "ollama")
        self.api_url = config_url if config_url else DEFAULT_API_URL

    def _load_model_aliases(self):
        """Loads model aliases from the configuration."""
        from llm_cli.clients.config import get_model_aliases

        self.available_models = get_model_aliases("ollama")

    def _send(
        self, data: List[DataSource]
    ) -> Tuple[Tuple[Optional[str], Optional[str]], Optional[Dict]]:
        """Sends the conversation history and new data to Ollama."""
        messages = self._build_messages(data)

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }

        if self.tools_enabled and self.active_tools:
            payload["tools"] = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )

        try:
            response = self._post_with_retry(
                self.api_url,
                headers={},
                json_data=payload,
                timeout=self.request_timeout,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()
            res_json = response.json()

            raw_content, tool_calls, reasoning = self._parse_response(res_json)
            # Ensure raw_content is a string even if None
            raw_content = raw_content or ""

            # Handle <think> tags in content (common in DeepSeek-R1 via Ollama)
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
                user_parts: List[Union[str, ContentPart]] = [
                    ContentPart(text=user_text)
                ]
                self.conversation.append(Message(role=Role.USER, parts=user_parts))

            model_msg = Message(role=Role.MODEL, parts=model_parts)
            self.conversation.append(model_msg)

            return (raw_content.strip(), (reasoning or "").strip()), res_json.get(
                "usage", {}
            )
        except Exception as e:
            self._report_error("Ollama", e)
            return (None, None), None

    def _build_messages(self, data: List[DataSource]) -> List[Dict[str, Any]]:
        """Converts history and new data to Ollama API format."""
        msgs = []
        if self.system_prompt and self.system_prompt_enabled:
            msgs.append({"role": "system", "content": self.system_prompt})

        # Track tool_call_ids that have responses to maintain consistency
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
                            content_text += f"<think>\n{p.thought}\n</think>\n"

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
                    msg_obj = {"role": role, "content": content_text}
                    if tool_calls:
                        msg_obj["tool_calls"] = tool_calls
                    msgs.append(msg_obj)

        # Append incoming data
        user_content = "".join(str(d.content) for d in data)
        if user_content:
            msgs.append({"role": "user", "content": user_content})

        return msgs

    def _parse_response(self, res_json: Dict) -> Tuple[str, List, Optional[str]]:
        """Parses Ollama API response."""
        reasoning = None
        if "choices" in res_json:
            choice = res_json["choices"][0].get("message", {})
            content = choice.get("content", "")
            tool_calls = choice.get("tool_calls", [])
            reasoning = choice.get("reasoning_content")
        else:
            message = res_json.get("message", {})
            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])
        return content, tool_calls, reasoning

    def _build_model_parts(
        self, content: str, tool_calls: List, reasoning: Optional[str] = None
    ) -> List[Union[str, ContentPart]]:
        """Builds internal ContentPart list."""
        model_parts: List[Union[str, ContentPart]] = []
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
