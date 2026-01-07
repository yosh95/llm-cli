# llm_cli/clients/grok.py

import json
from typing import Dict, List, Optional, Tuple

from llm_cli.clients.base import BaseLlmClient, DataSource
from llm_cli.clients.config import get_setting
from llm_cli.modules.tool_registry import registry

FALLBACK_MODEL = "grok-4-1-fast-reasoning"
DEFAULT_API_URL = "https://api.x.ai/v1/chat/completions"


class GrokClient(BaseLlmClient):
    """A client for interacting with the xAI Grok API."""

    def __init__(self, initial_model_alias="default", **kwargs):
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="xai",
            pdf_as_base64=False,
            **kwargs,
        )
        config_url = get_setting("api_url", "xai")
        self.api_url = config_url if config_url else DEFAULT_API_URL

    def _load_model_aliases(self):
        from llm_cli.clients.config import get_model_aliases

        self.available_models = get_model_aliases("xai")
        if "default" not in self.available_models:
            self.available_models["default"] = FALLBACK_MODEL

    def _send(self, data: List[DataSource]) -> Tuple[Optional[str], Optional[Dict]]:
        messages = self._build_messages(data)
        payload = {
            "model": self.model,
            "messages": messages,
        }

        if self.active_tools:
            payload["tools"] = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._post_with_retry(
                self.api_url, headers=headers, json_data=payload, timeout=120
            )
            self._log_debug(response_obj=response)
            response.raise_for_status()
            res = response.json()

            choice = res["choices"][0]["message"]
            content = choice.get("content", "")

            model_parts = []
            if content:
                model_parts.append({"text": content})

            if choice.get("tool_calls"):
                for tc in choice["tool_calls"]:
                    model_parts.append(
                        {
                            "functionCall": {
                                "id": tc["id"],
                                "name": tc["function"]["name"],
                                "args": json.loads(tc["function"]["arguments"]),
                            }
                        }
                    )

            model_msg = {"role": "model", "parts": model_parts}
            self._update_history(data, model_msg)

            return content, res.get("usage")
        except Exception as e:
            self._report_error("Grok", e)
            return None, None

    def _update_history(self, data: List[DataSource], model_msg: Dict):
        user_parts = []
        for d in data:
            if d["content_type"] == "text/plain":
                user_parts.append({"text": d["content"]})
            else:
                user_parts.append(
                    {
                        "inlineData": {
                            "mimeType": d["content_type"],
                            "data": d["content"],
                        }
                    }
                )

        if user_parts:
            self.conversation.append({"role": "user", "parts": user_parts})
        self.conversation.append(model_msg)

    def _build_messages(self, data):
        msgs = []
        if self.system_prompt and self.system_prompt_enabled:
            msgs.append({"role": "system", "content": self.system_prompt})

        # Track tool_call_ids that have responses
        responded_tool_ids = set()
        for m in self.conversation:
            if m["role"] == "function":
                for p in m["parts"]:
                    if "functionResponse" in p:
                        func_resp = p["functionResponse"]
                        tool_id = func_resp.get("id")
                        if tool_id and tool_id != "unknown":
                            responded_tool_ids.add(tool_id)

        for m in self.conversation:
            if m["role"] == "function":
                # Only include function responses that correspond to
                # responded tool calls
                for p in m["parts"]:
                    if "functionResponse" in p:
                        func_resp = p["functionResponse"]
                        tool_id = func_resp.get("id")
                        # Only add tool response if it's in the responded set
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
                role = "assistant" if m["role"] == "model" else m["role"]
                content = ""
                tool_calls = []

                for p in m["parts"]:
                    if "text" in p:
                        content += p["text"]
                    elif "functionCall" in p:
                        func_call = p["functionCall"]
                        tool_id = func_call.get("id")
                        # Only include tool calls that have responses
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

                if content or tool_calls:
                    msg = {"role": role, "content": content}
                    if tool_calls:
                        msg["tool_calls"] = tool_calls
                    msgs.append(msg)

        user_content = []
        for d in data:
            if d["content_type"] == "text/plain":
                user_content.append({"type": "text", "text": d["content"]})
            elif d["content_type"].startswith("image/"):
                user_content.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": (f"data:{d['content_type']};base64,{d['content']}")
                        },
                    }
                )

        if user_content:
            msgs.append({"role": "user", "content": user_content})

        return msgs
