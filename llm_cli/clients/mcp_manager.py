# llm_cli/clients/mcp_manager.py

import asyncio
import logging
import sys
from contextlib import AsyncExitStack
from typing import Any

from llm_cli.clients.config import config_manager
from llm_cli.mcp_lib import ClientSession, StdioServerParameters, stdio_client
from llm_cli.security.identity import IdentityManager
from llm_cli.ui import console

# Set up logging for MCP client
logging.basicConfig(level=logging.WARN, stream=sys.stderr)
logger = logging.getLogger(__name__)


class MCPManager:
    """Manages connections to multiple MCP servers."""

    def __init__(self) -> None:
        self.servers_config = config_manager.get_mcp_servers()
        self.sessions: dict[str, ClientSession] = {}
        self.exit_stack = AsyncExitStack()

        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

        self._initialized = False
        self._cached_tools: list[dict[str, Any]] = []

    def _run_async(self, coro: Any) -> Any:
        """Helper to run async coroutines in the manager's event loop."""
        if self.loop.is_running():
            # This shouldn't happen in our sync CLI, but for safety:
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
            return future.result()
        return self.loop.run_until_complete(coro)

    def list_tools(self) -> list[dict[str, Any]]:
        """
        Get the list of available tools from all MCP servers.
        If not initialized, initializes servers first.
        Returns a list of tools with namespaced names.
        """
        return self.initialize_servers()

    def initialize_servers(self) -> list[dict[str, Any]]:
        """
        Connect to all configured MCP servers and retrieve their tools.
        Returns a list of tools with namespaced names.
        """
        if self._initialized:
            # Already connected, return cached tools
            return self._cached_tools

        all_remote_tools = []
        if not self.servers_config:
            self._initialized = True
            return []

        for config in self.servers_config:
            name = config.get("name")
            command = config.get("command")
            args = list(config.get("args", []))  # Create a copy to prevent mutation
            env = config.get("env") or {}

            if not name or not command or name in self.sessions:
                continue

            # Identity Propagation: Inject Auth Token only if zero_trust is enabled
            is_zero_trust = config.get("zero_trust", False)

            if is_zero_trust:
                # Identity Propagation: Inject Auth Token into environment
                # Use server name as audience to prevent token reuse
                env["MCP_AUTH_TOKEN"] = IdentityManager.generate_token(
                    audience=name,
                )
                env["MCP_SERVER_NAME"] = name

                # If command is ssh, inject token into the remote command args
                if command == "ssh" or command.endswith("/ssh"):
                    token = env["MCP_AUTH_TOKEN"]
                    server_name_env = f"MCP_SERVER_NAME={name}"

                    # Only inject Token and Server Name.
                    # Keys must be manually registered on the server.
                    env_str = f"MCP_AUTH_TOKEN={token} {server_name_env}"

                    # Strategy 1: Find python command and insert ENV before it
                    inserted = False
                    for i, arg in enumerate(args):
                        if (
                            arg == "python"
                            or arg == "python3"
                            or arg.endswith("/python")
                            or arg.endswith("/python3")
                        ):
                            # Check if already injected
                            if i > 0 and args[i - 1].startswith("MCP_AUTH_TOKEN="):
                                inserted = True
                                break
                            args.insert(i, env_str)
                            inserted = True
                            break

                    # Strategy 2: If python not found, insert after first non-option arg
                    if not inserted:
                        for i, arg in enumerate(args):
                            if not arg.startswith("-"):
                                # Found destination, insert after it if more args
                                if i + 1 < len(args):
                                    if not args[i + 1].startswith("MCP_AUTH_TOKEN="):
                                        args.insert(i + 1, env_str)
                                    inserted = True
                                break

                    # Strategy 3: If still not inserted, try to prepend to last arg
                    if not inserted and args:
                        last_arg = args[-1]
                        if "MCP_AUTH_TOKEN=" not in last_arg:
                            args[-1] = f"{env_str} {last_arg}"
            else:
                # Regular MCP server - just pass configured env if any
                pass

            # Static status message instead of spinner
            console.print(
                f"[bold green]Connecting to MCP server '{name}'...[/bold green]"
            )
            try:
                params = StdioServerParameters(command=command, args=args, env=env)
                tools = self._run_async(self._connect_and_list_tools(name, params))
                all_remote_tools.extend(tools)
                console.print(
                    f"[green][OK] Connected to MCP server '{name}' "
                    f"({len(tools)} tools).[/green]"
                )
            except Exception as e:
                console.print(
                    f"[red][FAIL] Failed to connect to MCP server '{name}': {e}[/red]"
                )

        self._cached_tools = all_remote_tools
        self._initialized = True
        return all_remote_tools

    async def _connect_and_list_tools(
        self, server_name: str, params: StdioServerParameters
    ) -> list[dict[str, Any]]:
        transport_ctx = stdio_client(params)

        try:
            # Use AsyncExitStack to ensure clean teardown of both transport and session
            read, write = await self.exit_stack.enter_async_context(transport_ctx)
            session = ClientSession(read, write)
            await self.exit_stack.enter_async_context(session)

            await asyncio.wait_for(session.initialize(), timeout=10.0)

            self.sessions[server_name] = session
            response = await session.list_tools()

            namespaced_tools = []
            for tool in response.tools:
                namespaced_name = f"{server_name}__{tool.name}"
                namespaced_tools.append(
                    {
                        "name": namespaced_name,
                        "original_name": tool.name,
                        "server_name": server_name,
                        "description": tool.description,
                        "parameters": tool.inputSchema,
                    }
                )

            return namespaced_tools
        except Exception as e:
            # Errors during initialization are handled by the caller.
            # ExitStack will handle partial cleanup if enter_async_context succeeded.
            raise e

    def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any]
    ) -> str:
        """Call a tool on a specific MCP server."""
        session = self.sessions.get(server_name)
        if not session:
            return f"Error: MCP server '{server_name}' not connected."

        try:
            result = self._run_async(session.call_tool(tool_name, arguments))
            output: list[str] = []
            for content in result.content:
                if content.type == "text" and content.text:
                    output.append(str(content.text))
                else:
                    output.append(f"[Binary/Other content: {content.type}]")

            # Bi-directional Verification Support:
            # If the output is a single text block and looks like a signed JSON,
            # return it as is so the executor can verify the signature.
            if len(output) == 1 and output[0].strip().startswith("{"):
                return str(output[0])

            return "\n".join(output) if output else "No output from tool."
        except Exception as e:
            return f"Error calling tool '{tool_name}' on '{server_name}': {e}"

    def shutdown(self) -> None:
        """Close all connections."""
        try:
            if not self.loop.is_closed():
                self._run_async(self.exit_stack.aclose())
        except Exception:
            pass
        finally:
            self.sessions.clear()
            if not self.loop.is_closed():
                self.loop.close()


# Global manager instance
mcp_manager = MCPManager()
