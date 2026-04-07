# llm_cli/security/resource_manager.py

import logging
import os
from typing import Any

try:
    import resource
except ImportError:
    resource = None  # type: ignore

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore

logger = logging.getLogger(__name__)


def set_resource_limits(mem_limit_mb: int, cpu_limit_sec: int, file_limit_mb: int = 50) -> None:
    """Sets resource limits for the current/child process (Unix-only via preexec_fn)."""
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
        file_limit = file_limit_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))

    except Exception as e:
        logger.warning(f"Failed to set Unix resource limits: {e}")


def limit_process_resources(process: Any, _mem_limit_mb: int) -> None:
    """Sets resource limits on an already running process object (Best effort)."""
    if psutil is None:
        return

    try:
        p = psutil.Process(process.pid)
        # Memory limit on Windows is harder but we can set working set size
        if os.name == "nt":
            # Best effort limit (soft limit)
            # On Windows, we can't strictly enforce address space limit like RLIMIT_AS
            # but we can set the process priority to avoid CPU hogging
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            # For Unix, we can also use nice
            p.nice(10)

    except Exception as e:
        logger.debug(f"Failed to apply psutil limits: {e}")
