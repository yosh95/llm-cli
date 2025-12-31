# llm_cli/clients/mcp_manager.py

import asyncio
import logging
import sys
from typing import Dict, List, Any, Optional
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from llm_cli.clients.config import get_mcp_servers

# Set up logging for MCP client
logging.basicConfig(level=logging.WARN, stream=sys.stderr)
logger = logging.getLogger(__name__)

class MCPManager:
    """Manages connections to multiple MCP servers."""

    def __init__(self):
        self.servers_config = get_mcp_servers()
        self.sessions: Dict[str, ClientSession] = {}
        self.exit_stack: Dict[str, Any] = {}
        self.loop = asyncio.new_event_loop()

    def _run_async(self, coro):
        """Helper to run async coroutines in the manager's event loop."""
        return self.loop.run_until_complete(coro)

    def initialize_servers(self) -> List[Dict[str, Any]]:
        """
        Connect to all configured MCP servers and retrieve their tools.
        Returns a list of tools with namespaced names.
        """
        all_remote_tools = []
        for config in self.servers_config:
            name = config.get("name")
            command = config.get("command")
            args = config.get("args", [])
            env = config.get("env")

            if not name or not command:
                continue

            try:
                # We use a context manager pattern but manually manage it
                # to keep sessions alive.
                params = StdioServerParameters(command=command, args=args, env=env)
                
                # stdio_client is an async context manager
                # We'll initialize it and keep the session
                tools = self._run_async(self._connect_and_list_tools(name, params))
                all_remote_tools.extend(tools)
                logger.info(f"Connected to MCP server '{name}'")
            except Exception as e:
                logger.error(f"Failed to connect to MCP server '{name}': {e}")

        return all_remote_tools

    async def _connect_and_list_tools(self, server_name: str, params: StdioServerParameters):
        # This is a bit tricky because we want to keep the connection open.
        # For now, we'll open, list, and then we need a way to keep it alive
        # for calls.
        
        # In a real sync-to-async bridge for a CLI, 
        # we might keep the transport open.
        
        # Temporary implementation: we'll use a simplified persistent connection
        # if the SDK supports it easily, or re-open for each call (less efficient).
        # Better: let's store the context manager and session.
        
        transport_ctx = stdio_client(params)
        read, write = await transport_ctx.__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        
        self.sessions[server_name] = session
        self.exit_stack[server_name] = (transport_ctx, session)
        
        response = await session.list_tools()
        
        namespaced_tools = []
        for tool in response.tools:
            # Prefix tool name to avoid collisions
            original_name = tool.name
            namespaced_name = f"{server_name}__{original_name}"
            
            namespaced_tools.append({
                "name": namespaced_name,
                "original_name": original_name,
                "server_name": server_name,
                "description": tool.description,
                "parameters": tool.inputSchema
            })
            
        return namespaced_tools

    def call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call a tool on a specific MCP server."""
        session = self.sessions.get(server_name)
        if not session:
            return f"Error: MCP server '{server_name}' not connected."

        try:
            result = self._run_async(session.call_tool(tool_name, arguments))
            
            # Combine text content from the result
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
            except:
                pass
        self.loop.close()

# Global manager instance
mcp_manager = MCPManager()
