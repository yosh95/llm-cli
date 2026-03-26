import logging
from enum import Enum
from typing import TypedDict

from llm_cli.clients.config import config_manager

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Enumeration of risk levels for tool execution."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SecurityPosture(TypedDict):
    """Defines the security requirements scaled by CASS."""

    require_pqc_signature: bool
    pqc_variant: str  # ML-DSA-44, 65, or 87
    require_pqc_audit_encryption: bool
    ast_strictness: str  # "basic", "restricted", "strict"
    require_dual_llm_verification: bool


class CASSOrchestrator:
    """
    Context-Adaptive Security Scaling (CASS) Orchestrator.
    Dynamically determines the required security posture based on the requested
    tool's risk profile.
    """

    def __init__(self) -> None:
        # Define high-risk tools that can modify system state or execute arbitrary code
        self.high_risk_tools = set(
            config_manager.get("security", "high_risk_tools") or []
        )

        # Define medium-risk tools that can read potentially sensitive information
        self.medium_risk_tools = set(
            config_manager.get("security", "medium_risk_tools") or []
        )

    def evaluate_risk(self, tool_name: str) -> RiskLevel:
        """Evaluate the risk level of a given tool."""
        if tool_name in self.high_risk_tools:
            return RiskLevel.HIGH
        elif tool_name in self.medium_risk_tools:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.LOW

    def get_security_requirements(self, tool_name: str) -> SecurityPosture:
        """Get the required security posture for a specific tool execution."""
        risk_level = self.evaluate_risk(tool_name)
        dual_llm_enabled = config_manager.get_bool("security", "dual_llm_verification")

        if risk_level == RiskLevel.HIGH:
            logger.debug(
                f"CASS: High risk detected for tool '{tool_name}'. "
                "Escalating security posture."
            )
            return {
                "require_pqc_signature": True,
                "pqc_variant": "ML-DSA-87",
                "require_pqc_audit_encryption": True,
                "ast_strictness": "strict",
                "require_dual_llm_verification": dual_llm_enabled,
            }
        elif risk_level == RiskLevel.MEDIUM:
            logger.debug(f"CASS: Medium risk detected for tool '{tool_name}'.")
            return {
                "require_pqc_signature": True,
                "pqc_variant": "ML-DSA-65",
                "require_pqc_audit_encryption": False,
                "ast_strictness": "restricted",
                "require_dual_llm_verification": False,
            }
        else:
            logger.debug(f"CASS: Low risk detected for tool '{tool_name}'.")
            return {
                "require_pqc_signature": True,
                "pqc_variant": "ML-DSA-44",
                "require_pqc_audit_encryption": False,
                "ast_strictness": "basic",
                "require_dual_llm_verification": False,
            }


cass_orchestrator = CASSOrchestrator()
