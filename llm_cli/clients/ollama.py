# llm_cli/apps/ollama.py

import json
from typing import Dict, List, Optional, Tuple

import requests

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

    def _send(self, data: List[DataSource]) -> Tuple[Optional[str], Optional[Dict]]:
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
            "stream": False,
        }

        if self.tools_enabled and self.active_tools:
            payload["tools"] = registry.get_openai_spec(self.active_tools)

        try:
            response = requests.post(self.api_url, json=payload, timeout=120)
            self._log_debug(response_obj=response)
            response.raise_for_status()
            res_json = response.json()

            # Handle both OpenAI-compatible and native Ollama formats
            if "choices" in res_json:
                choice = res_json["choices"][0].get("message", {})
                content = choice.get("content", "")
                tool_calls = choice.get("tool_calls", [])
            else:
                message = res_json.get("message", {})
                content = message.get("content", "")
                tool_calls = message.get("tool_calls", [])

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

            if user_content:
                self.conversation.append(
                    {"role": "user", "parts": [{"text": user_content}]}
                )

            model_msg = {"role": "model", "parts": model_parts}
            self.conversation.append(model_msg)

            return content, res_json.get("usage", {})
        except Exception as e:
            self._report_error("Ollama", e)
            return None, None
