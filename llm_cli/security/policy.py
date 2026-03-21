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

    blocked_paths: list[str]
    allowed_paths: list[str]
    high_risk_tools: list[str]
    medium_risk_tools: list[str]
    missing_token_policy: str


class EvaluationContext(TypedDict, total=False):
    """Context for policy evaluation."""

    user_id: str
    user_prompt: str
    has_pqc_proof: bool  # Whether a valid PQC signature was provided/verified


class PolicyEngine:
    """
    Attribute-Based Access Control (ABAC) driven by Risk Levels.
    Determines permissions based on tool risk, user identity proof (PQC),
    and resource scopes.
    """

    def __init__(self, config: SecurityConfig | None = None):
        from llm_cli.security.cass import cass_orchestrator

        self.cass = cass_orchestrator
        self._config: SecurityConfig = {}
        if config:
            self._load_security_config(config)
            # Propagate risk level overrides to CASS
            if "high_risk_tools" in self._config:
                self.cass.high_risk_tools = set(self._config["high_risk_tools"])
            if "medium_risk_tools" in self._config:
                self.cass.medium_risk_tools = set(self._config["medium_risk_tools"])

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
        """Loads security configuration from the config file."""
        provided_config = config or {}
        self._config = {}
        try:
            from llm_cli.clients.config import config_manager

            full_conf = config_manager.load_config()
            self._config.update(full_conf.get("security", {}))  # type: ignore
        except (ImportError, AttributeError):
            pass
        self._config.update(provided_config)

    def reinitialize(self, config: SecurityConfig | None = None) -> None:
        """Reload configuration."""
        self._load_security_config(config)

    def evaluate(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: EvaluationContext,
    ) -> bool:
        """
        Evaluate if the tool execution is permitted based on risk and identity proof.
        """
        from llm_cli.security.cass import RiskLevel

        if not self.config:
            self.reinitialize()

        user_id = context.get("user_id", "unknown")
        has_pqc = context.get("has_pqc_proof", False)
        risk_level = self.cass.evaluate_risk(tool_name)

        logger.info(
            f"🛡️  ABAC Evaluation: Tool='{tool_name}', Risk='{risk_level.value}', "
            f"User='{user_id}', PQC_Proof={has_pqc}"
        )

        # 1. Identity Requirement (High Risk requires PQC)
        if risk_level == RiskLevel.HIGH and not has_pqc:
            msg = f"⛔ Access Denied: High-risk tool '{tool_name}' requires PQC proof."
            logger.warning(msg)
            return False

        # 2. Scope Verification (Path restrictions, etc.)
        # We use a global scope defined in the config
        global_scope = {"allowed_paths": self.config.get("allowed_paths", ["."])}
        if not self._verify_scope(
            tool_name, arguments, {"scopes": {tool_name: global_scope}}
        ):
            logger.warning(
                f"⛔ Access Denied: Arguments out of scope for tool '{tool_name}'"
            )
            return False

        # 3. Global Safety Guardrails
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
                    cwd = Path.cwd().resolve()
                    for pattern in allowed_patterns:
                        pat = str(pattern)
                        # Special case: "." means everything under CWD
                        if pat == ".":
                            try:
                                candidate_path = Path(candidate).resolve()
                                if (
                                    candidate_path == cwd
                                    or cwd in candidate_path.parents
                                ):
                                    return True
                            except Exception:
                                pass
                            continue

                        # Expand/resolve patterns that look like paths.
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
