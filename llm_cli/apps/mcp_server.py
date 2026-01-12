# llm_cli/apps/mcp_server.py

import logging
import sys

from mcp.server.fastmcp import FastMCP

from llm_cli.modules.tool_registry import registry

# Configure logging to stderr because stdout is used for MCP JSON-RPC
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)


def create_mcp_server():
    """Create and configure the FastMCP server instance."""
    mcp = FastMCP("llm-cli-remote")

    # Register all tools from the tool registry
    for name, tool_def in registry.tools.items():
        # FastMCP.tool() uses the function's name, docstring, and type hints.
        # Since our tools are already designed for LLM consumption,
        # they should map well.
        logger.info(f"Registering MCP tool: {name}")
        mcp.tool(name=name)(tool_def["func"])

    return mcp


def main():
    """Run the MCP server in stdio mode."""
    mcp = create_mcp_server()
    logger.info("Starting LLM-CLI MCP Server (stdio)...")
    mcp.run()


if __name__ == "__main__":
    main()
