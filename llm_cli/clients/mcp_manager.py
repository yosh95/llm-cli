# llm_cli/clients/mcp_manager.py

import asyncio
import logging
import sys
from typing import Any, Dict, List

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from rich.console import Console

from llm_cli.clients.config import get_mcp_servers
from llm_cli.security import CommandValidationError, validate_mcp_command

# Set up logging for MCP client
logging.basicConfig(level=logging.WARN, stream=sys.stderr)
logger = logging.getLogger(__name__)
console = Console()


class MCPManager:
    """Manages connections to multiple MCP servers."""

    def __init__(self):
        self.servers_config = get_mcp_servers()
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack: Dict[str, Any] = {}
        self.loop = asyncio.new_event_loop()
        self._initialized = False
        self._cached_tools: List[Dict[str, Any]] = []

    def _run_async(self, coro):
        """Helper to run async coroutines in the manager's event loop."""
        return self.loop.run_until_complete(coro)

    def list_tools(self) -> List[Dict[str, Any]]:
        """
        Get the list of available tools from all MCP servers.
        If not initialized, initializes servers first.
        Returns a list of tools with namespaced names.
        """
        return self.initialize_servers()

    def initialize_servers(self) -> List[Dict[str, Any]]:
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
            args = config.get("args", [])
            env = config.get("env")

            if not name or not command or name in self.sessions:
                continue

            # Validate MCP server command against security whitelist
            try:
                validate_mcp_command(command)
            except CommandValidationError as e:
                console.print(
                    f"[bold red]Security Error for MCP server '{name}':[/bold red] {e}"
                )
                console.print(
                    "[yellow]Skipping this MCP server. Check the allowed "
                    "MCP commands in your config file "
                    "(~/.config/llm_cli/config.toml)[/yellow]"
                )
                continue

            # Static status message instead of spinner
            console.print(f"[bold green]Connecting to MCP server '{name}'...[/bold green]")
            try:
                params = StdioServerParameters(command=command, args=args, env=env)
                    tools = self._run_async(self._connect_and_list_tools(name, params))
                    all_remote_tools.extend(tools)
                    console.print(
                        f"[green]✓ Connected to MCP server '{name}' "
                        f"({len(tools)} tools).[/green]"
                    )
                except Exception as e:
                    console.print(
                        f"[red]✗ Failed to connect to MCP server '{name}': {e}[/red]"
                    )

        self._cached_tools = all_remote_tools
        self._initialized = True
        return all_remote_tools

    async def _connect_and_list_tools(
        self, server_name: str, params: StdioServerParameters
    ):
        transport_ctx = stdio_client(params)

        try:
            read, write = await asyncio.wait_for(
                transport_ctx.__aenter__(), timeout=15.0
            )
            session = ClientSession(read, write)
            await session.__aenter__()
            await asyncio.wait_for(session.initialize(), timeout=10.0)

            self.sessions[server_name] = session
            self.exit_stack[server_name] = (transport_ctx, session)

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
        except asyncio.TimeoutError:
            raise Exception("Connection timed out.")
        except Exception as e:
            await transport_ctx.__aexit__(None, None, None)
            raise e

    def call_tool(
        self, server_name: str, tool_name: str, arguments: Dict[str, Any]
    ) -> str:
        """Call a tool on a specific MCP server."""
        session = self.sessions.get(server_name)
        if not session:
            return f"Error: MCP server '{server_name}' not connected."

        try:
            result = self._run_async(session.call_tool(tool_name, arguments))
            output = []
            for content in result.content:
                if content.type == "text":
                    output.append(content.text)
                else:
                    output.append(f"[Binary/Other content: {content.type}]")
            return "\n".join(output) if output else "No output from tool."
        except Exception as e:
            return f"Error calling tool '{tool_name}' on '{server_name}': {e}"

    def shutdown(self):
        """Close all connections."""
        for server_name, (transport_ctx, session) in self.exit_stack.items():
            try:
                self._run_async(session.__aexit__(None, None, None))
                self._run_async(transport_ctx.__aexit__(None, None, None))
            except Exception:
                pass
        self.loop.close()


# Global manager instance
mcp_manager = MCPManager()
