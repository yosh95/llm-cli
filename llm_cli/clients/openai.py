# llm_cli/clients/openai.py

import json
from typing import Dict, Iterable, List, Optional, Tuple, Union

from llm_cli.clients.base import BaseLlmClient, DataSource
from llm_cli.clients.config import get_setting
from llm_cli.modules.tool_registry import registry

FALLBACK_MODEL = "gpt-5-nano"
DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIClient(BaseLlmClient):
    def __init__(self, initial_model_alias="default", **kwargs):
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
        from llm_cli.clients.config import get_model_aliases

        self.available_models = get_model_aliases("openai")
        if "default" not in self.available_models:
            self.available_models["default"] = FALLBACK_MODEL

    def _send(
        self, data: List[DataSource], stream: bool = False
    ) -> Union[Tuple[Optional[str], Optional[Dict]], Iterable[str]]:
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

        if not stream:
            try:
                response = self._post_with_retry(
                    self.api_url, headers=headers, json_data=payload, timeout=60
                )
                self._log_debug(response_obj=response)
                response.raise_for_status()
                res = response.json()

                choice = res["choices"][0]["message"]
                model_parts = []
                if choice.get("content"):
                    model_parts.append({"text": choice["content"]})

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
                return choice.get("content", ""), res.get("usage")
            except Exception as e:
                self._report_error("OpenAI", e)
                return None, None
        else:
            payload["stream"] = True
            return self._send_stream(headers, payload, data)

    def _send_stream(
        self, headers: Dict, payload: Dict, data: List[DataSource]
    ) -> Iterable[str]:
        try:
            response = self._post_with_retry(
                self.api_url,
                headers=headers,
                json_data=payload,
                timeout=60,
                stream=True,
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()

            full_text = ""
            model_parts = []
            tool_calls_buffer = {}
            event_count = 0

            for line in response.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    data_content = line_str[6:].strip()
                    if data_content == "[DONE]" or not data_content:
                        break

                    try:
                        chunk = json.loads(data_content)
                        event_count += 1

                        # Log first few events in debug mode
                        if self.live_debug and event_count <= 3:
                            self._log_debug(response_content=chunk)
                    except json.JSONDecodeError as e:
                        if self.live_debug:
                            yield f"\n[JSON Parse Error: {e}]\n"
                        continue

                    delta = chunk["choices"][0].get("delta", {})

                    if "content" in delta and delta["content"]:
                        content = delta["content"]
                        full_text += content
                        yield content
                        if not model_parts or "text" not in model_parts[-1]:
                            model_parts.append({"text": content})
                        else:
                            model_parts[-1]["text"] += content

                    if "tool_calls" in delta:
                        for tc_delta in delta["tool_calls"]:
                            idx = tc_delta["index"]
                            if idx not in tool_calls_buffer:
                                tool_calls_buffer[idx] = {
                                    "id": tc_delta.get("id"),
                                    "name": "",
                                    "arguments": "",
                                }

                            if "id" in tc_delta:
                                tool_calls_buffer[idx]["id"] = tc_delta["id"]
                            if "function" in tc_delta:
                                fn_delta = tc_delta["function"]
                                if "name" in fn_delta:
                                    tool_calls_buffer[idx]["name"] += fn_delta["name"]
                                if "arguments" in fn_delta:
                                    tool_calls_buffer[idx]["arguments"] += fn_delta[
                                        "arguments"
                                    ]

                    if "usage" in chunk:
                        self.last_usage = chunk["usage"]

            # Process tool calls from buffer
            for idx in sorted(tool_calls_buffer.keys()):
                tc = tool_calls_buffer[idx]
                model_parts.append(
                    {
                        "functionCall": {
                            "id": tc["id"],
                            "name": tc["name"],
                            "args": json.loads(tc["arguments"])
                            if tc["arguments"]
                            else {},
                        }
                    }
                )

            model_msg = {"role": "model", "parts": model_parts}
            self._update_history(data, model_msg)

        except Exception as e:
            self._report_error("OpenAI Stream", e)
            yield f"\n[Error: {e}]"

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
