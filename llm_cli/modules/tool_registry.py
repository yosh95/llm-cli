# llm_cli/modules/tool_registry.py

import importlib
import pkgutil
from typing import Any, Dict, List, Callable

# Global list to hold tool definitions collected via decorators
_DECORATED_TOOLS: List[Dict[str, Any]] = []

def tool(name: str, description: str, parameters: Dict[str, Any]):
    """
    Decorator to register a function as an LLM tool.
    """
    def decorator(func: Callable):
        _DECORATED_TOOLS.append({
            "name": name,
            "description": description,
            "parameters": parameters,
            "func": func
        })
        return func
    return decorator


class ToolRegistry:
    """Central registry for tools with exporters for LLM providers."""

    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._load_plugins()

    def _load_plugins(self):
        """
        Dynamically load all modules in the 'tools' sub-package 
        to trigger tool registrations.
        """
        import llm_cli.modules.tools as tools_pkg
        for _, name, _ in pkgutil.iter_modules(tools_pkg.__path__):
            full_module_name = f"llm_cli.modules.tools.{name}"
            importlib.import_with_cache(full_module_name) if hasattr(importlib, 'import_with_cache') else importlib.import_module(full_module_name)
        
        # After importing all modules, populate the tools dictionary
        for t in _DECORATED_TOOLS:
            self.register(t["name"], t["description"], t["parameters"], t["func"])

    def register(
        self, name: str, description: str,
        parameters: Dict[str, Any], func: Callable
    ):
        self.tools[name] = {
            "name": name, "description": description,
            "parameters": parameters, "func": func
        }

    def register_remote_tools(self, mcp_manager):
        """Register tools from MCP servers."""
        remote_tools = mcp_manager.initialize_servers()
        for t in remote_tools:
            srv, orig = t["server_name"], t["original_name"]
            self.register(
                t["name"], t["description"], t["parameters"],
                lambda s=srv, o=orig, **kw: mcp_manager.call_tool(s, o, kw)
            )
        return [t["name"] for t in remote_tools]

    def _get_active(self, names: List[str]):
        return [self.tools[n] for n in names if n in self.tools]

    def get_gemini_spec(self, names: List[str]):
        tools = [
            {"name": t["name"], "description": t["description"],
             "parameters": t["parameters"]}
            for t in self._get_active(names)
        ]
        return [{"function_declarations": tools}] if tools else []

    def get_openai_spec(self, names: List[str]):
        return [
            {"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["parameters"]}}
            for t in self._get_active(names)
        ]

    def get_anthropic_spec(self, names: List[str]):
        return [
            {"name": t["name"], "description": t["description"],
             "input_schema": t["parameters"]}
            for t in self._get_active(names)
        ]


# Singleton instance
registry = ToolRegistry()
