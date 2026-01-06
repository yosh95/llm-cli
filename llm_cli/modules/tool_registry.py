# llm_cli/modules/tool_registry.py

import functools
import importlib
import inspect
import pkgutil
from typing import Any, Callable, Dict, List, Optional

from llm_cli.security.audit import log_audit


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        name: str,
        func: Callable,
        description: str,
        parameters: Optional[Dict[str, Any]] = None,
        supported_providers: Optional[List[str]] = None,
    ):
        # 1. Initialize parameters
        if parameters is None:
            parameters = {"type": "object", "properties": {}, "required": []}

        if "properties" not in parameters:
            parameters["properties"] = {}

        # 2. Force inject 'thought' parameter
        parameters["properties"]["thought"] = {
            "type": "string",
            "description": (
                "The reasoning behind calling this tool. Why is this necessary now?"
            ),
        }

        if "required" not in parameters:
            parameters["required"] = []
        if "thought" not in parameters["required"]:
            parameters["required"].append("thought")

        # 3. Wrap the function with Auditing and Parameter Filtering
        @functools.wraps(func)
        def wrapper(**kwargs):
            # Extract thought for logging
            # (kwargs will be logged in log_audit)
            _ = kwargs.get("thought", "No reasoning provided.")

            sig = inspect.signature(func)
            filtered_kwargs = {
                k: v
                for k, v in kwargs.items()
                if k in sig.parameters
                or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
            }

            try:
                result = func(**filtered_kwargs)

                # Automatically log ALL tool calls for auditing
                # Special handling for tools that return more detailed status
                exit_code = None
                error_str = None

                if isinstance(result, str) and "Exit Code:" in result:
                    try:
                        exit_code = int(result.split("Exit Code:")[-1].strip())
                    except Exception:
                        pass

                log_audit(
                    tool_name=name,
                    args=kwargs,  # Log original args including thought
                    output=result,
                    exit_code=exit_code,
                    error=error_str,
                )
                return result
            except Exception as e:
                log_audit(tool_name=name, args=kwargs, output="", error=str(e))
                raise e

        self.tools[name] = {
            "name": name,
            "func": wrapper,
            "description": description,
            "parameters": parameters,
            "supported_providers": supported_providers,
        }

    def register_remote_tools(self, mcp_manager) -> List[str]:
        remote_names = []
        for tool in mcp_manager.list_tools():

            def make_tool_func(server_name, original_name):
                return lambda **kwargs: mcp_manager.call_tool(
                    server_name, original_name, kwargs
                )

            self.register(
                name=tool["name"],
                func=make_tool_func(tool["server_name"], tool["original_name"]),
                description=tool["description"],
                parameters=tool["parameters"],
            )
            remote_names.append(tool["name"])
        return remote_names

    def discover_local_tools(self):
        import llm_cli.modules.tools as tools_pkg

        for _, name, _ in pkgutil.iter_modules(tools_pkg.__path__):
            importlib.import_module(f"llm_cli.modules.tools.{name}")

    def get_tool_schemas(
        self, active_tools: List[str], provider: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        schemas = []
        for t in self._get_active(active_tools, provider=provider):
            schemas.append(
                {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                }
            )
        return schemas

    def get_active_names(
        self, names: List[str], provider: Optional[str] = None
    ) -> List[str]:
        """
        Returns a list of tool names that are both in the 'names' list
        and supported by the given provider.
        """
        return [t["name"] for t in self._get_active(names, provider=provider)]

    def _get_active(
        self, names: List[str], provider: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        active = []
        for n in names:
            if n in self.tools:
                t = self.tools[n]
                if provider and t.get("supported_providers"):
                    if provider not in t["supported_providers"]:
                        continue
                active.append(t)
        return active

    def get_gemini_spec(
        self, names: List[str], provider: str = "google"
    ) -> List[Dict[str, Any]]:
        tools = [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in self._get_active(names, provider=provider)
        ]
        return [{"function_declarations": tools}] if tools else []

    def get_openai_spec(
        self, names: List[str], provider: str = "openai"
    ) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
            for t in self._get_active(names, provider=provider)
        ]

    def get_anthropic_spec(
        self, names: List[str], provider: str = "anthropic"
    ) -> List[Dict[str, Any]]:
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"],
            }
            for t in self._get_active(names, provider=provider)
        ]


registry = ToolRegistry()


def tool(
    name: str,
    description: Optional[str] = None,
    parameters: Optional[Dict] = None,
    supported_providers: Optional[List[str]] = None,
    desc: Optional[str] = None,
    params: Optional[Dict] = None,
):
    """
    Decorator to register a function as a tool.
    Supports both old (description, parameters) and new (desc, params) names.
    """
    final_desc = description or desc
    final_params = parameters or params

    if not final_desc:
        raise ValueError("Either 'description' or 'desc' must be provided")

    def decorator(f: Callable):
        registry.register(name, f, final_desc, final_params, supported_providers)
        return f

    return decorator


# Automatically discover and register local tools when module is imported
registry.discover_local_tools()
