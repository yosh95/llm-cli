import pytest

from llm_cli.modules.tool_registry import ToolRegistry


@pytest.fixture
def mock_registry():
    """Create a fresh ToolRegistry for each test."""
    reg = ToolRegistry()

    # Register some dummy tools
    def dummy_func(**kwargs):
        return "success"

    reg.register(
        name="brave_search",
        func=dummy_func,
        description="Search using Brave",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )

    reg.register(
        name="other_tool",
        func=dummy_func,
        description="Another tool",
        parameters={"type": "object", "properties": {"arg": {"type": "string"}}},
    )

    return reg


def test_gemini_search_exclusivity(mock_registry):
    # Case 1: brave_search is NOT requested
    spec_no_brave = mock_registry.get_gemini_spec(["other_tool"])
    has_google_search = any("google_search" in s for s in spec_no_brave)
    assert has_google_search is True

    # Case 2: brave_search IS requested
    spec_with_brave = mock_registry.get_gemini_spec(["brave_search", "other_tool"])
    has_google_search = any("google_search" in s for s in spec_with_brave)
    assert has_google_search is False

    # Verify brave_search is still in function_declarations
    functions = []
    for s in spec_with_brave:
        if "function_declarations" in s:
            functions.extend([d["name"] for d in s["function_declarations"]])
    assert "brave_search" in functions


def test_openai_search_exclusivity(mock_registry):
    # Case 1: brave_search is NOT requested
    spec_no_brave = mock_registry.get_openai_spec(["other_tool"], provider="openai")
    has_native_search = any(s.get("type") == "web_search" for s in spec_no_brave)
    assert has_native_search is True

    # Case 2: brave_search IS requested
    spec_with_brave = mock_registry.get_openai_spec(
        ["brave_search", "other_tool"], provider="openai"
    )
    has_native_search = any(s.get("type") == "web_search" for s in spec_with_brave)
    assert has_native_search is False

    # Verify brave_search is still there
    tool_names = [s.get("name") for s in spec_with_brave if s.get("type") == "function"]
    assert "brave_search" in tool_names


def test_anthropic_search_exclusivity(mock_registry):
    # Case 1: brave_search is NOT requested
    spec_no_brave = mock_registry.get_anthropic_spec(["other_tool"])
    has_native_search = any(s.get("type") == "web_search_20260209" for s in spec_no_brave)
    assert has_native_search is True

    # Case 2: brave_search IS requested
    spec_with_brave = mock_registry.get_anthropic_spec(["brave_search", "other_tool"])
    has_native_search = any(s.get("type") == "web_search_20260209" for s in spec_with_brave)
    assert has_native_search is False

    # Verify brave_search is still there
    tool_names = [s.get("name") for s in spec_with_brave if s.get("name") is not None]
    assert "brave_search" in tool_names


def test_ollama_no_native_search(mock_registry):
    # Ollama (openai provider but not responses api) should not have native web_search anyway
    spec = mock_registry.get_openai_spec(["other_tool"], provider="ollama")
    has_native_search = any(s.get("type") == "web_search" for s in spec)
    assert has_native_search is False
