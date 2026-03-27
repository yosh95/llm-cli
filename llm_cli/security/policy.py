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

        # 0. Security Level Check (Compatibility Mode)
        security_level = os.getenv("LLM_CLI_SECURITY_LEVEL") or self.config.get(
            "security_level", "high"
        )

        logger.info(
            f"ABAC Evaluation: Tool='{tool_name}', Risk='{risk_level.value}', "
            f"User='{user_id}', PQC_Proof={has_pqc}, Level='{security_level}'"
        )

        # 1. Identity Requirement (High Risk requires PQC)
        if risk_level == RiskLevel.HIGH and not has_pqc:
            if security_level == "high":
                msg = (
                    f"[DENIED] Access Denied: High-risk tool "
                    f"'{tool_name}' requires PQC proof."
                )
                logger.warning(msg)
                return False
            else:
                logger.info(
                    f"[WARNING] Standard Mode: Permitting "
                    f"high-risk tool '{tool_name}' without PQC proof."
                )

        # 2. Scope Verification (Path restrictions, etc.)
        # We use a global scope defined in the config
        global_scope = {"allowed_paths": self.config.get("allowed_paths", ["."])}
        if not self._verify_scope(
            tool_name, arguments, {"scopes": {tool_name: global_scope}}
        ):
            logger.warning(
                f"[DENIED] Access Denied: Arguments out of scope for tool '{tool_name}'"
            )
            return False

        # 3. Global Safety Guardrails
        if not self._global_guardrails(tool_name, arguments):
            return False

        logger.info("[OK] Access Granted")
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
            # Look for common path-like argument names
            PATH_ARGS = [
                "path",
                "directory",
                "file",
                "filename",
                "src",
                "dest",
                "destination",
            ]
            for arg_name in PATH_ARGS:
                raw_path = arguments.get(arg_name)
                if raw_path and isinstance(raw_path, str):
                    allowed_patterns = tool_scope["allowed_paths"]

                    # validate_path() performs a single canonical resolve() and all
                    # security checks (blocklist, whitelist, Root-of-Trust guard).
                    try:
                        canonical_path_obj = validate_path(str(raw_path))
                        normalized_target = str(canonical_path_obj)
                    except PathValidationError as e:
                        logger.warning(
                            f"Scope Violation: invalid path in '{arg_name}'="
                            f"'{raw_path}': {e}"
                        )
                        return False

                    # Also allow matching against the original raw string for
                    # convenience (e.g., patterns like '*.md' that are not
                    # tied to a directory).
                    candidates = {str(raw_path), normalized_target}

                    found_match = False
                    cwd = Path.cwd().resolve()
                    for candidate in candidates:
                        # Use the already-resolved canonical object when the candidate
                        # matches the normalized form to avoid a third resolve() call.
                        if candidate == normalized_target:
                            candidate_resolved = canonical_path_obj
                        else:
                            candidate_resolved = Path(candidate)

                        for pattern in allowed_patterns:
                            pat = str(pattern)
                            # Special case: "." means everything under CWD
                            if pat == ".":
                                try:
                                    # candidate_resolved.parts returns a tuple of
                                    # strings, so comparing a Path object against it
                                    # with `in` is always False (was a silent bug).
                                    # The correct check is:
                                    #   - exact match with CWD, OR
                                    #   - CWD is an ancestor of the candidate
                                    #     (i.e. candidate lives *inside* CWD)
                                    if (
                                        candidate_resolved == cwd
                                        or cwd in candidate_resolved.parents
                                    ):
                                        found_match = True
                                        break
                                except Exception:
                                    pass
                                continue

                            # Expand/resolve patterns that look like paths.
                            expanded_pat = str(Path(pat).expanduser())
                            resolved_pat = expanded_pat
                            try:
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
                                found_match = True
                                break
                        if found_match:
                            break

                    if not found_match:
                        logger.warning(
                            f"Scope Violation: Path in '{arg_name}'='{raw_path}' "
                            f"(normalized='{normalized_target}') not in allowed "
                            f"patterns {allowed_patterns}"
                        )
                        return False

            # If the tool is in a scope that requires allowed_paths, but no path
            # argument was found, we should be careful. For now, we allow it if no
            # known path argument is present, assuming the tool might be using
            # the scope for something else or doesn't need a path.

        return True

    def _global_guardrails(self, _tool_name: str, arguments: dict[str, Any]) -> bool:
        """Safety checks that apply to everyone, including admins."""
        # 1. Path Blacklist Check
        # We check any argument that might be a path.
        PATH_ARGS = [
            "path",
            "directory",
            "file",
            "filename",
            "src",
            "dest",
            "destination",
        ]

        for arg_name in PATH_ARGS:
            path_val = arguments.get(arg_name)
            if path_val and isinstance(path_val, str):
                # Resolve the path first so that encoded traversal sequences
                # (e.g. URL-encoded "%2e%2e", null-byte injections, or symlinks
                # that point outside the workspace) are all normalised to their
                # canonical absolute form before any comparison is made.

                # Strip surrounding quotes if the LLM accidentally included them
                path_val = path_val.strip()
                if (path_val.startswith('"') and path_val.endswith('"')) or (
                    path_val.startswith("'") and path_val.endswith("'")
                ):
                    path_val = path_val[1:-1]

                try:
                    path_obj = Path(path_val).expanduser().resolve()
                except (ValueError, OSError) as exc:
                    logger.warning(
                        f"Guardrail: Could not resolve path '{path_val}' in "
                        f"'{arg_name}': {exc}"
                    )
                    # If it's a path argument that can't be resolved, it might
                    # be an attempt to bypass via invalid characters. Block it.
                    return False

                blocked_paths = self.config.get("blocked_paths", [])
                for blocked in blocked_paths:
                    try:
                        blocked_obj = Path(blocked).expanduser().resolve()
                        if path_obj == blocked_obj or blocked_obj in path_obj.parents:
                            logger.warning(
                                "Guardrail: "
                                f"Attempt to access blocked path '{path_val}' "
                                f"(resolved='{path_obj}', "
                                f"matched blocked='{blocked_obj}')"
                            )
                            return False
                    except (ValueError, OSError):
                        continue

        return True


# Singleton instance will be re-initialized with config later
policy_engine = PolicyEngine()
