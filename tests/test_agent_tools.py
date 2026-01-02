import unittest
import subprocess
import time
import os
import signal
from llm_cli.modules.agent_tools import execute_command

class TestExecuteCommand(unittest.TestCase):
    def test_basic_execution(self):
        """正常なコマンドが実行され、出力を取得できるか確認"""
        result = execute_command("echo 'hello world'")
        self.assertIn("STDOUT:", result)
        self.assertIn("hello world", result)
        self.assertIn("Exit Code: 0", result)

    def test_interactive_command_no_hang(self):
        """catのような入力を待つコマンドがハングせずに終了するか確認"""
        # stdin=DEVNULLにより、catは即座に終了するはず
        start_time = time.time()
        result = execute_command("cat")
        duration = time.time() - start_time
        
        self.assertLess(duration, 5, "Interactive command should exit immediately via DEVNULL")
        self.assertIn("STDOUT:", result)

    def test_stderr_capture(self):
        """標準エラー出力が正しくキャプチャされるか確認"""
        result = execute_command("ls non_existent_file_reallly_not_there")
        self.assertIn("STDERR:", result)
        self.assertNotEqual("Exit Code: 0", result)

    def test_timeout_and_cleanup(self):
        """タイムアウト時にプロセスが終了し、部分出力を取得できるか確認"""
        # 60秒待つのは長いため、テスト用に一時的に短いタイムアウトで検証したいが、
        # 現在のコードは60固定なので、実際にタイムアウトを発生させる。
        # 注意: このテストは1分かかります。
        print("\n(Testing timeout - waiting 60s...)")
        start_time = time.time()
        result = execute_command("echo 'starting'; sleep 100; echo 'finished'")
        duration = time.time() - start_time

        self.assertTrue(60 <= duration <= 70, f"Command should timeout around 60s, took {duration}s")
        self.assertIn("Error: Command timed out (60s).", result)
        self.assertIn("Partial STDOUT:", result)
        self.assertIn("starting", result)
        self.assertNotIn("finished", result)

        # プロセスが残っていないか確認 (POSIXのみ)
        if os.name != 'nt':
            ps_check = subprocess.run("ps aux | grep 'sleep 100' | grep -v grep", shell=True, capture_output=True)
            self.assertEqual(ps_check.stdout, b"", "Child process 'sleep 100' should have been killed")

if __name__ == "__main__":
    unittest.main()
