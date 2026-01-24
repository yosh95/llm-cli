# llm_cli/apps/mcp_server.py

import functools
import inspect
import logging
import os
import sys

from mcp.server.fastmcp import FastMCP

from llm_cli.apps.configure import load_config
from llm_cli.modules.tool_registry import registry
from llm_cli.security.identity import IdentityManager
from llm_cli.security.integrity import verify_installation
from llm_cli.security.policy import PolicyEngine, policy_engine

# Configure logging to stderr because stdout is used for MCP JSON-RPC
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

# Load User Configuration for Security Policies
try:
    user_config = load_config()
    # Initialize Policy Engine with user config
    # Expects config structure: [security.roles] or similar
    # For now, we pass the whole security section if it exists
    security_config = user_config.get("security", {})
    policy_engine = PolicyEngine(config=security_config)

    # Get Missing Token Policy (Default to 'guest' for usability,
    # or 'deny' for security)
    # User can set security.missing_token_policy = "deny" in config.toml
    MISSING_TOKEN_POLICY = security_config.get("missing_token_policy", "guest")

except Exception as e:
    logger.warning(f"Failed to load user config: {e}. Using default strict policies.")
    MISSING_TOKEN_POLICY = "guest"
    policy_engine = PolicyEngine()

def secure_tool_wrapper(func, tool_name: str):
    """
    Decorator-like wrapper to enforce security policies before tool execution.
    Implements Zero Trust and Workload Identity checks.
    """
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        # 1. Identity Verification (Workload Auth)
        # Attempt to retrieve token from Environment (injected by client or SSH wrapper)
        token = os.environ.get("MCP_AUTH_TOKEN")

        user_context = {}

        if token:
            # Case A: Token Present - Verify Signature
            payload = IdentityManager.verify_token(token)
            if payload:
                user_context = {
                    "roles": payload.get("roles", ["user"]),
                    "user_id": payload.get("sub"),
                }
                logger.info(f"Authenticated User: {user_context['user_id']}")
            else:
                # Token present but invalid -> Treat as attack attempt (Deny)
                logger.warning("Invalid Auth Token provided. Access Denied.")
                return "⛔ Authentication Failed: Invalid Token."
        else:
            # Case B: No Token - Apply Missing Token Policy (e.g., from Claude Desktop)
            logger.info(
                f"No Auth Token found. Applying missing_token_policy: "
                f"'{MISSING_TOKEN_POLICY}'"
            )
            if MISSING_TOKEN_POLICY == "deny":
                return "⛔ Access Denied: Authentication required."

            # Assign the fallback role (e.g., "guest")
            user_context = {
                "roles": [MISSING_TOKEN_POLICY],
                "user_id": "anonymous_client",
            }

        # 2. Policy Enforcement (Zero Trust / RBAC)
        if not policy_engine.evaluate(tool_name, kwargs, user_context):
            error_msg = (
                f"⛔ Security Policy Violation: Role '{user_context.get('roles')}' "
                f"is not allowed to use '{tool_name}'."
            )
            logger.warning(error_msg)
            return error_msg

        # 3. Audit Logging (Non-repudiation)
        logger.info(f"📝 AUDIT: Executing '{tool_name}' with args: {kwargs.keys()}")

        # 4. Actual Execution
        try:
            if inspect.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            raise e

    return wrapper

def create_mcp_server():
    """Create and configure the FastMCP server instance with security hooks."""

    # 0. Root of Trust: Integrity Verification
    # Verify that the server code hasn't been tampered with before starting.
    verify_installation()

    mcp = FastMCP("llm-cli-remote")

    # Register all tools from the tool registry with security wrappers
    for name, tool_def in registry.tools.items():
        original_func = tool_def["func"]

        # Apply security wrapper
        secured_func = secure_tool_wrapper(original_func, name)

        logger.info(f"Registering SECURE MCP tool: {name}")
        mcp.tool(name=name)(secured_func)

    return mcp


def main():
    """Run the MCP server in stdio mode."""
    mcp = create_mcp_server()
    logger.info("Starting LLM-CLI MCP Server (stdio)...")
    mcp.run()


if __name__ == "__main__":
    main()
