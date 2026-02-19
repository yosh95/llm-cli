# llm_cli/modules/tools/system.py

import logging
import os
import platform
import signal
import subprocess
from typing import Any

try:
    import resource
except ImportError:
    resource = None  # type: ignore

from llm_cli.clients.config import get_setting
from llm_cli.modules.tool_registry import tool
from llm_cli.security import CommandValidationError, validate_command

logger = logging.getLogger(__name__)


def set_resource_limits(mem_limit_mb: int, cpu_limit_sec: int) -> None:
    """Sets resource limits for the child process. (Linux/Unix only)"""
    if resource is None:
        return

    try:
        # Limit CPU time (seconds)
        # Soft limit: Process receives SIGXCPU
        # Hard limit: Process receives SIGKILL
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit_sec, cpu_limit_sec + 5))

        # Limit address space (Memory)
        # Android/Termux linker allocates large virtual address spaces, which causes
        # SIGABRT (Exit Code -6) when RLIMIT_AS is set.
        is_termux = any(k.startswith("TERMUX_") for k in os.environ)
        is_android = "ANDROID_ROOT" in os.environ

        if not (is_termux or is_android):
            mem_limit = mem_limit_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (mem_limit, mem_limit))
        else:
            logger.debug("Skipping RLIMIT_AS on Termux/Android to prevent SIGABRT.")

        # Limit number of processes
        # resource.setrlimit(resource.RLIMIT_NPROC, (20, 20))

        # Limit file size
        file_limit = 50 * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))

    except Exception as e:
        logger.warning(f"Failed to set resource limits: {e}")


@tool(
    name="execute_shell_command",
    description=(
        "Execute a shell command. Use this for running tests, linters, git operations, "
        "or other development tasks. Do not use this for file editing; use "
        "'create_or_overwrite_file' or 'edit_file_by_replacing_lines' instead."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to run."},
            "max_output_length": {
                "type": "integer",
                "description": (
                    "Maximum number of characters to return in the output. "
                    "Truncates if exceeded."
                ),
            },
        },
        "required": ["command"],
    },
)
def execute_shell_command(command: str, max_output_length: int | None = None) -> str:
    # Validate command against security whitelist
    # Note: validation errors are now handled by the registry wrapper auditing
    try:
        validate_command(command)
    except CommandValidationError as e:
        # We raise the error here so the tool registry's wrapper catches it
        # and logs it as FAILED
        raise RuntimeError(f"Security Error: {e}") from e

    # Use a default timeout of 300 seconds.
    # Config > Env Var > Default
    timeout = int(
        str(
            get_setting("command_timeout", "general")
            or os.environ.get("LLM_CLI_COMMAND_TIMEOUT", "300")
        )
    )

    # Use configured max output length or default to 10000
    if max_output_length is None:
        max_output_length = int(
            str(get_setting("max_output_length", "general") or "10000")
        )

    # Read memory limit from config, default to 1024MB (1GB)
    mem_limit_mb = int(str(get_setting("max_command_memory_mb", "general") or "1024"))

    # 1. Define base safe environment variables
    safe_env_keys = {
        "PATH",
        "LANG",
        "LC_ALL",
        "TERM",
        "HOME",
        "USER",
        "PWD",
        "TMPDIR",
        "TEMP",
        "TMP",
    }

    # 2. Handle Termux/Android specifically
    # On these platforms, many system variables (including LD_PRELOAD for termux-exec)
    # are required for basic functionality like shebang resolution.
    is_termux = any(k.startswith("TERMUX_") for k in os.environ)
    is_android = "ANDROID_ROOT" in os.environ

    if is_termux or is_android:
        # We allow system-provided variables but exclude anything sensitive.
        # Note: CommandValidator already prevents the LLM from injecting NEW
        # environment variables via the command string (e.g., "LD_PRELOAD=... ls").
        # These values are inherited from the user's current shell session.
        sensitive_patterns = [
            "API_KEY",
            "SECRET",
            "PASSWORD",
            "TOKEN",
            "AUTH",
            "CREDENTIAL",
        ]
        for k in os.environ:
            k_upper = k.upper()
            if not any(pattern in k_upper for pattern in sensitive_patterns):
                safe_env_keys.add(k)

    # 3. Construct the environment for the subprocess
    env = {k: v for k, v in os.environ.items() if k in safe_env_keys}

    kwargs: dict[str, Any] = {
        "shell": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.DEVNULL,
        "text": True,
        "env": env,
    }

    if platform.system() != "Windows":
        kwargs["start_new_session"] = True
        kwargs["preexec_fn"] = lambda: set_resource_limits(mem_limit_mb, timeout)

    try:
        with subprocess.Popen(command, **kwargs) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                exit_code = proc.returncode

                result = f"STDOUT:\n{stdout}"
                if stderr:
                    result += f"\nSTDERR:\n{stderr}"

                if len(result) > max_output_length:
                    result = (
                        result[:max_output_length]
                        + "\n[... OUTPUT TRUNCATED DUE TO LENGTH LIMIT ...]"
                    )

                return f"{result}\nExit Code: {exit_code}"

            except subprocess.TimeoutExpired:
                if platform.system() != "Windows":
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
                stdout, stderr = proc.communicate()

                error_msg = f"Command timed out ({timeout}s). Partial STDOUT:\n{stdout}"
                if stderr:
                    error_msg += f"\nPartial STDERR:\n{stderr}"

                if len(error_msg) > max_output_length:
                    error_msg = (
                        error_msg[:max_output_length]
                        + "\n[... ERROR MESSAGE TRUNCATED DUE TO LENGTH LIMIT ...]"
                    )

                # Raising error so registry wrapper logs it
                raise RuntimeError(error_msg) from None

    except Exception as e:
        # Re-raise to let the tool_registry wrapper handle logging
        raise e
