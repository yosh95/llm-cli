from llm_cli.modules.tool_registry import registry, tool


def test_registry_auto_injects_explanation():
    """Verify that the tool registry always injects the 'explanation' parameter."""

    @tool(
        name="test_tool_no_explanation",
        desc="A test tool",
        params={
            "type": "object",
            "properties": {"arg1": {"type": "string"}},
            "required": ["arg1"],
        },
    )
    def test_func(arg1: str, explanation: str = ""):
        return f"{arg1}: {explanation}"

    # Get the registered tool metadata
    tool_meta = registry.tools["test_tool_no_explanation"]
    params = tool_meta["parameters"]

    assert "explanation" in params["properties"]
    assert "explanation" in params["required"]
    assert params["properties"]["explanation"]["type"] == "string"


def test_provider_specs_generation():
    """Verify that provider-specific specifications are correctly generated."""

    # We'll use a few existing tools or create test ones
    test_names = ["search_files", "read_file_content"]

    # 1. OpenAI Spec
    openai_spec = registry.get_openai_spec(test_names)
    for spec in openai_spec:
        assert spec["type"] == "function"
        assert "function" in spec
        assert spec["function"]["name"] in test_names
        assert "parameters" in spec["function"]
        assert "explanation" in spec["function"]["parameters"]["properties"]

    # 2. Anthropic Spec
    anthropic_spec = registry.get_anthropic_spec(test_names)
    for spec in anthropic_spec:
        assert spec["name"] in test_names
        assert "input_schema" in spec
        assert "explanation" in spec["input_schema"]["properties"]

    # 3. Gemini Spec
    gemini_spec = registry.get_gemini_spec(test_names)
    # Gemini spec format is a bit unique: list of dicts with function_declarations
    found_tools = []
    for s in gemini_spec:
        for decl in s["function_declarations"]:
            found_tools.append(decl["name"])
            assert "explanation" in decl["parameters"]["properties"]

    for name in test_names:
        assert name in found_tools


def test_tool_discovery():
    """Verify that local tools are correctly discovered and registered."""
    # This assumes the tool registry has already run discover_local_tools()
    # Which is done at the end of tool_registry.py

    expected_tools = [
        "search_files",
        "list_files_in_directory",
        "read_file_content",
        "edit_file",
    ]
    for tool_name in expected_tools:
        assert tool_name in registry.tools, f"Tool {tool_name} was not discovered."


def test_tool_wrapper_audit_logging():
    """Test that the tool wrapper correctly filters arguments and handles logging."""
    from unittest.mock import patch

    @tool(
        name="test_audit_tool",
        desc="Audit test",
        params={"type": "object", "properties": {"a": {"type": "integer"}}},
    )
    def simple_func(a: int):
        return a * 2

    # Patch log_audit to verify it's called
    with patch("llm_cli.modules.tool_registry.log_audit") as mock_audit:
        # Call via registry
        wrapper_func = registry.tools["test_audit_tool"]["func"]
        result = wrapper_func(a=5, explanation="Testing audit", __audit_model__="gpt-4")

        assert result == 10
        mock_audit.assert_called_once()
        args_in_audit = mock_audit.call_args[1]["args"]
        assert args_in_audit["a"] == 5
        assert args_in_audit["explanation"] == "Testing audit"
        assert mock_audit.call_args[1]["context"]["model"] == "gpt-4"
