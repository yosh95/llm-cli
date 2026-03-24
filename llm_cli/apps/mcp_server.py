# llm_cli/apps/mcp_server.py

import functools
import inspect
import logging
import os
import sys
from collections.abc import Callable
from typing import Any

from llm_cli.clients.config import config_manager
from llm_cli.mcp_server_lib import FastMCP
from llm_cli.modules.tool_registry import registry
from llm_cli.security.audit import log_audit
from llm_cli.security.integrity import verify_installation
from llm_cli.security.policy import PolicyEngine, policy_engine

# Configure logging to stderr because stdout is used for MCP JSON-RPC
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

# Load User Configuration for Security Policies
try:
    user_config = config_manager.load_config()
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


def secure_tool_wrapper(func: Callable[..., Any], tool_name: str) -> Callable[..., Any]:
    """
    Decorator-like wrapper to enforce security policies before tool execution.
    Implements Zero Trust and Workload Identity checks.
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        # 1. Identity Verification (Workload Auth)
        # Attempt to retrieve token from Environment (injected by client or SSH wrapper)
        token = os.environ.get("MCP_AUTH_TOKEN")

        from llm_cli.security.policy import EvaluationContext

        user_context: EvaluationContext = {}

        if token:
            # Case A: Token Present - Verify Signature
            from llm_cli.security.identity import id_manager

            payload = id_manager.verify_token(token)
            if payload:
                user_context = {
                    "user_id": str(payload.get("sub", "unknown")),
                    "user_prompt": "Execution via MCP",
                    "has_pqc_proof": payload.get("pqc", False),
                }
                logger.info(f"Authenticated User: {user_context['user_id']}")
            else:
                # Token present but invalid -> Treat as attack attempt (Deny)
                logger.warning("Invalid Auth Token provided. Access Denied.")
                return "⛔ Authentication Failed: Invalid Token."
        else:
            # Case B: No Token - Apply Missing Token Policy
            logger.info(
                f"No Auth Token found. Applying missing_token_policy: "
                f"'{MISSING_TOKEN_POLICY}'"
            )
            if MISSING_TOKEN_POLICY == "deny":
                return "⛔ Access Denied: Authentication required."

            # Assign the fallback identity
            user_context = {
                "user_id": "anonymous_client",
                "user_prompt": "Execution via MCP (No Token)",
                "has_pqc_proof": False,
            }

        # 2. Policy Enforcement (Zero Trust / ABAC)
        if not policy_engine.evaluate(tool_name, kwargs, user_context):
            error_msg = (
                f"⛔ Security Policy Violation: User '{user_context.get('user_id')}' "
                f"is not allowed to use '{tool_name}' in this context."
            )
            logger.warning(error_msg)
            return error_msg

        # 3. Audit Logging (Non-repudiation)
        from llm_cli.mcp_lib import get_current_trace_id

        # Extract model name if provided by the client (internal/propagation)
        # We don't pop it here so it can be popped and logged by the tool's
        # registry wrapper if it exists.
        audit_model = kwargs.get("__audit_model__", "-")

        audit_context = {
            "user_id": user_context.get("user_id"),
            "audience": os.environ.get("MCP_SERVER_NAME"),
            "trace_id": get_current_trace_id(),
            "model": audit_model,
        }

        # 4. Actual Execution
        try:
            if inspect.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)

            # --- Bi-directional Verification: Sign Output ---
            # Result MUST be signed to pass client-side 'high' security verification.
            # Ensure we're signing a canonical JSON string representation of the result
            import json

            from llm_cli.security.pqc import PQCAgilityManager, sign_tool_result

            if isinstance(result, (dict, list)):
                res_str = json.dumps(result)
            else:
                res_str = str(result)

            variant = PQCAgilityManager.get_required_level(tool_name, args=kwargs)
            signed_result = sign_tool_result(res_str, variant=variant)

            log_audit(
                tool_name=tool_name,
                args=kwargs,
                _output=res_str,
                context=audit_context,
            )
            return signed_result
        except Exception as e:
            log_audit(
                tool_name=tool_name,
                args=kwargs,
                _output=None,
                error=str(e),
                context=audit_context,
            )
            logger.error(f"Execution failed: {e}")
            raise e

    return wrapper


def create_mcp_server() -> FastMCP:
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


def main() -> None:
    """Run the MCP server in stdio mode."""
    mcp = create_mcp_server()
    logger.info("Starting LLM-CLI MCP Server (stdio)...")
    mcp.run()


if __name__ == "__main__":
    main()
