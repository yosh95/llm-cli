# llm_cli/modules/tools/interpreter.py

import logging
import os
import platform
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from llm_cli.clients.config import config_manager
from llm_cli.consts import MAX_OUTPUT_CHARS, MAX_OUTPUT_LINES
from llm_cli.modules.tool_registry import tool
from llm_cli.security.resource_manager import (
    limit_process_resources,
    set_resource_limits,
)

logger = logging.getLogger(__name__)


@tool(
    name="execute_python",
    desc=(
        "Execute a Python script to interact with the system. "
        "This tool is the replacement for shell commands. "
        "Use this for ANY system interaction, including tasks "
        "traditionally done via shell (e.g., 'ls', 'git', 'grep', 'find', 'ruff'). "
        "You MUST write complete, self-contained Python code. "
        f"IMPORTANT: Output is truncated to {MAX_OUTPUT_LINES} lines or "
        f"{MAX_OUTPUT_CHARS} characters. "
        "For security and reliability: "
        "1. For external commands, ALWAYS use subprocess.run() with shell=False. "
        "2. NEVER use os.system(), os.popen(), or any call with shell=True, "
        "as these will be blocked by the security policy. "
        "3. Prefer using safer standard library features, such as 'pathlib' for "
        "filesystem operations (e.g., Path.unlink() instead of os.remove()), "
        "unless calling an external CLI tool."
    ),
    params={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Complete Python code to execute. "
                    "Use standard libraries for most tasks. "
                    "For CLI tools (git, ruff, etc.), use "
                    "subprocess.run(..., shell=False). "
                    "Avoid high-risk calls like os.system(), eval(), or exec()."
                ),
            }
        },
        "required": ["code"],
    },
)
def execute_python(code: str) -> Any:
    from llm_cli.security.pqc import sign_tool_result
    from llm_cli.security.static_analyzer import analyze_python_safety

    # 0. Enforce static analysis before execution (Tier 1 Guardrail)
    is_safe, issues = analyze_python_safety(code)
    if not is_safe:
        error_msg = (
            "Security Violation: Python code failed static analysis.\n"
            f"Issues: {', '.join(issues)}"
        )
        return sign_tool_result(error_msg)

    # Use a default timeout of 300 seconds.
    timeout = int(
        str(
            config_manager.get("general", "command_timeout")
            or os.environ.get("LLM_CLI_COMMAND_TIMEOUT", "300")
        )
    )

    # Read memory limit from config, default to 1024MB (1GB)
    mem_limit_mb = int(
        str(config_manager.get("general", "max_command_memory_mb") or "1024")
    )

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
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_CONFIG_NOSYSTEM",
    }
    user_allowed_env = config_manager.get("security", "allowed_env_vars")
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

                # Structured output with simple section markers for cleaner display.
                # Uses --- STDOUT --- and --- STDERR --- to reduce visual noise.
                stdout = (stdout or "").rstrip()
                stderr = (stderr or "").rstrip()

                result = f"""--- STDOUT ---
{stdout or "(no output)"}
"""

                if stderr:
                    result += f"""--- STDERR ---
{stderr}
"""
                else:
                    result += """--- STDERR ---
(no output)
"""

                output = f"""{result}--- EXIT CODE: {exit_code} ---"""

                return sign_tool_result(output)

            except subprocess.TimeoutExpired:
                if platform.system() != "Windows":
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
                stdout, stderr = proc.communicate()
                error_msg = (
                    f"Error: Script timed out ({timeout}s). Partial STDOUT:\n{stdout}"
                )
                return sign_tool_result(error_msg)
    except Exception as e:
        logger.error(f"Error executing Python: {e}")
        return sign_tool_result(f"Error: {e}")
    finally:
        path_obj = Path(tmp_path)
        if path_obj.exists():
            try:
                path_obj.unlink()
            except OSError:
                pass
