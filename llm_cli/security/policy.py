import logging
import re
from typing import Any, Dict

logger = logging.getLogger(__name__)

class PolicyEngine:
    """
    Role-Based Access Control (RBAC) Policy Engine.
    Determines permissions based on user roles defined in configuration.
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}

        # Default Role Definitions (Fallback if config is missing)
        self.roles = {
            "admin": {
                "description": "Full access to all tools",
                "allow_all": True,
                "allowed_tools": []
            },
            "guest": {
                "description": "Read-only access for unauthenticated clients",
                "allow_all": False,
                "allowed_tools": ["list_files", "read_file", "fetch_web_text", "google_search"]
            },
            "deny": {
                "description": "No access allowed",
                "allow_all": False,
                "allowed_tools": []
            }
        }

        # Merge user config into roles if provided
        if "roles" in self.config:
            self.roles.update(self.config["roles"])

    def evaluate(self, tool_name: str, arguments: Dict[str, Any], context: Dict[str, Any]) -> bool:
        """
        Evaluate if the current user (based on context roles) can execute the tool.
        """
        user_roles = context.get("roles", ["guest"])
        logger.info(f"🛡️  Policy Evaluation: Tool='{tool_name}', UserRoles={user_roles}")

        # Default Deny
        is_allowed = False
        active_role = None

        # Check all roles assigned to the user. If any role allows it, permit.
        for role_name in user_roles:
            role_def = self.roles.get(role_name)
            if not role_def:
                logger.warning(f"Undefined role encountered: {role_name}")
                continue

            # Check 1: Allow All (Admin)
            if role_def.get("allow_all", False):
                is_allowed = True
                active_role = role_name
                break

            # Check 2: Explicit Allow List
            allowed_tools = role_def.get("allowed_tools", [])
            # Support wildcard matching or exact match
            if tool_name in allowed_tools or "*" in allowed_tools:
                is_allowed = True
                active_role = role_name
                break

        # Additional Guardrail: Path validation for write operations
        # Even admins shouldn't write to /etc casually unless explicitly overridden
        if is_allowed and tool_name in ["write_file", "edit_file", "execute_command"]:
            if not self._validate_dangerous_args(tool_name, arguments):
                logger.warning(f"⛔ Safety Guardrail: Suspicious arguments detected for '{tool_name}'")
                return False

        if is_allowed:
            logger.info(f"✅ Access Granted by role: '{active_role}'")
        else:
            logger.warning(f"⛔ Access Denied: No role allows tool '{tool_name}'")

        return is_allowed

    def _validate_dangerous_args(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """
        Last line of defense: Check for obviously dangerous paths/commands regardless of role.
        This can be configured to be disabled by admins if needed.
        """
        path = arguments.get("path", "")
        # Block writes to critical system directories
        if path and re.match(r"^(/etc|/var|/usr|/root|C:\\Windows)", path):
            return False
        return True

# Singleton instance will be re-initialized with config later
policy_engine = PolicyEngine()
