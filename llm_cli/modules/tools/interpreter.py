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
from llm_cli.security.resource_manager import (
    limit_process_resources,
    set_resource_limits,
)
from llm_cli.security.static_analyzer import analyze_python_safety

logger = logging.getLogger(__name__)


@tool(
    name="execute_python",
    description=(
        "Execute a Python script to interact with the system. "
        "This tool is the replacement for shell commands. "
        "Use this for ANY system interaction, including tasks "
        "traditionally done via shell (e.g., 'ls', 'git', 'grep', 'find'). "
        "You MUST write complete, self-contained Python code."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Complete Python code to execute. "
                    "Use standard libraries for most tasks."
                ),
            }
        },
        "required": ["code"],
    },
)
def execute_python(code: str) -> str:
    # 1. Static Security Scan
    is_safe, issues = analyze_python_safety(code)
    if not is_safe:
        issue_str = "\n".join(f"- {i}" for i in issues)
        logger.warning(f"Static analysis found potential issues:\n{issue_str}")
        # Note: We don't necessarily block execution here if the user approves it,
        # but we provide this info to the audit log and potentially to the UI.
        # For now, we'll prefix the result with a warning.
        warning_prefix = f"⚠️ SECURITY WARNING (Static Analysis):\n{issue_str}\n\n"
    else:
        warning_prefix = ""

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

    # Prepare command for execution
    cmd = [python_exe, tmp_path]

    # Bubblewrap (bwrap) support for Linux sandboxing
    # Only attempt if on Linux and not in a restricted environment like Termux
    use_bwrap = (
        platform.system() == "Linux"
        and not is_termux
        and not is_android
        and get_setting("use_bwrap", "security") is not False
    )

    if use_bwrap:
        import shutil

        bwrap_path = shutil.which("bwrap")
        if bwrap_path:
            # Construct bwrap command
            # --ro-bind /usr /usr: Mount system libs as read-only
            # --dev /dev: Necessary devices
            # --proc /proc: Necessary for some python ops
            # --tmpfs /tmp: Private tmp
            # --bind . /app: Bind current dir to /app
            # --die-with-parent: Kill sandbox if parent dies
            cwd = str(Path.cwd())
            sandbox_cmd = [
                bwrap_path,
                "--ro-bind",
                "/usr",
                "/usr",
                "--ro-bind",
                "/lib",
                "/lib",
                "--ro-bind",
                "/lib64",
                "/lib64",
                "--ro-bind",
                "/bin",
                "/bin",
                "--ro-bind",
                "/sbin",
                "/sbin",
                "--ro-bind",
                "/etc/alternatives",
                "/etc/alternatives",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--unshare-all",  # Isolate network, ipc, uts, etc.
                "--share-net",  # Allow network for now, but could be toggled
                "--bind",
                cwd,
                cwd,
                "--bind",
                tmp_path,
                tmp_path,
                "--chdir",
                cwd,
                "--die-with-parent",
            ]
            cmd = sandbox_cmd + cmd
            logger.info("Using bubblewrap sandbox for Python execution")

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
        with subprocess.Popen(cmd, **kwargs) as proc:
            # Best effort resource limits (e.g., nice on Windows/Unix)
            limit_process_resources(proc, mem_limit_mb)
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                exit_code = proc.returncode

                result = f"STDOUT:\n{stdout}"
                if stderr:
                    result += f"\nSTDERR:\n{stderr}"

                return f"{warning_prefix}{result}\nExit Code: {exit_code}"

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
