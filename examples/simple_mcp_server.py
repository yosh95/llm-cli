import logging
import sys

from llm_cli.mcp_server_lib import FastMCP

# Configure logging to stderr because stdout is used for MCP JSON-RPC
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger(__name__)

# Create a simple MCP server named "test-server"
mcp = FastMCP("test-server")


@mcp.tool()
def hello(name: str = "World") -> str:
    """Say hello to someone."""
    logger.info(f"Tool 'hello' called with name={name}")
    return f"Hello, {name}!"


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    logger.info(f"Tool 'add' called with a={a}, b={b}")
    return a + b


@mcp.tool()
def get_status() -> dict:
    """Get some mock status information."""
    logger.info("Tool 'get_status' called")
    return {
        "status": "online",
        "version": "1.0.0",
        "features": ["hello", "add", "get_status"],
    }


def main() -> None:
    logger.info("Starting Simple MCP Server (stdio)...")
    mcp.run()


if __name__ == "__main__":
    main()
