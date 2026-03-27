"""Tests for Python interpreter tool."""

import os
import platform
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from llm_cli.modules.tools.interpreter import execute_python


def _get_result_text(result: Any) -> str:
    if isinstance(result, dict):
        return str(result["result"])
    return str(result)


def test_basic_python_execution() -> None:
    """Verify that basic Python code executes and returns output."""
    code = "print('hello world')"
    result = _get_result_text(execute_python(code))
    assert "--- STDOUT ---" in result
    assert "hello world" in result
    assert "--- EXIT CODE:" in result
    assert "STDOUT" in result


def test_python_system_interaction() -> None:
    """Verify that Python can perform system tasks like listing files."""
    code = "import os; print(os.getcwd())"
    result = _get_result_text(execute_python(code))
    assert "--- STDOUT ---" in result
    assert str(Path.cwd()) in result
    assert "--- EXIT CODE:" in result
    assert "STDOUT" in result


def test_python_stderr_capture() -> None:
    """Verify that Python errors are captured in STDERR."""
    code = "import sys; print('error message', file=sys.stderr); sys.exit(1)"
    result = _get_result_text(execute_python(code))
    assert "--- STDERR ---" in result
    assert "error message" in result
    assert "--- EXIT CODE:" in result
    assert "STDERR" in result


def test_python_timeout() -> None:
    """Verify that Python scripts are terminated on timeout."""
    os.environ["LLM_CLI_COMMAND_TIMEOUT"] = "2"
    try:
        code = "import time; time.sleep(10)"
        result = _get_result_text(execute_python(code))
        assert "Error: Script timed out (2s)." in result
    finally:
        if "LLM_CLI_COMMAND_TIMEOUT" in os.environ:
            del os.environ["LLM_CLI_COMMAND_TIMEOUT"]


def test_subprocess_no_shell() -> None:
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
    assert "--- EXIT CODE: 0" in result


# ============================================================
# 2-B: Secure temporary file management tests
# ============================================================


class TestSecureTempFile:
    """Verify that execute_python uses a secure, owner-only temp directory and
    cleans up all temporary artefacts after execution."""

    def test_temp_dir_cleaned_up_after_success(self) -> None:
        """The private temp directory must not exist after normal execution."""
        created_dirs: list[str] = []
        original_mkdtemp = tempfile.mkdtemp

        def tracking_mkdtemp(**kwargs: Any) -> str:
            path = str(original_mkdtemp(**kwargs))
            created_dirs.append(path)
            return path

        with patch("llm_cli.modules.tools.interpreter.tempfile.mkdtemp", tracking_mkdtemp):
            execute_python("print('hello')")

        assert created_dirs, "mkdtemp should have been called"
        for d in created_dirs:
            assert not Path(d).exists(), (
                f"Temporary directory '{d}' was not cleaned up after execution"
            )

    def test_temp_dir_cleaned_up_after_error(self) -> None:
        """The private temp directory must be removed even if the script raises."""
        created_dirs: list[str] = []
        original_mkdtemp = tempfile.mkdtemp

        def tracking_mkdtemp(**kwargs: Any) -> str:
            path = str(original_mkdtemp(**kwargs))
            created_dirs.append(path)
            return path

        with patch("llm_cli.modules.tools.interpreter.tempfile.mkdtemp", tracking_mkdtemp):
            execute_python("raise RuntimeError('deliberate error')")

        assert created_dirs
        for d in created_dirs:
            assert not Path(d).exists(), f"Temporary directory '{d}' leaked after script error"

    def test_temp_dir_has_owner_only_permissions(self) -> None:
        """On POSIX systems the temp directory must be mode 0o700 (owner only)."""
        if platform.system() == "Windows":
            return  # chmod semantics differ on Windows

        observed_modes: list[int] = []
        original_mkdtemp = tempfile.mkdtemp

        def tracking_mkdtemp(**kwargs: Any) -> str:
            path = str(original_mkdtemp(**kwargs))
            # Record the mode after execute_python has called os.chmod
            return path

        captured_dirs: list[str] = []
        original_chmod = os.chmod

        def tracking_chmod(path: str, mode: int, **kw: Any) -> None:
            if str(path).startswith(tempfile.gettempdir()):
                observed_modes.append(mode)
                captured_dirs.append(str(path))
            original_chmod(path, mode, **kw)

        with (
            patch("llm_cli.modules.tools.interpreter.tempfile.mkdtemp", tracking_mkdtemp),
            patch("llm_cli.modules.tools.interpreter.os.chmod", tracking_chmod),
        ):
            execute_python("print('permissions check')")

        assert any(m == 0o700 for m in observed_modes), (
            f"Expected at least one os.chmod(dir, 0o700) call; got modes={observed_modes}"
        )
