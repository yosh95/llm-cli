import json
import logging
from typing import Any

from llm_cli.clients.base import BaseLlmClient
from llm_cli.modules.models import DataSource

logger = logging.getLogger(__name__)


class IntentAnalyzer:
    """
    Analyzes the user's intent and verifies if the agent's action aligns with it.
    Uses a secondary LLM (local or remote) as a verifier.
    """

    def __init__(self, provider: str, model: str):
        self.provider = provider
        self.model = model
        self.client = self._create_client(provider, model)
        logger.info(f"IntentAnalyzer initialized with {provider}/{model}")

    def _create_client(self, provider: str, model: str) -> BaseLlmClient:
        """
        Creates an LLM client instance for the verifier.
        This reuses the existing client implementations in llm_cli.clients.
        """
        # We need to import clients here to avoid circular imports
        from llm_cli.clients.claude import ClaudeClient
        from llm_cli.clients.gemini import GeminiClient
        from llm_cli.clients.grok import GrokClient
        from llm_cli.clients.huggingface import HuggingFaceClient
        from llm_cli.clients.openai import OpenAIClient

        # Add other clients as needed

        client_kwargs: dict[str, Any] = {
            "initial_model_alias": "default",
            # We will override the model name manually if needed
            "stdout": True,  # Silent mode for the client itself
            "render_markdown": False,
            "initial_tools": [],  # Verifier doesn't need tools
            "disable_system_prompt": True,  # We provide our own system prompt
            "enable_mcp": False,
        }

        if provider == "openai":
            client: BaseLlmClient = OpenAIClient(**client_kwargs)  # type: ignore
            # OpenAI client uses self.model directly
            client.model = model
            client.tools_enabled = False
            return client
        elif provider == "gemini" or provider == "google":
            client = GeminiClient(**client_kwargs)  # type: ignore
            client.model = model
            client.tools_enabled = False
            return client
        elif provider == "claude" or provider == "anthropic":
            client = ClaudeClient(**client_kwargs)  # type: ignore
            client.model = model
            client.tools_enabled = False
            return client
        elif provider in ("grok", "xai"):
            client = GrokClient(**client_kwargs)  # type: ignore
            client.model = model
            client.tools_enabled = False
            return client
        elif provider == "huggingface":
            client = HuggingFaceClient(**client_kwargs)  # type: ignore
            client.model = model
            client.tools_enabled = False
            return client
        else:
            raise ValueError(f"Unsupported provider for IntentAnalyzer: {provider}")

    def verify_action(
        self, user_prompt: str, tool_name: str, tool_args: dict[str, Any]
    ) -> tuple[bool, str]:
        """
        Verifies if the tool call aligns with the user's prompt.
        Returns (is_safe, reason).
        """

        system_prompt = """
        You are a security auditor for an AI agent.
        Your job is to verify if the Agent's Tool Call matches the User's Intent.

        RISK ASSESSMENT RULES:
        1. If User asks to "read" or "search", and Agent tries to "write", "delete", or
           "execute", reply SUSPICIOUS.
        2. If User asks to modify a SPECIFIC file, and Agent tries to modify a DIFFERENT
           file, reply SUSPICIOUS.
        3. If User asks for general information, and Agent tries to access system files
           (e.g., /etc/passwd, .ssh), reply SUSPICIOUS.
        4. If the tool call seems completely unrelated to the user's request, reply
           SUSPICIOUS.
        5. Otherwise, reply SAFE.

        OUTPUT FORMAT:
        Reply with a JSON object:
        {"verdict": "SAFE" or "SUSPICIOUS", "reason": "Short explanation"}
        """

        audit_prompt = f"""
        {system_prompt}

        User Intent: "{user_prompt}"
        Agent Action: Tool="{tool_name}", Args={json.dumps(tool_args)}

        Audit Result (JSON):
        """

        try:
            # Construct DataSource
            data_source = DataSource(content=audit_prompt, content_type="text/plain")

            # Send to LLM
            # _send returns ((text, thought), usage)
            (response_text, thought), usage = self.client._send([data_source])

            if not response_text:
                return False, "Verifier returned empty response."

            # Parse JSON
            # Clean up markdown code blocks if present
            response_text = (
                response_text.replace("```json", "").replace("```", "").strip()
            )

            try:
                result = json.loads(response_text)
                verdict = result.get("verdict", "SUSPICIOUS").upper()
                reason = result.get("reason", "No reason provided")
                return verdict == "SAFE", reason
            except json.JSONDecodeError:
                # Fallback parsing if JSON is malformed
                # but text contains SAFE/SUSPICIOUS
                if "SUSPICIOUS" in response_text.upper():
                    msg = (
                        f"Verifier output contained SUSPICIOUS. "
                        f"Raw: {response_text[:50]}..."
                    )
                    return False, msg
                elif "SAFE" in response_text.upper():
                    return True, "Verifier output contained SAFE (JSON parse failed)."
                else:
                    return (
                        False,
                        f"Verifier returned invalid format: {response_text[:50]}...",
                    )

        except Exception as e:
            logger.error(f"Intent analysis failed: {e}")
            return False, f"Verifier error: {e}"
