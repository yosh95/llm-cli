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
def execute_python(code: str, **kwargs: Any) -> Any:
    from llm_cli.security.pqc import sign_tool_result
    from llm_cli.security.static_analyzer import analyze_python_safety

    # Extract PQC variant from security requirements (injected by registry)
    reqs = kwargs.get("__security_requirements__")
    variant_raw = reqs.get("pqc_variant") if isinstance(reqs, dict) else None
    variant = str(variant_raw) if variant_raw else "ML-DSA-65"

    # 0. Enforce static analysis before execution (Tier 1 Guardrail)
    is_safe, violations, warnings = analyze_python_safety(code)
    if not is_safe:
        issues = violations or warnings
        error_msg = (
            "Security Violation: Python code failed static analysis.\n"
            f"Issues: {', '.join(issues)}"
        )
        return sign_tool_result(error_msg, variant=variant)

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

    # Create a private temporary directory (mode=0o700) to hold the script.
    # This ensures the generated code is never readable by other users on the
    # same system, even if the cleanup finally-block is somehow delayed.
    # The directory itself is cleaned up in the outermost finally block.
    tmp_dir: str | None = None
    tmp_path: str | None = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix="llm_cli_exec_", suffix="_secure")
        # Restrict to owner-only access immediately after creation
        tmp_dir_path = Path(tmp_dir)
        tmp_dir_path.chmod(0o700)

        tmp_file_path = tmp_dir_path / "script.py"
        tmp_path = str(tmp_file_path)
        # Write with O_CREAT | O_WRONLY | O_EXCL and mode 0o600 (owner read/write only)
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)
        except Exception:
            os.close(fd)
            raise
    except Exception as e:
        logger.error(f"Error creating secure temp file: {e}")
        return sign_tool_result(f"Error: {e}", variant=variant)

    # Prepare command for execution
    cmd = [python_exe, tmp_path]

    exec_kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.DEVNULL,
        "text": True,
        "env": env,
    }

    if platform.system() != "Windows":
        exec_kwargs["start_new_session"] = True
        exec_kwargs["preexec_fn"] = lambda: set_resource_limits(mem_limit_mb, timeout)

    try:
        # We use shell=False for security, running the script file directly
        with subprocess.Popen(cmd, **exec_kwargs) as proc:
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

                return sign_tool_result(output, variant=variant)

            except subprocess.TimeoutExpired:
                if platform.system() != "Windows":
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
                stdout, stderr = proc.communicate()
                error_msg = (
                    f"Error: Script timed out ({timeout}s). Partial STDOUT:\n{stdout}"
                )
                return sign_tool_result(error_msg, variant=variant)
    except Exception as e:
        logger.error(f"Error executing Python: {e}")
        return sign_tool_result(f"Error: {e}", variant=variant)
    finally:
        # Inner cleanup: remove the script file first
        if tmp_path is not None:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass
        # Outer cleanup: remove the private directory
        if tmp_dir is not None:
            try:
                import shutil as _shutil

                _shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass
