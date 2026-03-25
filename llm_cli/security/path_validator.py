# llm_cli/security/path_validator.py

from pathlib import Path

from llm_cli.clients.config import config_manager


class PathValidationError(Exception):
    """Raised when a path fails security validation."""

    pass


def validate_path(path: str) -> Path:
    """
    Validates a path against security policies defined in config.toml:
    1. Prevents directory traversal (..).
    2. Checks against whitelist (allowed_paths).
    3. Checks against blacklist (blocked_paths).
    4. Protects the core security directory (Root of Trust).
    """
    # Strip surrounding quotes if the LLM accidentally included them
    path = path.strip()
    if (path.startswith('"') and path.endswith('"')) or (
        path.startswith("'") and path.endswith("'")
    ):
        path = path[1:-1]

    from llm_cli.consts import LLM_CLI_BASE_DIR

    config = config_manager.load_config()
    security_config = config.get("security", {})

    allowed_paths = security_config.get("allowed_paths", ["."])
    blocked_paths = security_config.get("blocked_paths", [])

    # 1. Check for directory traversal patterns
    if ".." in path:
        raise PathValidationError(f"Directory traversal '..' is forbidden: {path}")

    try:
        # Resolve path to absolute form
        path_obj = Path(path).expanduser().resolve()

        # 2. Block sensitive paths even if absolute paths are somewhat allowed
        # Explicitly protect the application's own configuration and identity keys
        # (Root of Trust)
        if path_obj == LLM_CLI_BASE_DIR or LLM_CLI_BASE_DIR in path_obj.parents:
            raise PathValidationError(
                f"Access to the security configuration directory is forbidden: {path}"
            )

        for blocked_path_str in blocked_paths:
            try:
                blocked_obj = Path(blocked_path_str).expanduser().resolve()
                if path_obj == blocked_obj or blocked_obj in path_obj.parents:
                    raise PathValidationError(
                        f"Access to blocked path is forbidden: {path} "
                        f"(Matches blocked prefix: {blocked_path_str})"
                    )
            except (ValueError, OSError):
                continue

        # 3. Whitelist check: Must stay within one of the allowed paths
        is_allowed = False
        for allowed_path_str in allowed_paths:
            try:
                allowed_obj = Path(allowed_path_str).expanduser().resolve()
                if path_obj == allowed_obj or allowed_obj in path_obj.parents:
                    is_allowed = True
                    break
            except (ValueError, OSError):
                continue

        if not is_allowed:
            raise PathValidationError(
                f"Access to path is not in the whitelist: {path}. "
                "To allow this, add it to 'security.allowed_paths' in config."
            )

        return path_obj

    except (ValueError, OSError) as e:
        if isinstance(e, PathValidationError):
            raise
        raise PathValidationError(f"Invalid path format: {e}") from e
