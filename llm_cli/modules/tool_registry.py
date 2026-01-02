# llm_cli/modules/tool_registry.py

import importlib
import pkgutil
from typing import Any, Callable, Dict, List, Optional


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: str,
        func: Callable,
        description: str,
        parameters: Optional[Dict[str, Any]] = None
    ):
        self.tools[name] = {
            "name": name,
            "func": func,
            "description": description,
            "parameters": parameters or {"type": "object", "properties": {}}
        }

    def register_remote_tools(self, mcp_manager) -> List[str]:
        remote_names = []
        for tool in mcp_manager.list_tools():
            # Create a closure to capture the current values
            def make_tool_func(server_name, original_name):
                return lambda **kwargs: mcp_manager.call_tool(
                    server_name, original_name, kwargs
                )

            self.register(
                name=tool["name"],
                func=make_tool_func(tool["server_name"], tool["original_name"]),
                description=tool["description"],
                parameters=tool["parameters"]
            )
            remote_names.append(tool["name"])
        return remote_names

    def discover_local_tools(self):
        import llm_cli.modules.tools as tools_pkg
        for _, name, _ in pkgutil.iter_modules(tools_pkg.__path__):
            importlib.import_module(f"llm_cli.modules.tools.{name}")

    def get_tool_schemas(self,
                         active_tools: List[str]) -> List[Dict[str, Any]]:
        schemas = []
        for name in active_tools:
            if name in self.tools:
                t = self.tools[name]
                schemas.append({
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"]
                })
        return schemas


registry = ToolRegistry()


def tool(name: str,
         description: Optional[str] = None,
         parameters: Optional[Dict] = None,
         desc: Optional[str] = None,
         params: Optional[Dict] = None):
    """
    Decorator to register a function as a tool.
    Supports both old (description, parameters) and new (desc, params) names.
    """
    # Support both old and new parameter names
    final_desc = description or desc
    final_params = parameters or params

    if not final_desc:
        raise ValueError("Either 'description' or 'desc' must be provided")

    def decorator(f: Callable):
        registry.register(name, f, final_desc, final_params)
        return f

    return decorator


# Automatically discover and register local tools when module is imported
registry.discover_local_tools()
