# llm_cli/security/path_validator.py

from pathlib import Path

from llm_cli.clients.config import _load_config_from_file


class PathValidationError(Exception):
    """Raised when a path fails security validation."""

    pass


def validate_path(path: str, allow_outside_cwd: bool | None = None) -> Path:
    """
    Validates a path against security policies:
    1. Prevents directory traversal (..).
    2. Restricts access to the current working directory (CWD) by default.
    3. Blocks access to sensitive system directories.
    """
    config = _load_config_from_file()
    security_config = config.get("security", {})

    if allow_outside_cwd is None:
        allow_outside_cwd = security_config.get("allow_outside_cwd", False)

    allow_sensitive_path_access = security_config.get(
        "allow_sensitive_path_access", False
    )

    # 1. Check for directory traversal patterns
    if ".." in path:
        raise PathValidationError(f"Directory traversal '..' is forbidden: {path}")

    try:
        # Resolve path to absolute form
        path_obj = Path(path).expanduser().resolve()
        cwd = Path.cwd().resolve()

        # 2. Sandbox check: Must stay within CWD unless allowed
        if not allow_outside_cwd:
            if not str(path_obj).startswith(str(cwd)):
                raise PathValidationError(
                    f"Access outside project directory is forbidden: {path}. "
                    "To allow this, set 'security.allow_outside_cwd = true' in config."
                )

        # 3. Block sensitive system paths even if absolute paths are somewhat allowed
        if not allow_sensitive_path_access:
            sensitive_prefixes = [
                "/etc",
                "/var",
                "/root",
                "/bin",
                "/sbin",
                "/usr",
                "/dev",
                "/proc",
                "/sys",
                "/boot",
                "/home",
            ]
            # Only check these if the path is absolute and looks like a system path
            str_path = str(path_obj)
            for prefix in sensitive_prefixes:
                if str_path.startswith(prefix) and not str_path.startswith(str(cwd)):
                    raise PathValidationError(
                        f"Access to sensitive system path is forbidden: {path}"
                    )

        return path_obj

    except (ValueError, OSError) as e:
        raise PathValidationError(f"Invalid path format: {e}") from e
