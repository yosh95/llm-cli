# llm_cli/modules/tool_registry.py

import asyncio
import functools
import importlib
import inspect
import pkgutil
from collections.abc import Callable
from typing import Any

from llm_cli.security.audit import log_audit


class ToolRegistry:
    """
    Registry for managing local and remote (MCP) tools.

    This registry handles tool discovery, registration, and generating
    provider-specific tool specifications (OpenAI, Gemini, Anthropic).
    """

    def __init__(self) -> None:
        self.tools: dict[str, dict[str, Any]] = {}
        self.shutdown_hooks: list[Callable[[], Any]] = []

    def register_shutdown_hook(self, func: Callable[[], Any]) -> None:
        """Registers a function to be called when the application exits."""
        if func not in self.shutdown_hooks:
            self.shutdown_hooks.append(func)

    def shutdown(self) -> None:
        """Executes all registered shutdown hooks."""
        for hook in self.shutdown_hooks:
            try:
                if inspect.iscoroutinefunction(hook):
                    try:
                        # If there is already a running event loop (e.g. inside an
                        # async context), schedule the coroutine on it and block
                        # until it completes.
                        loop = asyncio.get_running_loop()
                        future = asyncio.run_coroutine_threadsafe(hook(), loop)
                        future.result(timeout=10)
                    except RuntimeError:
                        # No running loop — start a fresh one with asyncio.run().
                        # This replaces the deprecated asyncio.get_event_loop()
                        # pattern that raises DeprecationWarning in Python ≥ 3.10.
                        asyncio.run(hook())
                else:
                    hook()
            except Exception:
                pass

    def register(
        self,
        name: str,
        func: Callable[..., Any],
        description: str,
        parameters: dict[str, Any] | None = None,
        supported_providers: list[str] | None = None,
        interactive: bool = False,
        validate: Callable[..., str | bool] | None = None,
        is_local: bool = True,
    ) -> None:
        """
        Registers a tool in the registry.

        Args:
            name: The name of the tool (used by LLMs).
            func: The Python function to execute.
            description: A clear description of what the tool does.
            parameters: JSON Schema of the function parameters.
            supported_providers: List of providers that support this tool.
            interactive: Whether the tool requires interactive input.
            validate: Optional function to validate arguments BEFORE approval.
                     Should return True if valid, or a string error message if invalid.
            is_local: Whether this is a local system tool (protected).
        """
        # Security: Prevent remote tools from overriding local system tools
        if name in self.tools and self.tools[name].get("is_local", False):
            if not is_local:
                # Log a warning (the caller will handle the error)
                from llm_cli.ui import report_warning

                report_warning(
                    f"Security: Blocking attempt by remote server to override local tool '{name}'."
                )
                return

        # Initialize parameters following JSON Schema standard
        if parameters is None:
            parameters = {"type": "object", "properties": {}, "required": []}

        if "properties" not in parameters:
            parameters["properties"] = {}

        # Define 'explanation' parameter
        explanation_spec = {
            "type": "string",
            "description": (
                "A detailed explanation of why this tool is needed and what it will "
                "do, providing context for the user to approve the action."
            ),
        }

        # Order properties:
        # 1. Primary identifier (path, directory, or url) if it exists
        # 2. All other parameters in their original order (respecting developer intent)
        # 3. 'explanation' at the very end (as a mandatory system-injected field)
        ordered_properties = {}
        # Use a shallow copy so that pop() below does not mutate the caller's dict.
        original_props = dict(parameters["properties"])

        # 1. Move primary identifiers to front
        for identifier in ["path", "directory", "url"]:
            if identifier in original_props:
                ordered_properties[identifier] = original_props.pop(identifier)

        # 2. Add remaining original properties (respecting their defined order)
        for k in list(original_props.keys()):
            if k != "explanation":
                ordered_properties[k] = original_props.pop(k)

        # 3. Add explanation at the end
        ordered_properties["explanation"] = explanation_spec

        parameters["properties"] = ordered_properties

        if "required" not in parameters:
            parameters["required"] = []
        if "explanation" not in parameters["required"]:
            parameters["required"] = parameters["required"] + ["explanation"]

        @functools.wraps(func)
        def wrapper(**kwargs: Any) -> Any:
            # Extract explanation for logging (internal audit)
            _ = kwargs.get("explanation", "No explanation provided.")
            audit_model = kwargs.pop("__audit_model__", "-")
            security_reqs = kwargs.pop("__security_requirements__", None)

            # Filter kwargs to match the wrapped function's signature
            sig = inspect.signature(func)
            filtered_kwargs = {
                k: v
                for k, v in kwargs.items()
                if k in sig.parameters
                or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
            }

            # Inject system fields if the function (or decorator) accepts them.
            # We use follow_wrapped=False because decorators like @file_tool_handler
            # use functools.wraps, which obscures their ability to accept **kwargs.
            if security_reqs is not None:
                actual_sig = inspect.signature(func, follow_wrapped=False)
                if "__security_requirements__" in actual_sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD for p in actual_sig.parameters.values()
                ):
                    filtered_kwargs["__security_requirements__"] = security_reqs

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
                    _output=result,
                    exit_code=exit_code,
                    error=None,
                    context={"model": audit_model},
                )
                return result
            except Exception as e:
                log_audit(
                    tool_name=name,
                    args=kwargs,
                    _output="",
                    error=str(e),
                    context={"model": audit_model},
                )
                raise e

        self.tools[name] = {
            "name": name,
            "func": wrapper,
            "description": description,
            "parameters": parameters,
            "supported_providers": supported_providers,
            "interactive": interactive,
            "validate": validate,
            "is_local": is_local,
        }

    def register_remote_tools(self, mcp_manager: Any) -> list[str]:
        from llm_cli.ui import report_warning

        remote_names = []
        # Register shutdown hook for MCP manager
        self.register_shutdown_hook(mcp_manager.shutdown)
        try:
            for tool in mcp_manager.list_tools():

                def make_tool_func(server_name: str, original_name: str) -> Callable[..., Any]:
                    return lambda **kwargs: mcp_manager.call_tool(
                        server_name, original_name, kwargs
                    )

                self.register(
                    name=tool["name"],
                    func=make_tool_func(tool["server_name"], tool["original_name"]),
                    description=tool["description"],
                    parameters=tool["parameters"],
                    is_local=False,  # Mark as remote tool
                )
                remote_names.append(tool["name"])
        except Exception as e:
            report_warning(f"Failed to register remote tools: {e}")
            log_audit("remote_tools_register", {}, None, error=str(e))  # Fallback log
        return remote_names

    def discover_local_tools(self) -> None:
        import llm_cli.modules.tools as tools_pkg

        for _, name, _ in pkgutil.iter_modules(tools_pkg.__path__):
            importlib.import_module(f"llm_cli.modules.tools.{name}")

    def get_tool_schemas(
        self, active_tools: list[str], provider: str | None = None
    ) -> list[dict[str, Any]]:
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

    def get_active_names(self, names: list[str], provider: str | None = None) -> list[str]:
        return [t["name"] for t in self._get_active(names, provider=provider)]

    def _get_active(self, names: list[str], provider: str | None = None) -> list[dict[str, Any]]:
        active = []
        for n in names:
            if n in self.tools:
                t = self.tools[n]
                if provider and t.get("supported_providers"):
                    if provider not in t["supported_providers"]:
                        continue
                active.append(t)
        return active

    def get_gemini_spec(self, names: list[str], provider: str = "google") -> list[dict[str, Any]]:
        active_names = self.get_active_names(names, provider=provider)
        spec: list[dict[str, Any]] = []

        # 1. Native Google Search tool (Grounding with Google Search)
        # Exclusive: Disable native search if a local search tool (brave_search) is active
        if "brave_search" not in active_names:
            spec.append({"google_search": {}})

        # 2. Local function declarations
        functions = [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            }
            for t in self._get_active(names, provider=provider)
        ]
        if functions:
            spec.append({"function_declarations": functions})
        return spec

    def get_openai_spec(self, names: list[str], provider: str = "openai") -> list[dict[str, Any]]:
        active_names = self.get_active_names(names, provider=provider)
        is_responses_api = provider == "openai"
        spec = []

        for t in self._get_active(names, provider=provider):
            if is_responses_api:
                # Responses API (/v1/responses) used by OpenAI
                # uses a flat structure for function tools.
                spec.append(
                    {
                        "type": "function",
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    }
                )
            else:
                # Standard Chat Completions API (e.g. Ollama)
                spec.append(
                    {
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t["description"],
                            "parameters": t["parameters"],
                        },
                    }
                )

        # OpenAI uses Responses API with native web_search support
        if is_responses_api:
            # Note: OpenAI's Responses API fails if 'name' is provided for web_search.
            # Exclusive: Disable native search if a local search tool (brave_search) is active
            if "brave_search" not in active_names:
                spec.append({"type": "web_search"})
        return spec

    def get_anthropic_spec(
        self, names: list[str], provider: str = "anthropic"
    ) -> list[dict[str, Any]]:
        active_names = self.get_active_names(names, provider=provider)
        spec: list[dict[str, Any]] = []

        # Native Anthropic Web Search tool (using latest 20260209 version)
        # Exclusive: Disable native search if a local search tool (brave_search) is active
        if "brave_search" not in active_names:
            spec.append(
                {
                    "type": "web_search_20260209",
                    "name": "web_search",
                }
            )

        # Local tools
        for t in self._get_active(names, provider=provider):
            spec.append(
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"],
                }
            )
        return spec


registry = ToolRegistry()


def tool(
    name: str,
    description: str | None = None,
    parameters: dict[str, Any] | None = None,
    supported_providers: list[str] | None = None,
    desc: str | None = None,
    params: dict[str, Any] | None = None,
    interactive: bool = False,
    validate: Callable[..., str | bool] | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    final_desc = description or desc
    final_params = parameters or params

    if not final_desc:
        raise ValueError("Either 'description' or 'desc' must be provided")

    def decorator(f: Callable[..., Any]) -> Callable[..., Any]:
        registry.register(
            name,
            f,
            final_desc,  # type: ignore[arg-type]
            final_params,
            supported_providers,
            interactive,
            validate,
        )
        return f

    return decorator


registry.discover_local_tools()
