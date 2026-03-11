# llm_cli/modules/tools/interpreter.py

import logging
import os
import platform
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from llm_cli.clients.config import get_setting
from llm_cli.modules.tool_registry import tool
from llm_cli.security.resource_manager import set_resource_limits

logger = logging.getLogger(__name__)


@tool(
    name="execute_python",
    description=(
        "Execute a Python script to interact with the system. "
        "This tool is the replacement for shell commands. "
        "Use this for ANY system interaction, including tasks "
        "traditionally done via shell (e.g., 'ls', 'git', 'grep', 'find'). "
        "You MUST write complete, self-contained Python code. "
        "CRITICAL: You MUST include detailed comments in the code, "
        "explaining what each major block of code does. The user will "
        "read these comments to understand the script before approving it. "
        "To run external binaries, use 'subprocess.run' with a list of "
        "arguments and shell=False. Do not assume a shell environment exists. "
        "The code will be displayed to the user for manual approval before execution."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Complete Python code to execute. "
                    "Use standard libraries for most tasks. "
                    "Every major logic block MUST be accompanied by "
                    "a clear, detailed comment explaining its purpose."
                ),
            }
        },
        "required": ["code"],
    },
)
def execute_python(code: str) -> str:
    # Use a default timeout of 300 seconds.
    timeout = int(
        str(
            get_setting("command_timeout", "general")
            or os.environ.get("LLM_CLI_COMMAND_TIMEOUT", "300")
        )
    )

    # Read memory limit from config, default to 1024MB (1GB)
    mem_limit_mb = int(str(get_setting("max_command_memory_mb", "general") or "1024"))

    # Environment variables filtering
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
        "PYTHONPATH",
    }
    user_allowed_env = get_setting("allowed_env_vars", "security")
    if isinstance(user_allowed_env, list):
        for key in user_allowed_env:
            if isinstance(key, str):
                safe_env_keys.add(key)

    is_termux = any(k.startswith("TERMUX_") for k in os.environ)
    is_android = "ANDROID_ROOT" in os.environ
    if is_termux or is_android:
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

    env = {k: v for k, v in os.environ.items() if k in safe_env_keys}

    # Use 'python' or 'python3' depending on environment
    python_exe = "python3" if platform.system() != "Windows" else "python"

    # Create a temporary file to store the script
    with tempfile.NamedTemporaryFile(
        suffix=".py", mode="w", delete=False, encoding="utf-8"
    ) as tmp_file:
        tmp_file.write(code)
        tmp_path = tmp_file.name

    kwargs: dict[str, Any] = {
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
        # We use shell=False for security, running the script file directly
        with subprocess.Popen([python_exe, tmp_path], **kwargs) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                exit_code = proc.returncode

                result = f"STDOUT:\n{stdout}"
                if stderr:
                    result += f"\nSTDERR:\n{stderr}"

                return f"{result}\nExit Code: {exit_code}"

            except subprocess.TimeoutExpired:
                if platform.system() != "Windows":
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
                stdout, stderr = proc.communicate()
                raise RuntimeError(
                    f"Script timed out ({timeout}s). Partial STDOUT:\n{stdout}"
                ) from None
    except Exception as e:
        logger.error(f"Error executing Python: {e}")
        raise e
    finally:
        path_obj = Path(tmp_path)
        if path_obj.exists():
            try:
                path_obj.unlink()
            except OSError:
                pass
