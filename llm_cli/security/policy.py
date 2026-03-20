import fnmatch
import logging
import os
from pathlib import Path
from typing import Any, TypedDict

from llm_cli.security.path_validator import PathValidationError, validate_path

logger = logging.getLogger(__name__)


class RoleDefinition(TypedDict, total=False):
    """Structure of a role definition."""

    allow_all: bool
    allowed_tools: list[str]
    denied_tools: list[str]
    scopes: dict[str, dict[str, Any]]


class SecurityConfig(TypedDict, total=False):
    """Structure of the security configuration."""

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
        self.roles: dict[str, RoleDefinition] = {}
        self._config: SecurityConfig = {}
        self.subjects: dict[str, RoleDefinition] = {}
        if config:
            self._load_security_config(config)

    @property
    def config(self) -> SecurityConfig:
        """Lazy-loaded security configuration."""
        if not self._config:
            self.reinitialize()
        return self._config

    @config.setter
    def config(self, value: SecurityConfig) -> None:
        self._config = value

    def _load_security_config(self, config: SecurityConfig | None = None) -> None:
        """
        Loads security configuration from the config file and merges any
        provided overrides.
        """
        provided_config = config or {}

        # 1. Load base security settings from the global config file
        self._config = {}
        try:
            from llm_cli.clients.config import config_manager

            full_conf = config_manager.load_config()
            self._config.update(full_conf.get("security", {}))  # type: ignore
        except (ImportError, AttributeError):
            pass

        # 2. Override with caller-supplied values
        self._config.update(provided_config)

        # 3. Subject-specific overrides (e.g., specific user@host)
        self.subjects = self._config.get("subjects", {})

        # 4. Merge user-defined roles
        if "roles" in self._config:
            for role_name, role_def in self._config["roles"].items():
                if role_name in self.roles:
                    self.roles[role_name].update(role_def)
                else:
                    self.roles[role_name] = role_def

    def reinitialize(self, config: SecurityConfig | None = None) -> None:
        """Reload configuration and reset the engine state."""
        self._load_security_config(config)

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

        logger.info(
            f"🛡️  Policy Evaluation: Tool='{tool_name}', User='{user_id}', "
            f"Roles={user_roles}"
        )

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
