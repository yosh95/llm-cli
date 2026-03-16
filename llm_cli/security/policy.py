import fnmatch
import logging
import os
from pathlib import Path
from typing import Any, Protocol, TypedDict, runtime_checkable

from llm_cli.security.path_validator import PathValidationError, validate_path

logger = logging.getLogger(__name__)


@runtime_checkable
class IntentVerifier(Protocol):
    """Protocol for intent analysis verification."""

    def verify_action(
        self, user_prompt: str, tool_name: str, args: dict[str, Any]
    ) -> tuple[bool, str]: ...


class RoleDefinition(TypedDict, total=False):
    """Structure of a role definition."""

    allow_all: bool
    allowed_tools: list[str]
    denied_tools: list[str]
    scopes: dict[str, dict[str, Any]]


class SecurityConfig(TypedDict, total=False):
    """Structure of the security configuration."""

    intent_analyzer_enabled: bool
    intent_analyzer_provider: str
    intent_analyzer_model: str
    intent_analyzer_fail_open: bool
    intent_analyzer_fail_open_tools: list[str]
    intent_analyzer_fail_closed_tools: list[str]
    roles: dict[str, RoleDefinition]
    subjects: dict[str, RoleDefinition]
    blocked_paths: list[str]


class EvaluationContext(TypedDict, total=False):
    """Context for policy evaluation."""

    user_id: str
    roles: list[str]
    user_prompt: str


class PolicyEngine:
    """
    Enhanced Role-Based Access Control (RBAC) & Attribute-Based Access Control (ABAC).
    Determines permissions based on user roles, subjects, and resource scopes.
    """

    def __init__(self, config: SecurityConfig | None = None):
        from llm_cli.security.cass import CASSOrchestrator

        self.cass = CASSOrchestrator()
        self.intent_analyzer: IntentVerifier | None = None
        self.roles: dict[str, RoleDefinition] = {}
        self.config: SecurityConfig = {}
        self.subjects: dict[str, RoleDefinition] = {}
        self._load_security_config(config)

    def _load_security_config(self, config: SecurityConfig | None = None) -> None:
        """
        Loads security configuration from the config file and merges any
        provided overrides.
        """
        provided_config = config or {}

        # 1. Load base security settings from the global config file
        self.config = {}
        try:
            from llm_cli.clients.config import _load_config_from_file

            full_conf = _load_config_from_file()
            self.config.update(full_conf.get("security", {}))  # type: ignore
        except ImportError:
            pass

        # 2. Override with caller-supplied values
        self.config.update(provided_config)

        # 3. Subject-specific overrides (e.g., specific user@host)
        self.subjects = self.config.get("subjects", {})

        # 4. Set Default Roles if not present (for test stability)
        if not self.roles:
            self.roles = {
                "admin": {"allow_all": True},
                "user": {"allowed_tools": ["*"]},
                "guest": {"allowed_tools": ["read_file_content", "search_files"]},
            }

        # 5. Merge user-defined roles into the defaults
        if "roles" in self.config:
            for role_name, role_def in self.config["roles"].items():
                if role_name in self.roles:
                    self.roles[role_name].update(role_def)
                else:
                    self.roles[role_name] = role_def

    def reinitialize(self, config: SecurityConfig | None = None) -> None:
        """Reload configuration and reset the engine state."""
        self.intent_analyzer = None
        self._load_security_config(config)

    def _analyze_intent(
        self, user_prompt: str, tool_name: str, args: dict[str, Any]
    ) -> bool:
        """
        Uses a secondary LLM to verify if the tool call aligns with user intent.
        NOTE: This approach is deprecated due to severe UX degradation (high latency).
        The system now relies on MambaSentinel (O(N) latency) and CASS orchestrator.
        """
        posture = self.cass.get_security_requirements(tool_name)

        # If CASS determines we don't need the legacy intent analyzer, bypass it.
        # This is the default behavior now to maintain high responsiveness.
        if not posture.get("use_intent_analyzer", False) and not self.config.get(
            "intent_analyzer_enabled", False
        ):
            return True

        if not user_prompt:
            logger.warning("Intent Analysis Skipped: No user prompt context available.")
            return True

        if not self.intent_analyzer:
            try:
                from llm_cli.security.intent_analyzer import IntentAnalyzer

                provider = str(self.config.get("intent_analyzer_provider", "google"))
                model = str(
                    self.config.get("intent_analyzer_model", "gemini-flash-lite-latest")
                )
                self.intent_analyzer = IntentAnalyzer(provider, model)
            except Exception as e:
                logger.error(f"Failed to initialize Intent Analyzer: {e}")
                # Configurable fail-open/closed.
                # Zero-Trust default should be fail-closed for high-risk tools.
                high_risk_tools = {
                    "execute_python",
                    "edit_file",
                    "create_or_overwrite_file",
                }
                if tool_name in high_risk_tools:
                    logger.error(f"Intent Analyzer failed. Blocked: '{tool_name}'")
                    return False

                fail_open = bool(self.config.get("intent_analyzer_fail_open", False))
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
            print(f"SECURITY ALERT: Intent Analyzer Blocked Action.\nReason: {reason}")
            return False

        logger.info("✅ Intent Verified")
        return True

    def evaluate(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: EvaluationContext,
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
                from typing import cast

                return self._verify_scope(
                    tool_name, arguments, cast(dict[str, Any], subject_policy)
                )

        # 2. Role-based Evaluation
        is_allowed = False
        final_policy: RoleDefinition = {}

        for role_name in user_roles:
            role_def = self.roles.get(role_name)
            if not role_def:
                continue

            if role_def.get("allow_all", False):
                is_allowed = True
                final_policy = role_def
                break

            allowed_tools = role_def.get("allowed_tools", [])
            if tool_name in allowed_tools or "*" in allowed_tools:
                is_allowed = True
                final_policy = role_def
                break

        if not is_allowed:
            logger.warning(f"⛔ Access Denied: No role allows tool '{tool_name}'")
            return False

        # 3. Scope Verification (ABAC)
        # Check if the policy has specific restrictions for this tool
        from typing import cast

        if not self._verify_scope(
            tool_name, arguments, cast(dict[str, Any], final_policy)
        ):
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
        scopes: dict[str, dict[str, Any]] = policy.get("scopes", {})
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

        return True

    def _global_guardrails(self, _tool_name: str, arguments: dict[str, Any]) -> bool:
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

        return True


# Singleton instance will be re-initialized with config later
policy_engine = PolicyEngine()
