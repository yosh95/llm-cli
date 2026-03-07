from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_cli.modules.tool_registry import ToolRegistry
from llm_cli.modules.tool_registry import tool as tool_decorator


@pytest.fixture
def registry():
    return ToolRegistry()


def test_register_tool(registry):
    def my_tool(a: int, explanation: str):
        return a * 2

    registry.register(
        name="test_tool",
        func=my_tool,
        description="A test tool",
        parameters={"type": "object", "properties": {"a": {"type": "integer"}}},
    )

    assert "test_tool" in registry.tools
    t = registry.tools["test_tool"]
    assert t["name"] == "test_tool"
    assert t["description"] == "A test tool"
    assert "explanation" in t["parameters"]["properties"]
    assert "explanation" in t["parameters"]["required"]


def test_tool_wrapper_execution(registry):
    mock_func = MagicMock(return_value="Success")
    registry.register(name="mock_tool", func=mock_func, description="Mock description")

    wrapped_func = registry.tools["mock_tool"]["func"]

    # Test execution with explanation
    result = wrapped_func(explanation="Testing", unknown_arg="ignored")
    assert result == "Success"
    mock_func.assert_called_once()
    # Check that unknown_arg was filtered out if not in signature,
    # but wait, the wrapper filters based on sig.


def test_tool_wrapper_filtering(registry):
    def real_func(a, b=1):
        return a + b

    registry.register("add", real_func, "add tool")
    wrapped = registry.tools["add"]["func"]

    # explanation is popped, extra is filtered
    assert wrapped(a=5, extra=10, explanation="test") == 6


def test_tool_wrapper_var_kwargs(registry):
    def var_func(**kwargs):
        return len(kwargs)

    registry.register("var", var_func, "var tool")
    wrapped = registry.tools["var"]["func"]

    # extra should be kept because of **kwargs
    # explanation is also passed to the function
    assert wrapped(a=1, b=2, extra=3, explanation="test") == 4


def test_tool_wrapper_audit_logging(registry):
    with patch("llm_cli.modules.tool_registry.log_audit") as mock_log:

        def my_func(x):
            return f"Result: {x} Exit Code: 0"

        registry.register("audit_test", my_func, "desc")
        wrapped = registry.tools["audit_test"]["func"]

        wrapped(x=10, explanation="why not", __audit_model__="gpt-4o")

        mock_log.assert_called_once()
        args, kwargs = mock_log.call_args
        assert kwargs["tool_name"] == "audit_test"
        assert kwargs["args"]["x"] == 10
        assert kwargs["exit_code"] == 0
        assert kwargs["context"]["model"] == "gpt-4o"


def test_tool_wrapper_exception_logging(registry):
    with patch("llm_cli.modules.tool_registry.log_audit") as mock_log:

        def error_func():
            raise ValueError("Boom")

        registry.register("error_tool", error_func, "desc")
        wrapped = registry.tools["error_tool"]["func"]

        with pytest.raises(ValueError, match="Boom"):
            wrapped(explanation="err")

        mock_log.assert_called_once()
        _, kwargs = mock_log.call_args
        assert kwargs["error"] == "Boom"


def test_shutdown_hooks(registry):
    sync_hook = MagicMock()
    async_hook = AsyncMock()

    registry.register_shutdown_hook(sync_hook)
    registry.register_shutdown_hook(async_hook)

    # Register same hook twice, should be ignored
    registry.register_shutdown_hook(sync_hook)
    assert len(registry.shutdown_hooks) == 2

    with patch("asyncio.get_event_loop") as mock_get_loop:
        mock_loop = MagicMock()
        mock_get_loop.return_value = mock_loop

        # When run_until_complete is called, we should ideally await the coroutine
        # but since we are in a sync test and using a mock loop, we can't easily.
        # However, we can make sure the coroutine is at least closed to avoid the warning.
        def side_effect(coro):
            coro.close()
            return None

        mock_loop.run_until_complete.side_effect = side_effect

        registry.shutdown()
        mock_loop.run_until_complete.assert_called_once()

    sync_hook.assert_called_once()


def test_shutdown_hooks_exception(registry):
    def bad_hook():
        raise RuntimeError("Fail")

    ok_hook = MagicMock()
    registry.register_shutdown_hook(bad_hook)
    registry.register_shutdown_hook(ok_hook)

    # Should not raise exception
    registry.shutdown()
    ok_hook.assert_called_once()


def test_register_remote_tools(registry):
    mock_mcp = MagicMock()
    mock_mcp.list_tools.return_value = [
        {
            "name": "remote_tool",
            "server_name": "srv1",
            "original_name": "orig1",
            "description": "desc",
            "parameters": {"type": "object"},
        }
    ]

    names = registry.register_remote_tools(mock_mcp)
    assert names == ["remote_tool"]
    assert "remote_tool" in registry.tools

    # Test execution
    wrapped = registry.tools["remote_tool"]["func"]
    wrapped(val=1, explanation="remote call")
    mock_mcp.call_tool.assert_called_with(
        "srv1", "orig1", {"val": 1, "explanation": "remote call"}
    )


def test_register_remote_tools_error(registry):
    mock_mcp = MagicMock()
    mock_mcp.list_tools.side_effect = Exception("MCP Error")

    with patch("builtins.print") as mock_print:
        names = registry.register_remote_tools(mock_mcp)
        assert names == []
        mock_print.assert_called()


def test_discover_local_tools(registry):
    # Patch the modules in the tool_registry module
    with patch("llm_cli.modules.tool_registry.importlib") as mock_import_mod:
        with patch("llm_cli.modules.tool_registry.pkgutil") as mock_pkgutil_mod:
            mock_pkgutil_mod.iter_modules.return_value = [(None, "tool1", False)]

            registry.discover_local_tools()

            mock_import_mod.import_module.assert_called_with(
                "llm_cli.modules.tools.tool1"
            )
            # Verify that web was NOT called (which would happen if real pkgutil was used)
            for call in mock_import_mod.import_module.call_args_list:
                assert "web" not in call.args[0]


def test_get_tool_schemas(registry):
    registry.register("t1", lambda: 1, "desc1")
    registry.register("t2", lambda: 2, "desc2", supported_providers=["openai"])

    schemas = registry.get_tool_schemas(["t1", "t2", "nonexistent"])
    assert len(schemas) == 2
    assert schemas[0]["name"] == "t1"
    assert schemas[1]["name"] == "t2"

    # Filter by provider
    schemas_anthropic = registry.get_tool_schemas(["t1", "t2"], provider="anthropic")
    assert len(schemas_anthropic) == 1
    assert schemas_anthropic[0]["name"] == "t1"


def test_get_active_names(registry):
    registry.register("t1", lambda: 1, "desc1")
    assert registry.get_active_names(["t1", "t2"]) == ["t1"]


def test_provider_specific_specs(registry):
    registry.register("t1", lambda: 1, "desc1")

    # Gemini
    gemini_spec = registry.get_gemini_spec(["t1"])
    assert "function_declarations" in gemini_spec[0]
    assert gemini_spec[0]["function_declarations"][0]["name"] == "t1"
    assert registry.get_gemini_spec([]) == []

    # Gemini Interaction
    gemini_int_spec = registry.get_gemini_interactions_spec(["t1"])
    assert gemini_int_spec[0]["type"] == "function"
    assert gemini_int_spec[0]["name"] == "t1"

    # OpenAI
    openai_spec = registry.get_openai_spec(["t1"])
    assert openai_spec[0]["type"] == "function"
    assert openai_spec[0]["function"]["name"] == "t1"

    # Anthropic
    anthropic_spec = registry.get_anthropic_spec(["t1"])
    assert anthropic_spec[0]["name"] == "t1"
    assert "input_schema" in anthropic_spec[0]


def test_tool_decorator():
    # Decorator uses the global 'registry' instance by default
    # To test it without messing up the global state too much, we can mock registry in the module
    with patch("llm_cli.modules.tool_registry.registry") as mock_registry:

        @tool_decorator(name="dec_tool", description="dec desc")
        def dec_func():
            pass

        mock_registry.register.assert_called_once()
        args, _ = mock_registry.register.call_args
        assert args[0] == "dec_tool"
        assert args[2] == "dec desc"


def test_tool_decorator_aliases():
    with patch("llm_cli.modules.tool_registry.registry") as mock_registry:

        @tool_decorator(name="alias_tool", desc="alias desc", params={"p": 1})
        def alias_func():
            pass

        _, kwargs = mock_registry.register.call_args
        # Wait, the tool decorator calls register with positional args or mixed
        # Let's check what register received
        call_args = mock_registry.register.call_args
        assert call_args.args[0] == "alias_tool"
        assert call_args.args[2] == "alias desc"
        assert call_args.args[3] == {"p": 1}


def test_tool_decorator_missing_desc():
    with pytest.raises(
        ValueError, match="Either 'description' or 'desc' must be provided"
    ):

        @tool_decorator(name="fail")
        def fail_func():
            pass


def test_exit_code_parsing_failure(registry):
    with patch("llm_cli.modules.tool_registry.log_audit") as mock_log:

        def bad_exit_func():
            return "Exit Code: NotAnInt"

        registry.register("bad_exit", bad_exit_func, "desc")
        registry.tools["bad_exit"]["func"](explanation="test")

        _, kwargs = mock_log.call_args
        assert kwargs["exit_code"] is None
