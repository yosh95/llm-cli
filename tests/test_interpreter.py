"""Tests for Python interpreter tool."""

import os
import platform
from pathlib import Path

import pytest

from llm_cli.modules.tools.interpreter import execute_python


def _get_result_text(result):
    if isinstance(result, dict):
        return result["result"]
    return result


def test_basic_python_execution():
    """Verify that basic Python code executes and returns output."""
    code = "print('hello world')"
    result = _get_result_text(execute_python(code))
    assert "STDOUT:" in result
    assert "hello world" in result
    assert "Exit Code: 0" in result


def test_python_system_interaction():
    """Verify that Python can perform system tasks like listing files."""
    code = "import os; print(os.getcwd())"
    result = _get_result_text(execute_python(code))
    assert "STDOUT:" in result
    assert str(Path.cwd()) in result
    assert "Exit Code: 0" in result


def test_python_stderr_capture():
    """Verify that Python errors are captured in STDERR."""
    code = "import sys; print('error message', file=sys.stderr); sys.exit(1)"
    result = _get_result_text(execute_python(code))
    assert "STDERR:" in result
    assert "error message" in result
    assert "Exit Code: 1" in result


def test_python_timeout():
    """Verify that Python scripts are terminated on timeout."""
    os.environ["LLM_CLI_COMMAND_TIMEOUT"] = "2"
    try:
        code = "import time; time.sleep(10)"
        with pytest.raises(RuntimeError) as excinfo:
            execute_python(code)

        assert "Script timed out (2s)." in str(excinfo.value)
    finally:
        if "LLM_CLI_COMMAND_TIMEOUT" in os.environ:
            del os.environ["LLM_CLI_COMMAND_TIMEOUT"]


def test_subprocess_no_shell():
    """
    Verify that external commands can be run via subprocess.run (shell=False).
    This is the recommended way for agents to perform 'shell' tasks.
    """
    if platform.system() == "Windows":
        code = "import subprocess; subprocess.run(['cmd', '/c', 'echo', 'hello'], shell=False)"
    else:
        code = "import subprocess; subprocess.run(['echo', 'hello'], shell=False)"

    result = _get_result_text(execute_python(code))
    assert "hello" in result
    assert "Exit Code: 0" in result
