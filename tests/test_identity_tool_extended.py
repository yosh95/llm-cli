import runpy
from unittest.mock import patch


def test_identity_tool_module_main():
    with patch("sys.argv", ["llm-cli-identity", "--help"]):
        try:
            runpy.run_module("llm_cli.apps.identity_tool", run_name="__main__")
        except SystemExit:
            pass
