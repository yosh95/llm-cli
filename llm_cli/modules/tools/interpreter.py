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

logger = logging.getLogger(__name__)


@tool(
    name="execute_python",
    description=(
        "Execute a Python script to interact with the system. "
        "This tool is the replacement for shell commands. "
        "Use this for ANY system interaction, including tasks "
        "traditionally done via shell (e.g., 'ls', 'git', 'grep', 'find', 'ruff'). "
        "You MUST write complete, self-contained Python code. "
        "For security and reliability: "
        "1. For external commands, ALWAYS use subprocess.run() with shell=False. "
        "2. NEVER use os.system(), os.popen(), or any call with shell=True, "
        "as these will be blocked by the security policy. "
        "3. Prefer using safer standard library features, such as 'pathlib' for "
        "filesystem operations (e.g., Path.unlink() instead of os.remove()), "
        "unless calling an external CLI tool."
    ),
    parameters={
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
def execute_python(
    code: str, __security_requirements__: dict[str, Any] | None = None
) -> Any:
    from llm_cli.security.pqc import sign_tool_result

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
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
        "GIT_CONFIG_NOSYSTEM",
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
            sandbox_profile = (__security_requirements__ or {}).get(
                "sandbox_profile"
            ) or "standard"

            # Define mapping for main directory binding
            # Isolated: Read-only bind for current directory
            # Standard: Read-write bind for current directory
            cwd_bind_flag = "--bind"
            if sandbox_profile == "isolated":
                cwd_bind_flag = "--ro-bind"
                logger.info("CASS: Applying isolated sandbox profile (Read-Only CWD)")

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
                "--unshare-all",  # Isolate network, ipc, uts, etc. (Tier 3)
                cwd_bind_flag,
                cwd,
                cwd,
                "--bind",
                tmp_path,
                tmp_path,
                "--chdir",
                cwd,
                "--die-with-parent",
            ]

            # Add binds for git configuration
            home_path = Path.home()
            for git_cfg in [".gitconfig", ".config/git/config"]:
                cfg_path = home_path / git_cfg
                if cfg_path.exists():
                    sandbox_cmd.extend(["--ro-bind", str(cfg_path), str(cfg_path)])

            # Add binds for directories in PATH that are in user's home
            # (e.g., virtualenvs, .local/bin)
            # This ensures tools like 'ruff' installed in these locations
            # are accessible.
            path_env = env.get("PATH", "")
            home_dir = str(Path.home())
            added_binds = set()
            for p in path_env.split(os.pathsep):
                if not p:
                    continue
                try:
                    p_path = Path(p).resolve()
                    if str(p_path).startswith(home_dir) and p_path.exists():
                        target_to_bind = p_path
                        # If it looks like a virtualenv, bind the root instead
                        # of just 'bin'
                        if (
                            p_path.name == "bin"
                            and (p_path.parent / "pyvenv.cfg").exists()
                        ):
                            target_to_bind = p_path.parent

                        if str(target_to_bind) not in added_binds and not str(
                            target_to_bind
                        ).startswith(cwd):
                            sandbox_cmd.extend(
                                ["--ro-bind", str(target_to_bind), str(target_to_bind)]
                            )
                            added_binds.add(str(target_to_bind))
                except Exception:
                    continue

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

                output = f"{result}\nExit Code: {exit_code}"

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
