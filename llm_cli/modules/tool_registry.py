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
            self.register(
                name=tool.name,
                func=lambda **kwargs: mcp_manager.call_tool(
                    tool.name, kwargs
                ),
                description=tool.description,
                parameters=tool.input_schema
            )
            remote_names.append(tool.name)
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


def tool(name: str, desc: str, params: Optional[Dict] = None):
    def decorator(f: Callable):
        registry.register(name, f, desc, params)
        return f

    return decorator
