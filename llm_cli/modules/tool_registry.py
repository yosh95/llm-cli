# llm_cli/modules/tool_registry.py

import asyncio
import functools
import importlib
import inspect
import pkgutil
from typing import Any, Callable, Dict, List, Optional

from llm_cli.security.audit import log_audit


class ToolRegistry:
    """
    Registry for managing local and remote (MCP) tools.

    This registry handles tool discovery, registration, and generating
    provider-specific tool specifications (OpenAI, Gemini, Anthropic).
    """

    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.shutdown_hooks: List[Callable] = []

    def register_shutdown_hook(self, func: Callable):
        """Registers a function to be called when the application exits."""
        if func not in self.shutdown_hooks:
            self.shutdown_hooks.append(func)

    def shutdown(self):
        """Executes all registered shutdown hooks."""
        for hook in self.shutdown_hooks:
            try:
                if inspect.iscoroutinefunction(hook):
                    asyncio.get_event_loop().run_until_complete(hook())
                else:
                    hook()
            except Exception:
                pass

    def register(
        self,
        name: str,
        func: Callable,
        description: str,
        parameters: Optional[Dict[str, Any]] = None,
        supported_providers: Optional[List[str]] = None,
        interactive: bool = False,
        skip_approval: bool = False,
    ):
        """
        Registers a tool in the registry.

        Args:
            name: The name of the tool (used by LLMs).
            func: The Python function to execute.
            description: A clear description of what the tool does.
            parameters: JSON Schema of the function parameters.
            supported_providers: List of providers that support this tool.
            interactive: Whether the tool requires interactive input.
            skip_approval: Whether to skip user approval before execution.
        """
        # Initialize parameters following JSON Schema standard
        if parameters is None:
            parameters = {"type": "object", "properties": {}, "required": []}

        if "properties" not in parameters:
            parameters["properties"] = {}

        # Force inject 'explanation' parameter to encourage LLMs to explain
        # their actions
        parameters["properties"]["explanation"] = {
            "type": "string",
            "description": (
                "A detailed explanation of why this tool is needed and what it will "
                "do, providing context for the user to approve the action."
            ),
        }

        if "required" not in parameters:
            parameters["required"] = []
        if "explanation" not in parameters["required"]:
            parameters["required"].append("explanation")

        @functools.wraps(func)
        def wrapper(**kwargs):
            # Extract explanation for logging (internal audit)
            _ = kwargs.get("explanation", "No explanation provided.")

            # Filter kwargs to match the wrapped function's signature
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

                # Parse exit code if present in the string result (common for CLI tools)
                exit_code = None
                if isinstance(result, str) and "Exit Code:" in result:
                    try:
                        exit_code = int(result.split("Exit Code:")[-1].strip())
                    except Exception:
                        pass

                log_audit(
                    tool_name=name,
                    args=kwargs,
                    output=result,
                    exit_code=exit_code,
                    error=None,
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
            "interactive": interactive,
            "skip_approval": skip_approval,
        }

    def register_remote_tools(self, mcp_manager) -> List[str]:
        remote_names = []
        try:
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
        except Exception as e:
            print(f"Warning: Failed to register remote tools: {e}")
            log_audit("remote_tools_register", {}, None, error=str(e))  # Fallback log
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
    interactive: bool = False,
    skip_approval: bool = False,
):
    final_desc = description or desc
    final_params = parameters or params

    if not final_desc:
        raise ValueError("Either 'description' or 'desc' must be provided")

    def decorator(f: Callable):
        registry.register(
            name,
            f,
            final_desc,
            final_params,
            supported_providers,
            interactive,
            skip_approval,
        )
        return f

    return decorator


registry.discover_local_tools()
