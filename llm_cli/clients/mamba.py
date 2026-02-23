import json
import logging
import re
from pathlib import Path
from typing import Any

import tiktoken
import torch

from llm_cli.clients.base import BaseLlmClient, console
from llm_cli.clients.config import get_setting
from llm_cli.mamba_core.model import MambaLM
from llm_cli.modules.models import ContentPart, DataSource, Message, Role

logger = logging.getLogger(__name__)


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

        # Ensure self.model has a value for display
        if not self.model or self.model == "":
            self.model = "mamba-local"

        self._initialize_model()

        # Teacher LLM for online learning/critique
        self.teacher_enabled = get_setting("teacher_enabled", "mamba") or False
        self.teacher_client: BaseLlmClient | None = None
        if self.teacher_enabled:
            self._initialize_teacher()

        # Online optimizer
        self.learning_rate = float(get_setting("online_lr", "mamba") or 1e-5)
        self.optimizer = (
            torch.optim.AdamW(self.model_instance.parameters(), lr=self.learning_rate)
            if self.model_instance
            else None
        )
        self.criterion = torch.nn.CrossEntropyLoss(ignore_index=-100)

    def _initialize_teacher(self) -> None:
        """Initialize the teacher LLM based on config. Fail-safe if not configured."""
        provider = get_setting("teacher_provider", "mamba")
        model = get_setting("teacher_model", "mamba")

        if not provider or not model:
            console.print(
                "[yellow]Warning: Teacher LLM not configured (provider/model missing). "
                "Online learning mode is disabled.[/yellow]"
            )
            self.teacher_enabled = False
            return

        if provider not in ["ollama", "vllm"]:
            console.print(
                f"[red]Error: Teacher provider '{provider}' is not allowed. "
                "Distillation/Mentor mode is restricted to 'ollama' or 'vllm' "
                "to comply with ToS of commercial providers.[/red]"
            )
            self.teacher_enabled = False
            return

        from llm_cli.security.intent_analyzer import IntentAnalyzer

        try:
            # Re-use IntentAnalyzer's multi-provider client factory
            analyzer = IntentAnalyzer(provider, model)
            self.teacher_client = analyzer.client
            console.print(
                f"[bold cyan]Mentor Mode Active: using {provider}[/bold cyan]"
            )
        except Exception as e:
            console.print(f"[red]Failed to initialize Mentor: {e}[/red]")
            self.teacher_enabled = False

    def _initialize_model(self) -> None:
        # Configuration for the base model - must match training
        vocab_size = self.tokenizer.n_vocab
        d_model = get_setting("d_model", "mamba") or 512
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
            try:
                self.model_instance.load_state_dict(
                    torch.load(model_path, map_location=self.device)
                )
                console.print(
                    f"[green]Loaded Mamba model from {model_path} "
                    f"on {self.device}[/green]"
                )
            except Exception as e:
                console.print(f"[red]Error loading model weights: {e}[/red]")
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
        user_prompt = ""
        for item in data:
            user_prompt += str(item.content)
            self.conversation.append(
                Message(role=Role.USER, parts=[ContentPart(text=str(item.content))])
            )

        # 2. Generate with optional Mentor feedback loop
        # max_attempts > 1 only if teacher is available
        max_attempts = 2 if self.teacher_enabled else 1
        current_feedback = ""
        final_response_text = ""
        final_thought = None

        for attempt in range(max_attempts):
            response_text, thought = self._generate_mamba(current_feedback)

            if self.teacher_enabled:
                # Show raw Mamba output for debugging/transparency
                msg = f"[dim cyan]Raw Mamba Output (Attempt {attempt + 1}):[/dim cyan]"
                console.print(msg)
                console.print(response_text, style="dim", highlight=False)

            if not self.teacher_enabled:
                final_response_text, final_thought = response_text, thought
                break

            # Mentor Review
            is_valid, critique, correction = self._get_mentor_review(
                user_prompt, response_text
            )

            if is_valid or not correction:
                final_response_text, final_thought = response_text, thought
                # Even if valid, we can update weights if correction provided
                if correction:
                    self._online_update(user_prompt, correction)
                break
            else:
                msg = (
                    f"[yellow]Mentor Critique (Attempt {attempt + 1}): "
                    f"{critique}[/yellow]"
                )
                console.print(msg)
                current_feedback = (
                    f"MENTOR FEEDBACK: {critique}. CORRECT FORMAT: {correction}"
                )

                # Update weights using the teacher's gold standard
                if correction:
                    self._online_update(user_prompt, correction)

                if attempt == max_attempts - 1:
                    # Final fallback: use corrected version directly if Mamba failed
                    final_response_text = correction
                    final_thought = "Corrected by Mentor"

        # 3. Parse and update conversation (optimized for JSON)
        model_parts: list[str | ContentPart] = [
            ContentPart(text=final_response_text, thought=final_thought)
        ]

        try:
            # Expecting JSON: {"thought": "...", "message": "...", "tool_calls": [...]}
            clean_json = final_response_text.strip()
            clean_json = re.sub(r"```json\n?|\n?```", "", clean_json).strip()

            payload = json.loads(clean_json)
            if isinstance(payload, dict):
                final_thought = payload.get("thought", final_thought)
                calls = payload.get("tool_calls", [])
                for call in calls:
                    model_parts.append(ContentPart(function_call=call))

                final_response_text = payload.get("message", "")
                if isinstance(model_parts[0], ContentPart):
                    model_parts[0].text = final_response_text
                    model_parts[0].thought = final_thought
        except json.JSONDecodeError:
            # Fallback to legacy tag parsing if JSON fails
            calls = re.findall(r"<tool_call>(.*?)</tool_call>", final_response_text)
            for call_str in calls:
                try:
                    call_data = json.loads(call_str)
                    model_parts.append(ContentPart(function_call=call_data))
                except json.JSONDecodeError:
                    continue

        model_msg = Message(role=Role.MODEL, parts=model_parts)
        self.conversation.append(model_msg)

        return (final_response_text, final_thought), {"total_tokens": 0}

    def _generate_mamba(self, feedback: str = "") -> tuple[str, str | None]:
        """Core generation logic for Mamba."""
        full_prompt = (
            "SYSTEM: You are a structural data agent. "
            "Output ONLY valid JSON with 'thought', 'message', and 'tool_calls'.\n"
            # FUTURE: Once the model matures and understands JSON structure, consider
            # injecting a list of available tool names here to assist with selection.
            # For now, we rely on weight-based memorization via Mentor distillation.
        )
        if feedback:
            full_prompt += f"CONTEXT: {feedback}\n"

        for msg in self.conversation:
            role = msg.role.value
            content = msg.get_text()
            full_prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
        full_prompt += "<|im_start|>model\n"

        input_ids = torch.tensor(
            [self.tokenizer.encode(full_prompt)], device=self.device
        )
        generated_ids: list[int] = []
        max_new_tokens = 512
        states = None

        if self.model_instance is None:
            return "Error: Model not initialized", None

        self.model_instance.eval()
        with torch.no_grad():
            logits, states = self.model_instance.step(input_ids, states)
            next_token = torch.argmax(logits[:, -1, :], dim=-1)
            generated_ids.append(int(next_token.item()))

            im_end_token = self.tokenizer.encode(
                "<|im_end|>", allowed_special={"<|im_end|>"}
            )[0]

            for _ in range(max_new_tokens - 1):
                logits, states = self.model_instance.step(
                    next_token.unsqueeze(0), states
                )
                next_token = torch.argmax(logits[:, -1, :], dim=-1)
                if next_token.item() == im_end_token:
                    break
                generated_ids.append(int(next_token.item()))

        response_text = self.tokenizer.decode(generated_ids)
        return response_text, None

    def _get_mentor_review(
        self, user_prompt: str, mamba_output: str
    ) -> tuple[bool, str, str]:
        """Request review from Mentor LLM. Returns (is_valid, critique, correction)."""
        if not self.teacher_client:
            return True, "", ""

        # Get available tool descriptions for the mentor
        tool_descriptions = ""
        if hasattr(self, "mcp_manager") and self.mcp_manager:
            tools = self.mcp_manager.get_tool_definitions()
            tool_descriptions = json.dumps(tools, indent=2, ensure_ascii=False)

        prompt = f"""
        Review the following AI output for a digital agent.
        User Intent: "{user_prompt}"
        Agent Output (should be JSON):
        {mamba_output}

        Available Tools (only use these if needed):
        {tool_descriptions}

        Instructions:
        1. Check if the output is valid JSON with 'thought', 'message', 'tool_calls'.
        2. Ensure 'tool_calls' (if any) use only the Available Tools listed above.
        3. If the output is invalid, provide a full corrected JSON.
        4. If the intent can be fulfilled with tools, use them.

        Output ONLY a JSON object:
        {{"valid": bool, "critique": "string",
          "correction": "string_of_full_correct_json"}}
        """

        from llm_cli.modules.models import DataSource

        try:
            (res_text, _), _ = self.teacher_client._send(
                [DataSource(content=prompt, content_type="text/plain")]
            )
            if not res_text:
                return True, "", ""

            res_text = re.sub(r"```json\n?|\n?```", "", res_text).strip()
            result = json.loads(res_text)

            return (
                result.get("valid", True),
                result.get("critique", ""),
                result.get("correction", ""),
            )
        except Exception as e:
            logger.error(f"Mentor review failed: {e}")
            return True, "", ""

    def _online_update(self, user_prompt: str, target_json: str) -> None:
        """Single-step online training using teacher's correction. Auto-saves."""
        if not self.model_instance or not self.optimizer:
            return

        console.print("[dim]Learning from Mentor and saving weights...[/dim]")

        full_text = (
            f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
            f"<|im_start|>model\n{target_json}<|im_end|>\n"
        )
        tokens = self.tokenizer.encode(full_text)

        input_ids = torch.tensor(
            tokens[:-1], dtype=torch.long, device=self.device
        ).unsqueeze(0)
        labels = torch.tensor(
            tokens[1:], dtype=torch.long, device=self.device
        ).unsqueeze(0)

        self.model_instance.train()
        self.optimizer.zero_grad()

        logits = self.model_instance(input_ids)
        loss = self.criterion(logits.view(-1, logits.size(-1)), labels.view(-1))

        if not (torch.isnan(loss) or torch.isinf(loss)):
            loss.backward()
            torch.nn.utils.clip_grad_norm_(
                self.model_instance.parameters(), max_norm=1.0
            )
            self.optimizer.step()

            # Auto-save weights
            from llm_cli.consts import MAMBA_MODEL_PATH

            model_path_setting = get_setting("model_path", "mamba")
            save_path = (
                Path(model_path_setting) if model_path_setting else MAMBA_MODEL_PATH
            )
            try:
                torch.save(self.model_instance.state_dict(), save_path)
            except Exception as e:
                logger.error(f"Failed to auto-save Mamba weights: {e}")

        self.model_instance.eval()

    def _load_model_aliases(self) -> None:
        self.available_models = {"mamba-local": "mamba_model.pt"}
