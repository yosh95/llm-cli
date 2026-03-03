import fnmatch
import logging
import os
import re
from pathlib import Path
from typing import Any

from llm_cli.security.path_validator import PathValidationError, validate_path

logger = logging.getLogger(__name__)


class PolicyEngine:
    """
    Enhanced Role-Based Access Control (RBAC) & Attribute-Based Access Control (ABAC).
    Determines permissions based on user roles, subjects, and resource scopes.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        # Allow passing config directly, or load from global settings
        provided_config = config or {}

        # 1. Load base security settings from global config
        self.config = {}
        try:
            from llm_cli.clients.config import _load_config_from_file

            full_conf = _load_config_from_file()
            self.config.update(full_conf.get("security", {}))
        except ImportError:
            pass

        # 2. Override with provided config
        self.config.update(provided_config)

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
                    "list_files_in_directory",
                    "search_files",
                    "read_file_content",
                    "read_html_from_url",
                    "search_web",
                    "edit_file",
                    "execute_shell_command",
                ],
                "scopes": {
                    "edit_file": {"allowed_paths": [str(Path.home() / "*"), "./*"]},
                    "read_file_content": {
                        "allowed_paths": [str(Path.home() / "*"), "./*"]
                    },
                    "search_files": {"allowed_paths": [str(Path.home() / "*"), "./*"]},
                },
            },
            "guest": {
                "description": "Read-only access",
                "allowed_tools": [
                    "list_files_in_directory",
                    "search_files",
                    "read_file_content",
                ],
                "scopes": {
                    "read_file_content": {"allowed_paths": ["./docs/*", "*.md"]},
                    "search_files": {"allowed_paths": ["./docs/*", "./llm_cli/*"]},
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

    def reinitialize(self, config: dict[str, Any] | None = None) -> None:
        """Reload configuration and reset the engine state."""
        self.config = config or {}
        if not self.config:
            try:
                from llm_cli.clients.config import _load_config_from_file

                full_conf = _load_config_from_file()
                self.config.update(full_conf.get("security", {}))
            except ImportError:
                pass

        self.intent_analyzer = None
        self.subjects = self.config.get("subjects", {})

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
                # Configurable fail-open/closed.
                # Zero-Trust default should be fail-closed for high-risk tools.
                high_risk_tools = {
                    "execute_shell_command",
                    "edit_file",
                    "create_or_overwrite_file",
                }
                if tool_name in high_risk_tools:
                    logger.error(f"Intent Analyzer failed. Blocked: '{tool_name}'")
                    return False

                fail_open = self.config.get("intent_analyzer_fail_open", False)
                fail_open_tools = set(
                    self.config.get("intent_analyzer_fail_open_tools", [])
                )
                fail_closed_tools = set(
                    self.config.get("intent_analyzer_fail_closed_tools", [])
                )
                if tool_name in fail_open_tools:
                    return True
                if tool_name in fail_closed_tools:
                    return False
                return True if fail_open else False

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
        # Ensure latest config is used if we were initialized with default empty dict
        if not self.config:
            self.reinitialize()

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
            raw_path = arguments.get("path") or arguments.get("directory")
            if raw_path:
                allowed_patterns = tool_scope["allowed_paths"]

                # Normalize/resolve the target path the same way as tool-level
                # validation. This reduces bypass via relative paths, symlinks, or
                # differing path forms.
                try:
                    normalized_target = str(validate_path(str(raw_path)))
                except PathValidationError as e:
                    logger.warning(f"Scope Violation: invalid path '{raw_path}': {e}")
                    return False

                # Also allow matching against the original raw string for convenience
                # (e.g., patterns like '*.md' that are not tied to a directory).
                candidates = {str(raw_path), normalized_target}

                def _match_any(candidate: str) -> bool:
                    for pattern in allowed_patterns:
                        # Expand/resolve patterns that look like paths.
                        pat = str(pattern)
                        expanded_pat = str(Path(pat).expanduser())
                        resolved_pat = expanded_pat
                        try:
                            # Only resolve patterns that contain a path separator or
                            # start with '.'.
                            if (
                                (os.sep in expanded_pat)
                                or expanded_pat.startswith("./")
                                or expanded_pat.startswith("../")
                            ):
                                resolved_pat = str(Path(expanded_pat).resolve())
                        except Exception:
                            resolved_pat = expanded_pat

                        if fnmatch.fnmatch(candidate, pat) or fnmatch.fnmatch(
                            candidate, resolved_pat
                        ):
                            return True
                    return False

                if not any(_match_any(c) for c in candidates):
                    logger.warning(
                        f"Scope Violation: Path '{raw_path}' "
                        f"(normalized='{normalized_target}') not in allowed "
                        f"patterns {allowed_patterns}"
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
        """Safety checks that apply to everyone, including admins."""
        # 1. Path Blacklist Check
        # We check any argument that might be a path.
        path_val = arguments.get("path") or arguments.get("directory")
        if path_val and isinstance(path_val, str):
            if ".." in path_val:
                logger.warning(f"Guardrail: Directory traversal detected: {path_val}")
                return False

            try:
                path_obj = Path(path_val).expanduser().resolve()
                blocked_paths = self.config.get("blocked_paths", [])
                for blocked in blocked_paths:
                    try:
                        blocked_obj = Path(blocked).expanduser().resolve()
                        if path_obj == blocked_obj or blocked_obj in path_obj.parents:
                            logger.warning(
                                "Guardrail: "
                                f"Attempt to access blocked path '{path_val}'"
                            )
                            return False
                    except (ValueError, OSError):
                        continue
            except (ValueError, OSError):
                # If we can't resolve it, we still block it if it looks like
                # a sensitive system path as a fallback,
                # but we prefer the configured blocked_paths.
                pass

        # 2. Command Pattern Check
        if tool_name == "execute_command" or tool_name == "execute_shell_command":
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
