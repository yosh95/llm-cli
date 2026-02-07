import fnmatch
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PolicyEngine:
    """
    Enhanced Role-Based Access Control (RBAC) & Attribute-Based Access Control (ABAC).
    Determines permissions based on user roles, subjects, and resource scopes.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        # Allow passing config directly, or load from global settings
        self.config = config or {}

        # Load security settings from global config if not explicitly provided
        if not self.config:
            try:
                from llm_cli.clients.config import _load_config_from_file

                full_conf = _load_config_from_file()
                self.config.update(full_conf.get("security", {}))
            except ImportError:
                pass

        self.intent_analyzer: Any = None

        # Default Policy Definitions
        self.roles: dict[str, dict[str, Any]] = {
            "admin": {
                "description": "Full access with guardrails",
                "allow_all": True,
            },
            "user": {
                "description": "Standard user access",
                "allowed_tools": [
                    "list_files",
                    "read_file",
                    "fetch_web_text",
                    "google_search",
                    "edit_file",
                ],
                "scopes": {
                    "edit_file": {"allowed_paths": [str(Path.home() / "*"), "./*"]},
                },
            },
            "guest": {
                "description": "Read-only access",
                "allowed_tools": [
                    "list_files",
                    "read_file",
                ],
                "scopes": {
                    "read_file": {"allowed_paths": ["./docs/*", "*.md"]},
                },
            },
        }

        # Subject-specific overrides (e.g., specific user@host)
        self.subjects: dict[str, dict[str, Any]] = self.config.get("subjects", {})

        # Merge user config into roles if provided
        if "roles" in self.config:
            for role_name, role_def in self.config["roles"].items():
                if role_name in self.roles:
                    self.roles[role_name].update(role_def)
                else:
                    self.roles[role_name] = role_def

    def _analyze_intent(
        self, user_prompt: str, tool_name: str, args: dict[str, Any]
    ) -> bool:
        """
        Uses a secondary LLM to verify if the tool call aligns with user intent.
        """
        if not user_prompt:
            logger.warning("Intent Analysis Skipped: No user prompt context available.")
            return True

        if not self.intent_analyzer:
            try:
                from llm_cli.security.intent_analyzer import IntentAnalyzer

                provider = self.config.get("intent_analyzer_provider", "google")
                model = self.config.get(
                    "intent_analyzer_model", "gemini-flash-lite-latest"
                )
                self.intent_analyzer = IntentAnalyzer(provider, model)
            except Exception as e:
                logger.error(f"Failed to initialize Intent Analyzer: {e}")
                return True  # Fail open if analyzer is broken

        logger.info(
            f"🧠 Verifying Intent: Prompt='{user_prompt[:50]}...' Tool='{tool_name}'"
        )
        is_safe, reason = self.intent_analyzer.verify_action(
            user_prompt, tool_name, args
        )

        if not is_safe:
            logger.warning(f"⛔ Intent Mismatch Detected: {reason}")
            # We print to console directly to inform user
            # Note: Ideally we should use the rich console from clients.base,
            # but importing it here might cause loops.
            # We use standard print with some rich markup which might be printed
            # as raw text if not handled, but usually PolicyEngine runs in the
            # context where rich is installed.
            print(f"SECURITY ALERT: Intent Analyzer Blocked Action.\nReason: {reason}")
            return False

        logger.info("✅ Intent Verified")
        return True

    def evaluate(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> bool:
        """
        Evaluate if the current user/context can execute the tool with given arguments.
        """
        user_id = context.get("user_id", "unknown")
        user_roles = context.get("roles", ["guest"])
        user_prompt = context.get("user_prompt", "")

        logger.info(
            f"🛡️  Policy Evaluation: Tool='{tool_name}', User='{user_id}', "
            f"Roles={user_roles}"
        )

        # 0. Intent Analysis (Dynamic Guardrail)
        if self.config.get("intent_analyzer_enabled", False):
            if not self._analyze_intent(user_prompt, tool_name, arguments):
                return False

        # 1. Subject-specific Evaluation (Highest Priority)
        if user_id in self.subjects:
            subject_policy = self.subjects[user_id]
            if tool_name in subject_policy.get("denied_tools", []):
                return False
            if tool_name in subject_policy.get("allowed_tools", []):
                return self._verify_scope(tool_name, arguments, subject_policy)

        # 2. Role-based Evaluation
        is_allowed = False
        active_policy: dict[str, Any] = {}

        for role_name in user_roles:
            role_def = self.roles.get(role_name)
            if not role_def:
                continue

            if role_def.get("allow_all", False):
                is_allowed = True
                active_policy = role_def
                break

            allowed_tools = role_def.get("allowed_tools", [])
            if tool_name in allowed_tools or "*" in allowed_tools:
                is_allowed = True
                active_policy = role_def
                break

        if not is_allowed:
            logger.warning(f"⛔ Access Denied: No role allows tool '{tool_name}'")
            return False

        # 3. Scope Verification (ABAC)
        # Check if the policy has specific restrictions for this tool
        if not self._verify_scope(tool_name, arguments, active_policy):
            logger.warning(
                f"⛔ Access Denied: Arguments out of scope for tool '{tool_name}'"
            )
            return False

        # 4. Global Safety Guardrails (Last line of defense)
        if not self._global_guardrails(tool_name, arguments):
            return False

        logger.info("✅ Access Granted")
        return True

    def _verify_scope(
        self, tool_name: str, arguments: dict[str, Any], policy: dict[str, Any]
    ) -> bool:
        """Verify if arguments match the allowed scopes in the policy."""
        scopes = policy.get("scopes", {})
        if tool_name not in scopes:
            return True  # No specific scope restriction

        tool_scope = scopes[tool_name]

        # Path-based restriction
        if "allowed_paths" in tool_scope:
            path = arguments.get("path") or arguments.get("directory")
            if path:
                allowed_patterns = tool_scope["allowed_paths"]
                if not any(fnmatch.fnmatch(path, p) for p in allowed_patterns):
                    logger.warning(
                        f"Scope Violation: Path '{path}' not in allowed patterns "
                        f"{allowed_patterns}"
                    )
                    return False

        # Command-based restriction
        if "allowed_commands" in tool_scope and tool_name == "execute_command":
            command = arguments.get("command", "")
            allowed_cmds = tool_scope["allowed_commands"]
            if not any(re.search(p, command) for p in allowed_cmds):
                logger.warning(
                    f"Scope Violation: Command '{command}' not in allowed patterns"
                )
                return False

        return True

    def _global_guardrails(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        """Hardcoded safety checks that apply to everyone, including admins."""
        path = arguments.get("path", "")
        if path:
            # Block sensitive system paths
            if re.match(
                r"^(/etc|/var|/usr|/root|/bin|/sbin|C:\\Windows|C:\\System32)", path
            ):
                logger.warning(
                    f"Guardrail: Attempt to access sensitive system path '{path}'"
                )
                return False

        if tool_name == "execute_command":
            command = arguments.get("command", "").lower()
            dangerous_patterns = [
                r"rm\s+-rf\s+/",
                r"mkfs",
                r"dd\s+if=",
                r"chmod\s+777",
                r"> /dev/sd",
            ]
            if any(re.search(p, command) for p in dangerous_patterns):
                logger.warning(
                    f"Guardrail: Dangerous command pattern detected: {command}"
                )
                return False

        return True


# Singleton instance will be re-initialized with config later
policy_engine = PolicyEngine()
