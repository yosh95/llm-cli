# llm_cli/clients/huggingface.py

import json
import logging
import re
from typing import Any

import torch

from llm_cli.clients.base import BaseLlmClient, console
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry

logger = logging.getLogger(__name__)


class HuggingFaceClient(BaseLlmClient):
    """
    Client for interacting with local models via Hugging Face Transformers.
    Supports Function Calling via Chat Templates.
    """

    def __init__(self, initial_model_alias: str = "default", **kwargs: Any) -> None:
        self.model_instance: Any = None
        self.tokenizer: Any = None

        if torch.cuda.is_available():
            self.device = "cuda"
        elif torch.backends.mps.is_available():
            self.device = "mps"
        else:
            self.device = "cpu"

        super().__init__(
            initial_model_alias=initial_model_alias,
            api_key_name="api_key",  # Not strictly needed for local
            config_section="huggingface",
            pdf_as_base64=False,
            **kwargs,
        )

    def set_model(self, alias: str) -> bool:
        """Sets the model and re-initializes if necessary."""
        old_model = getattr(self, "model", None)
        if super().set_model(alias):
            # Only (re)initialize if model ID changed and we are ready
            # (after __init__ basics)
            if self.model != old_model and hasattr(self, "device"):
                self._initialize_local_model()
            return True
        return False

    def _initialize_local_model(self) -> None:
        """Loads the model and tokenizer from Hugging Face."""
        try:
            from transformers import (
                AutoModelForCausalLM,
                AutoTokenizer,
                BitsAndBytesConfig,
            )
        except ImportError:
            console.print("[red]Error: 'transformers' is not installed.[/red]")
            console.print(
                "[yellow]Please install it with: pip install '.[huggingface]'[/yellow]"
            )
            return

        model_id = self.model  # This will be the HF repo ID or local path
        if not model_id:
            return

        console.print(f"[dim]Loading Hugging Face model: {model_id}...[/dim]")

        load_in_4bit = self.model_config.get("load_in_4bit")
        if isinstance(load_in_4bit, str):
            load_in_4bit = load_in_4bit.lower() == "true"
        elif load_in_4bit is None:
            load_in_4bit = True

        trust_remote_code = self.model_config.get("trust_remote_code")
        if isinstance(trust_remote_code, str):
            trust_remote_code = trust_remote_code.lower() == "true"
        elif trust_remote_code is None:
            trust_remote_code = False

        try:
            self.tokenizer = AutoTokenizer.from_pretrained(
                model_id, trust_remote_code=trust_remote_code
            )

            quantization_config = None
            if load_in_4bit and self.device == "cuda":
                try:
                    import accelerate  # noqa: F401
                    import bitsandbytes  # noqa: F401

                    quantization_config = BitsAndBytesConfig(
                        load_in_4bit=True,
                        bnb_4bit_compute_dtype=torch.float16,
                        bnb_4bit_quant_type="nf4",
                    )
                except ImportError:
                    console.print(
                        "[yellow]Warning: 4-bit quantization requested but "
                        "'bitsandbytes' or 'accelerate' is not installed.[/yellow]"
                    )
                    console.print(
                        "[yellow]Falling back to standard loading. "
                        "To use 4-bit, run: pip install bitsandbytes "
                        "accelerate[/yellow]"
                    )
                    load_in_4bit = False

            # Clear old model if switching
            if self.model_instance is not None:
                del self.model_instance
                if self.device == "cuda":
                    torch.cuda.empty_cache()

            # Determine optimal dtype
            if self.device == "cuda" and torch.cuda.is_bf16_supported():
                use_dtype = torch.bfloat16
            elif self.device in ("cuda", "mps"):
                use_dtype = torch.float16
            else:
                use_dtype = torch.float32

            self.model_instance = AutoModelForCausalLM.from_pretrained(
                model_id,
                device_map="auto" if self.device in ("cuda", "mps") else None,
                quantization_config=quantization_config,
                torch_dtype=use_dtype,
                trust_remote_code=trust_remote_code,
            )
            if self.device == "cpu":
                self.model_instance.to(self.device)
            elif self.device == "mps" and not hasattr(
                self.model_instance, "hf_device_map"
            ):
                # fallback if device_map didn't put it on mps
                self.model_instance.to(self.device)

            console.print(f"[green]Model loaded successfully on {self.device}.[/green]")
        except Exception as e:
            console.print(f"[red]Failed to load Hugging Face model: {e}[/red]")

    def _send(
        self, data: list[DataSource]
    ) -> tuple[tuple[str | None, str | None], dict[str, Any] | None]:
        if not self.model_instance or not self.tokenizer:
            return (None, None), None

        messages = self._build_messages(data)

        # Prepare tools in OpenAI-like spec for the chat template
        tools_spec = None
        if self.tools_enabled and self.active_tools:
            tools_spec = registry.get_openai_spec(self.active_tools, provider="openai")

        # Apply Chat Template (requires transformers v4.39+)
        try:
            prompt = self.tokenizer.apply_chat_template(
                messages, tools=tools_spec, add_generation_prompt=True, tokenize=False
            )
        except Exception as e:
            logger.warning(
                f"Failed to apply chat template with tools: {e}. "
                "Falling back to standard template."
            )
            prompt = self.tokenizer.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=False
            )

        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)

        # Generation parameters (using model-specific config)
        max_new_tokens = self.model_config.get("max_new_tokens", 2048)
        try:
            max_new_tokens = int(max_new_tokens)
        except (ValueError, TypeError):
            max_new_tokens = 2048

        temperature = self.model_config.get("temperature", 0.7)
        try:
            temperature = float(temperature)
        except (ValueError, TypeError):
            temperature = 0.7

        with torch.no_grad():
            output_ids = self.model_instance.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                do_sample=temperature > 0,
                pad_token_id=self.tokenizer.eos_token_id,
            )

        # Decode only the newly generated tokens
        generated_ids = output_ids[0][inputs.input_ids.shape[-1] :]
        response_text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)

        # Parse response for tool calls
        # Note: Some models use specific tags, but latest Chat Templates
        # often handle this.
        # Here we attempt to parse JSON if the model is expected to output it.
        raw_content, tool_calls, reasoning = self._parse_hf_output(response_text)

        model_parts = self._build_model_parts(raw_content, tool_calls, reasoning)

        # Update history
        user_text = "".join(str(d.content) for d in data)
        if user_text:
            user_parts: list[str | ContentPart] = [ContentPart(text=user_text)]
            self.conversation.append(Message(role=Role.USER, parts=user_parts))

        model_msg = Message(role=Role.MODEL, parts=model_parts)
        self.conversation.append(model_msg)

        return (raw_content.strip(), (reasoning or "").strip()), {
            "total_tokens": len(output_ids[0])
        }

    def _parse_hf_output(self, text: str) -> tuple[str, list, str | None]:
        """Parses the generated text for content and potential tool calls."""
        # Simple JSON extraction logic as a fallback for models that don't use tags
        tool_calls = []
        content = text
        reasoning = None

        # Handle <think> tags if present
        if "<think>" in text:
            think_match = re.search(r"<think>(.*?)</think>", text, re.DOTALL)
            if think_match:
                reasoning = think_match.group(1).strip()
                content = re.sub(
                    r"<think>.*?</think>", "", text, flags=re.DOTALL
                ).strip()

        # Try to find JSON block for tool calls if the model is prompted for it
        # This is a heuristic; specific model families might need specific parsers.
        json_match = re.search(r"```json\n(.*?)\n```", content, re.DOTALL)
        if json_match:
            try:
                potential_json = json.loads(json_match.group(1))
                if isinstance(potential_json, list):
                    # Likely a list of tool calls
                    tool_calls = potential_json
                    content = content.replace(json_match.group(0), "").strip()
                elif (
                    isinstance(potential_json, dict) and "tool_calls" in potential_json
                ):
                    tool_calls = potential_json["tool_calls"]
                    content = content.replace(json_match.group(0), "").strip()
            except json.JSONDecodeError:
                pass

        return content, tool_calls, reasoning

    def _build_messages(self, data: list[DataSource]) -> list[dict[str, Any]]:
        msgs = []
        if self.system_prompt and self.system_prompt_enabled:
            msgs.append({"role": "system", "content": self.system_prompt})

        for m in self.conversation:
            role = "assistant" if m.role == Role.MODEL else m.role.value
            content_text = ""
            for p in m.parts:
                if isinstance(p, str):
                    content_text += p
                elif isinstance(p, ContentPart):
                    if p.text:
                        content_text += p.text
            if content_text:
                msgs.append({"role": role, "content": content_text})

        user_content = "".join(str(d.content) for d in data)
        if user_content:
            msgs.append({"role": "user", "content": user_content})
        return msgs

    def _build_model_parts(
        self, content: str, tool_calls: list, reasoning: str | None
    ) -> list[str | ContentPart]:
        parts: list[str | ContentPart] = []
        if reasoning:
            parts.append(ContentPart(thought=reasoning))
        if content:
            parts.append(ContentPart(text=content))
        for tc in tool_calls:
            # Normalize tool call format
            parts.append(
                ContentPart(
                    function_call={
                        "name": tc.get("name") or tc.get("function", {}).get("name"),
                        "args": tc.get("arguments")
                        or tc.get("function", {}).get("arguments")
                        or tc.get("args", {}),
                        "id": tc.get("id") or "call_" + str(hash(content))[:8],
                    }
                )
            )
        return parts
