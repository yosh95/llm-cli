# llm_cli/clients/ollama.py

import json
from typing import Dict, Iterable, List, Optional, Tuple, Union

from llm_cli.clients.base import BaseLlmClient, DataSource
from llm_cli.clients.config import get_setting
from llm_cli.modules.tool_registry import registry

FALLBACK_MODEL = "gemma3:270m"
DEFAULT_API_URL = "http://localhost:11434/v1/chat/completions"


class OllamaClient(BaseLlmClient):
    """A client for interacting with the Ollama API."""

    def __init__(self, initial_model_alias="default", **kwargs):
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
        from llm_cli.clients.config import get_model_aliases

        self.available_models = get_model_aliases("ollama")
        if "default" not in self.available_models:
            self.available_models["default"] = FALLBACK_MODEL

    def _send(
        self, data: List[DataSource], stream: bool = False
    ) -> Union[Tuple[Optional[str], Optional[Dict]], Iterable[str]]:
        messages = []
        if self.system_prompt and self.system_prompt_enabled:
            messages.append({"role": "system", "content": self.system_prompt})

        for msg in self.conversation:
            role = "assistant" if msg["role"] == "model" else msg["role"]
            content = ""
            for p in msg.get("parts", []):
                if "text" in p:
                    content += p["text"]
            messages.append({"role": role, "content": content})

        user_content = ""
        for item in data:
            user_content += item["content"]

        if user_content:
            messages.append({"role": "user", "content": user_content})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
        }

        if self.tools_enabled and self.active_tools:
            payload["tools"] = registry.get_openai_spec(
                self.active_tools, provider=self.config_section
            )

        if not stream:
            try:
                response = self._post_with_retry(
                    self.api_url, headers={}, json_data=payload, timeout=60
                )
                self._log_debug(response_obj=response)
                response.raise_for_status()
                res_json = response.json()

                content, tool_calls = self._parse_response(res_json)
                model_parts = self._build_model_parts(content, tool_calls)

                self._update_history(user_content, model_parts)
                return content, res_json.get("usage", {})
            except Exception as e:
                self._report_error("Ollama", e)
                return None, None
        else:
            return self._send_stream(payload, user_content)

    def _send_stream(self, payload: Dict, user_content: str) -> Iterable[str]:
        try:
            response = self._post_with_retry(
                self.api_url, headers={}, json_data=payload, timeout=60, stream=True
            )
            self._log_debug(response_obj=response, request_payload=payload)
            response.raise_for_status()

            full_text = ""
            model_parts = []
            event_count = 0

            # Ollama /v1/chat/completions uses SSE if stream=True
            for line in response.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8")

                # Handle both SSE (data: ...) and raw JSON lines (Ollama native)
                try:
                    if line_str.startswith("data: "):
                        data_content = line_str[6:].strip()
                        if data_content == "[DONE]" or not data_content:
                            break
                        chunk = json.loads(data_content)
                    else:
                        chunk = json.loads(line_str)

                    event_count += 1

                    # Log first few events in debug mode
                    if self.live_debug and event_count <= 3:
                        self._log_debug(response_content=chunk)
                except json.JSONDecodeError as e:
                    if self.live_debug:
                        yield f"\n[JSON Parse Error: {e}]\n"
                    continue

                # Parse chunk
                if "choices" in chunk:
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                else:
                    message = chunk.get("message", {})
                    content = message.get("content", "")

                if content:
                    full_text += content
                    yield content
                    if not model_parts or "text" not in model_parts[-1]:
                        model_parts.append({"text": content})
                    else:
                        model_parts[-1]["text"] += content

                if "usage" in chunk:
                    self.last_usage = chunk["usage"]

            self._update_history(user_content, model_parts)
        except Exception as e:
            self._report_error("Ollama Stream", e)
            yield f"\n[Error: {e}]"

    def _parse_response(self, res_json):
        if "choices" in res_json:
            choice = res_json["choices"][0].get("message", {})
            content = choice.get("content", "")
            tool_calls = choice.get("tool_calls", [])
        else:
            message = res_json.get("message", {})
            content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])
        return content, tool_calls

    def _build_model_parts(self, content, tool_calls):
        model_parts = []
        if content:
            model_parts.append({"text": content})

        if tool_calls:
            for tc in tool_calls:
                fn = tc.get("function", {})
                model_parts.append(
                    {
                        "functionCall": {
                            "id": tc.get("id"),
                            "name": fn.get("name"),
                            "args": (
                                json.loads(fn["arguments"])
                                if isinstance(fn.get("arguments"), str)
                                else fn.get("arguments")
                            ),
                        }
                    }
                )
        return model_parts

    def _update_history(self, user_content, model_parts):
        if user_content:
            self.conversation.append(
                {"role": "user", "parts": [{"text": user_content}]}
            )
        if model_parts:
            self.conversation.append({"role": "model", "parts": model_parts})
