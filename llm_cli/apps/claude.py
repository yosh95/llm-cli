# llm_cli/apps/claude.py

import requests
from typing import Dict, List, Optional, Tuple
from llm_cli.clients.base import BaseLlmClient, DataSource, console
from llm_cli.modules.tool_registry import registry

FALLBACK_MODEL = "claude-haiku-4-5-20251001"


class ClaudeClient(BaseLlmClient):
    """A client for interacting with the Anthropic Claude API."""
    API_URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, initial_model_alias="default", **kwargs):
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="anthropic",
            pdf_as_base64=True,
            **kwargs
        )

    def _load_model_aliases(self):
        from llm_cli.clients.config import get_model_aliases
        self.available_models = get_model_aliases("anthropic")
        if 'default' not in self.available_models:
            self.available_models['default'] = FALLBACK_MODEL

    def _send(self, data: List[DataSource]) -> Tuple[
        Optional[str], Optional[Dict]
    ]:
        messages = self._build_messages(data)
        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages,
        }
        if self.system_prompt and self.system_prompt_enabled:
            payload["system"] = self.system_prompt

        if self.active_tools:
            payload["tools"] = registry.get_anthropic_spec(self.active_tools)

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        try:
            response = requests.post(
                self.API_URL, headers=headers, json=payload, timeout=120
            )
            response.raise_for_status()
            res = response.json()

            model_parts = []
            full_text = ""
            for block in res.get('content', []):
                if block['type'] == 'text':
                    full_text += block['text']
                    model_parts.append({"text": block['text']})
                elif block['type'] == 'tool_use':
                    model_parts.append({
                        "functionCall": {
                            "name": block['name'],
                            "args": block['input']
                        }
                    })

            model_msg = {"role": "model", "parts": model_parts}

            # Update history
            user_parts = []
            for d in data:
                if d["content_type"] == "text/plain":
                    user_parts.append({"text": d["content"]})
                else:
                    user_parts.append({
                        "inlineData": {
                            "mimeType": d["content_type"],
                            "data": d["content"]
                        }
                    })

            self.conversation.append({"role": "user", "parts": user_parts})
            self.conversation.append(model_msg)

            return full_text, res.get('usage')
        except Exception as e:
            console.print(f"[red]Claude Error: {e}[/red]")
            return None, None

    def _build_messages(self, data):
        msgs = []
        for m in self.conversation:
            role = "assistant" if m["role"] == "model" else m["role"]
            content = []
            for p in m["parts"]:
                if "text" in p:
                    content.append({"type": "text", "text": p["text"]})
            if content:
                msgs.append({"role": role, "content": content})

        user_content = []
        for d in data:
            if d["content_type"] == "text/plain":
                user_content.append({"type": "text", "text": d["content"]})
            elif d["content_type"].startswith("image/"):
                user_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": d["content_type"],
                        "data": d["content"]
                    }
                })
        msgs.append({"role": "user", "content": user_content})
        return msgs
