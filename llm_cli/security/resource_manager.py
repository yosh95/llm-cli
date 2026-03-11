# llm_cli/security/resource_manager.py

import logging
import os

try:
    import resource
except ImportError:
    resource = None  # type: ignore

logger = logging.getLogger(__name__)


def set_resource_limits(mem_limit_mb: int, cpu_limit_sec: int) -> None:
    """Sets resource limits for the child process. (Linux/Unix only)"""
    if resource is None:
        return

    try:
        # Limit CPU time (seconds)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit_sec, cpu_limit_sec + 5))

        # Limit address space (Memory)
        is_termux = any(k.startswith("TERMUX_") for k in os.environ)
        is_android = "ANDROID_ROOT" in os.environ

        if not (is_termux or is_android):
            mem_limit = mem_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))
        else:
            logger.debug("Skipping RLIMIT_AS on Termux/Android to prevent SIGABRT.")

        # Limit file size
        file_limit = 50 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))

    except Exception as e:
        logger.warning(f"Failed to set resource limits: {e}")
