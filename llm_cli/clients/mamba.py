import json
from pathlib import Path
from typing import Any

import tiktoken
import torch

from llm_cli.clients.base import BaseLlmClient, console
from llm_cli.clients.config import get_setting
from llm_cli.mamba_core.model import MambaLM
from llm_cli.modules.models import ContentPart, DataSource, Message, Role


class MambaClient(BaseLlmClient):
    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",
            config_section="mamba",
            pdf_as_base64=False,
            **kwargs,
        )
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = tiktoken.get_encoding("o200k_base")
        self.model_instance: MambaLM | None = None
        self._initialize_model()

    def _initialize_model(self) -> None:
        # Configuration for the base model - must match training
        vocab_size = self.tokenizer.n_vocab
        d_model = get_setting("d_model", "mamba") or 128
        n_layers = get_setting("n_layers", "mamba") or 4

        self.model_instance = MambaLM(
            vocab_size=vocab_size, d_model=d_model, n_layers=n_layers
        )

        # Load weights if path exists
        from llm_cli.consts import MAMBA_MODEL_PATH

        model_path_setting = get_setting("model_path", "mamba")
        model_path = (
            Path(model_path_setting) if model_path_setting else MAMBA_MODEL_PATH
        )

        if model_path.exists():
            self.model_instance.load_state_dict(
                torch.load(model_path, map_location=self.device)
            )
            console.print(
                f"[green]Loaded Mamba model from {model_path} on {self.device}[/green]"
            )
        else:
            msg = (
                "[yellow]Warning: Mamba model weights not found. "
                f"Using random initialization on {self.device}.[/yellow]"
            )
            console.print(msg)

        self.model_instance.to(self.device)
        self.model_instance.eval()

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        # 1. Update history with user data
        for item in data:
            self.conversation.append(
                Message(role=Role.USER, parts=[ContentPart(text=str(item.content))])
            )

        # 2. Build prompt
        full_prompt = ""
        for msg in self.conversation:
            role = msg.role.value
            content = msg.get_text()
            full_prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
        full_prompt += "<|im_start|>model\n"

        # 3. Generate
        input_ids = torch.tensor(
            [self.tokenizer.encode(full_prompt)], device=self.device
        )
        generated_ids: list[int] = []

        # Simple greedy generation
        max_new_tokens = 512
        states = None

        if self.model_instance is None:
            raise RuntimeError("Mamba model not initialized")

        # Initial pass
        logits, states = self.model_instance.step(input_ids, states)
        next_token = torch.argmax(logits[:, -1, :], dim=-1)
        generated_ids.append(int(next_token.item()))

        im_end_token = (
            self.tokenizer.encode("<|im_end|>", allowed_special={"<|im_end|>"})[0]
            if "<|im_end|>" in self.tokenizer._special_tokens
            else -1
        )

        for _ in range(max_new_tokens - 1):
            logits, states = self.model_instance.step(next_token.unsqueeze(0), states)
            next_token = torch.argmax(logits[:, -1, :], dim=-1)

            if next_token.item() == im_end_token:
                break
            generated_ids.append(int(next_token.item()))

        response_text = self.tokenizer.decode(generated_ids)

        # 4. Parse response for thought and tool calls
        thought = None
        if "<thought>" in response_text:
            parts = response_text.split("</thought>")
            thought = parts[0].replace("<thought>", "").strip()
            response_text = parts[1].strip() if len(parts) > 1 else ""

        model_parts: list[str | ContentPart] = [
            ContentPart(text=response_text, thought=thought)
        ]

        # Extract tool calls using regex
        import re

        calls = re.findall(r"<tool_call>(.*?)</tool_call>", response_text)
        if calls:
            for call_str in calls:
                try:
                    call_data = json.loads(call_str)
                    model_parts.append(ContentPart(function_call=call_data))
                except json.JSONDecodeError:
                    continue
            # Remove XML-like tags from display text
            response_text = re.sub(
                r"<tool_call>.*?</tool_call>", "", response_text
            ).strip()
            # We know model_parts[0] is a ContentPart
            first_part = model_parts[0]
            if isinstance(first_part, ContentPart):
                first_part.text = response_text

        model_msg = Message(role=Role.MODEL, parts=model_parts)
        self.conversation.append(model_msg)

        return (response_text, thought), {
            "total_tokens": len(input_ids[0]) + len(generated_ids)
        }

    def _load_model_aliases(self) -> None:
        self.available_models = {"mamba-local": "mamba_model.pt"}
