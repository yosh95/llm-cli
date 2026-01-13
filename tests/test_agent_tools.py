"""Tests for system tools like execute_command."""

import os
import subprocess
import time

import pytest

from llm_cli.modules.tools.system import execute_command


def test_basic_execution():
    """Verify that a normal command executes and returns output."""
    result = execute_command("echo 'hello world'")
    assert "STDOUT:" in result
    assert "hello world" in result
    assert "Exit Code: 0" in result


def test_interactive_command_no_hang():
    """Verify that commands waiting for input (like cat) exit without hanging."""
    # cat should exit immediately because stdin is set to DEVNULL.
    start_time = time.time()
    result = execute_command("cat")
    duration = time.time() - start_time

    assert duration < 5, "Interactive command should exit immediately via DEVNULL"
    assert "STDOUT:" in result


def test_stderr_capture():
    """Verify that standard error is correctly captured."""
    result = execute_command("ls non_existent_file_reallly_not_there")
    assert "STDERR:" in result
    assert "Exit Code: 0" not in result


def test_timeout_and_cleanup():
    """Verify that processes are terminated on timeout and partial output is captured."""
    # Use a short timeout for testing to avoid wasting time and hitting CI limits.
    os.environ["LLM_CLI_COMMAND_TIMEOUT"] = "2"
    try:
        start_time = time.time()
        # Use sleep command directly (safe command in whitelist)
        with pytest.raises(RuntimeError) as excinfo:
            execute_command("sleep 10")

        duration = time.time() - start_time
        assert 2 <= duration <= 5, f"Command should timeout around 2s, took {duration}s"
        assert "Command timed out (2s)." in str(excinfo.value)

        # Verify that the child process is not lingering (POSIX only)
        if os.name != "nt":
            # We use ps to check for the 'sleep 10' process
            ps_check = subprocess.run(
                "ps aux | grep 'sleep 10' | grep -v grep",
                shell=True,
                capture_output=True,
                text=True,
            )
            assert ps_check.stdout.strip() == "", (
                f"Child process 'sleep 10' should have been killed. Found:\n{ps_check.stdout}"
            )
    finally:
        if "LLM_CLI_COMMAND_TIMEOUT" in os.environ:
            del os.environ["LLM_CLI_COMMAND_TIMEOUT"]
