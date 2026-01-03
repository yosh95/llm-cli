# llm_cli/modules/tools/system.py

import subprocess
import os
import signal
import platform
from llm_cli.modules.tool_registry import tool
from llm_cli.security import validate_command, CommandValidationError


@tool(
    name="execute_command",
    description="Execute a shell command.",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to run."}
        },
        "required": ["command"]
    }
)
def execute_command(command: str) -> str:
    # Validate command against security whitelist
    try:
        validate_command(command)
    except CommandValidationError as e:
        return (
            f"Security Error: {e}\n\n"
            "For security reasons, only whitelisted commands are allowed. "
            "Check the allowed commands list in your config file "
            "(~/.config/llm_cli/config.toml) or see the default whitelist "
            "in llm_cli/security/command_validator.py"
        )

    # Use a default timeout of 60 seconds.
    # We allow internal overriding for testing purposes.
    timeout = int(os.environ.get("LLM_CLI_COMMAND_TIMEOUT", 60))

    kwargs = {
        "shell": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.DEVNULL,  # Prevent hanging on interactive prompts
        "text": True,
    }
    if platform.system() != "Windows":
        kwargs["start_new_session"] = True

    try:
        with subprocess.Popen(command, **kwargs) as proc:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                if platform.system() != "Windows":
                    # Kill the whole process group
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
                stdout, stderr = proc.communicate()
                return (
                    f"Error: Command timed out ({timeout}s). "
                    f"Partial STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
                )

        output = f"STDOUT:\n{stdout}"
        if stderr:
            output += f"\nSTDERR:\n{stderr}"
        return f"{output}\nExit Code: {proc.returncode}"
    except Exception as e:
        return f"Error: {e}"
