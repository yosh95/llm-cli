import logging
import os
from pathlib import Path

from llm_cli.consts import LLM_CLI_BASE_DIR

logger = logging.getLogger(__name__)


def setup_permissions() -> None:
    """
    Enforce strict user-only permissions for all tool-generated data.
    Sets process umask and fixes existing file/directory permissions.
    """
    # 1. Set umask so newly created files/dirs are restricted by default.
    # umask 0077 means:
    #   Dirs: 0777 & ~0077 = 0700 (drwx------)
    #   Files: 0666 & ~0077 = 0600 (-rw-------)
    os.umask(0o077)

    # 2. Ensure base directory exists with correct permissions.
    if not LLM_CLI_BASE_DIR.exists():
        try:
            LLM_CLI_BASE_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
        except Exception as e:
            logger.warning(f"Could not create base directory {LLM_CLI_BASE_DIR}: {e}")
            return
    else:
        # Fix base directory if it's too open
        _ensure_mode(LLM_CLI_BASE_DIR, 0o700)

    # 3. Fix permissions for critical subdirectories and files.
    # We do this once during startup to ensure a secure state.
    for item in LLM_CLI_BASE_DIR.rglob("*"):
        if item.is_dir():
            _ensure_mode(item, 0o700)
        else:
            _ensure_mode(item, 0o600)


def _ensure_mode(path: Path, mode: int) -> None:
    """Ensure the path has the exact permissions specified."""
    try:
        current_mode = path.stat().st_mode & 0o777
        if current_mode != mode:
            path.chmod(mode)
    except Exception as e:
        logger.debug(f"Failed to set permissions for {path}: {e}")
