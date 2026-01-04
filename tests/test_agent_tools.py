# tests/test_agent_tools.py

import os
import subprocess
import time
import unittest

from llm_cli.modules.tools.system import execute_command


class TestExecuteCommand(unittest.TestCase):
    def test_basic_execution(self):
        """Verify that a normal command executes and returns output."""
        result = execute_command("echo 'hello world'")
        self.assertIn("STDOUT:", result)
        self.assertIn("hello world", result)
        self.assertIn("Exit Code: 0", result)

    def test_interactive_command_no_hang(self):
        """Verify that commands waiting for input (like cat) exit without hanging."""
        # Now that we set stdin=DEVNULL, cat should exit immediately.
        start_time = time.time()
        result = execute_command("cat")
        duration = time.time() - start_time

        self.assertLess(
            duration, 5, "Interactive command should exit immediately via DEVNULL"
        )
        # result might contain "STDOUT:\n" and "Exit Code: 0"
        self.assertIn("STDOUT:", result)

    def test_stderr_capture(self):
        """Verify that standard error is correctly captured."""
        result = execute_command("ls non_existent_file_reallly_not_there")
        self.assertIn("STDERR:", result)
        self.assertNotEqual("Exit Code: 0", result)

    def test_timeout_and_cleanup(self):
        """Verify that processes are terminated on timeout and partial output is captured."""
        # Use a short timeout for testing to avoid wasting time and hitting CI limits.
        os.environ["LLM_CLI_COMMAND_TIMEOUT"] = "2"
        try:
            start_time = time.time()
            # Use sleep command directly (safe command in whitelist)
            result = execute_command("sleep 10")
            duration = time.time() - start_time

            self.assertTrue(
                2 <= duration <= 5,
                f"Command should timeout around 2s, took {duration}s",
            )
            self.assertIn("Error: Command timed out (2s).", result)

            # Verify that the child process is not lingering (POSIX only)
            if os.name != "nt":
                # We use ps to check for the 'sleep 10' process
                ps_check = subprocess.run(
                    "ps aux | grep 'sleep 10' | grep -v grep",
                    shell=True,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    ps_check.stdout.strip(),
                    "",
                    f"Child process 'sleep 10' should have been killed. Found:\n{ps_check.stdout}",
                )
        finally:
            if "LLM_CLI_COMMAND_TIMEOUT" in os.environ:
                del os.environ["LLM_CLI_COMMAND_TIMEOUT"]


if __name__ == "__main__":
    unittest.main()
