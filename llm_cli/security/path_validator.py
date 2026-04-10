# llm_cli/security/path_validator.py

import fnmatch
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
    4. Checks against filename blocklist (blocked_filenames) — fnmatch patterns
       matched against the file's bare name (e.g. ".env*", "*.pem").
       Unlike blocked_paths (which targets directories or absolute paths),
       blocked_filenames protects sensitive files that live *inside* the
       allowed working directory and would otherwise pass the whitelist check.
    5. Protects the core security directory (Root of Trust).

    TOCTOU mitigation: resolve() is called **exactly once** and the resulting
    canonical Path object is used for every subsequent comparison.  Callers
    MUST use the returned object for all further path operations to avoid a
    second resolve() that could race against a symlink swap.
    """
    # Robustly strip surrounding quotes and whitespace
    path = path.strip().strip("'").strip('"').strip()

    # Normalize trailing slashes (pathlib.Path handles this, but we'll be explicit)
    # except for the root itself.
    if path and path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    from llm_cli.consts import LLM_CLI_BASE_DIR

    config = config_manager.load_config()
    security_config = config.get("security", {})

    allowed_paths = security_config.get("allowed_paths", ["."])
    blocked_paths = security_config.get("blocked_paths", [])
    blocked_filenames = security_config.get("blocked_filenames", [])

    # 1. Check for directory traversal patterns (lexical pre-filter)
    if ".." in path:
        raise PathValidationError("Access to path is forbidden.")

    try:
        # --- Single canonical resolution ---
        # resolve() follows symlinks and collapses ".." sequences.
        # This is the ONLY call to resolve() for the target path.
        # Every comparison below uses this one canonical object.
        path_obj = Path(path).expanduser().resolve()

        # 2. Block sensitive paths even if absolute paths are somewhat allowed
        # Explicitly protect the application's own configuration and identity keys
        # (Root of Trust)
        if path_obj == LLM_CLI_BASE_DIR or LLM_CLI_BASE_DIR in path_obj.parents:
            raise PathValidationError("Access to path is forbidden.")

        for blocked_path_str in blocked_paths:
            try:
                blocked_obj = Path(blocked_path_str).expanduser().resolve()
                if path_obj == blocked_obj or blocked_obj in path_obj.parents:
                    raise PathValidationError("Access to blocked path is forbidden.")
            except (ValueError, OSError):
                continue

        # 3. Filename blocklist — fnmatch patterns matched against the bare filename.
        # This protects files like .env, .env.local, id_rsa that live *inside*
        # the allowed working directory and would otherwise pass the whitelist.
        filename = path_obj.name
        for pattern in blocked_filenames:
            if fnmatch.fnmatch(filename, pattern):
                raise PathValidationError(
                    f"Access to filename '{filename}' is forbidden "
                    f"(matches blocked pattern '{pattern}')."
                )

        # 4. Whitelist check: Must stay within one of the allowed paths
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
            raise PathValidationError("Access to path is not in the whitelist.")

        # Return the single canonical Path so callers never need to call
        # resolve() again, preventing TOCTOU races from a second resolution.
        return path_obj

    except (ValueError, OSError) as e:
        if isinstance(e, PathValidationError):
            raise
        raise PathValidationError(f"Invalid path format: {e}") from e
