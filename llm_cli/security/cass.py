import logging
from enum import Enum
from typing import TypedDict

from llm_cli.clients.config import get_setting

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Enumeration of risk levels for tool execution."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SecurityPosture(TypedDict):
    """Defines the security requirements scaled by CASS."""

    require_pqc_signature: bool
    require_pqc_audit_encryption: bool
    mamba_enforcement: str  # "monitor_only", "strict_block"
    use_intent_analyzer: bool


class CASSOrchestrator:
    """
    Context-Adaptive Security Scaling (CASS) Orchestrator.
    Dynamically determines the required security posture based on the requested
    tool's risk profile. This eliminates the need for slow Dual-LLM intent
    analysis for most operations, relying on high-speed Mamba Sentinel and
    scaling up to Post-Quantum Cryptography only when necessary.
    """

    def __init__(self) -> None:
        # Define high-risk tools that can modify system state or execute arbitrary code
        self.high_risk_tools = set(get_setting("high_risk_tools", "security") or [])

        # Define medium-risk tools that can read potentially sensitive information
        self.medium_risk_tools = set(get_setting("medium_risk_tools", "security") or [])

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

        if risk_level == RiskLevel.HIGH:
            logger.debug(
                f"CASS: High risk detected for tool '{tool_name}'."
                " Escalating security posture."
            )
            return {
                "require_pqc_signature": True,
                "require_pqc_audit_encryption": True,
                "mamba_enforcement": "strict_block",  # Block if Mamba score is RED
                "use_intent_analyzer": False,  # Deprecated due to UX/latency
            }
        elif risk_level == RiskLevel.MEDIUM:
            logger.debug(f"CASS: Medium risk detected for tool '{tool_name}'.")
            return {
                "require_pqc_signature": False,  # Fast classical RSA is sufficient
                "require_pqc_audit_encryption": False,
                "mamba_enforcement": "strict_block",
                "use_intent_analyzer": False,
            }
        else:
            logger.debug(f"CASS: Low risk detected for tool '{tool_name}'.")
            return {
                "require_pqc_signature": False,
                "require_pqc_audit_encryption": False,
                "mamba_enforcement": "monitor_only",  # Log warnings but do not block
                "use_intent_analyzer": False,
            }
