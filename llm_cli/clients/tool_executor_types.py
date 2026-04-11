# llm_cli/clients/tool_executor_types.py

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from llm_cli.modules.models import ContentPart, DataSource
from llm_cli.security.cass import RiskLevel, SecurityPosture

logger = logging.getLogger(__name__)


@runtime_checkable
class AgentContext(Protocol):
    """Protocol for Agent sessions (e.g. ChatSession)."""

    @property
    def client(self) -> Any: ...
    def _get_input(self, message: str, **kwargs: Any) -> str: ...


@dataclass
class ToolExecutionContext:
    """Carries tool-specific state through the execution pipeline."""

    session: AgentContext
    part: ContentPart
    duration: float | None = None
    # Derived fields
    tool_id: str = "unknown"
    call_id: str | None = None
    name: str = "unknown"
    args: dict[str, Any] = field(default_factory=dict)
    thought_signature: str | None = None
    # Output fields
    result_data: Any = None
    injected_data: DataSource | None = None
    error_message: str | None = None
    aborted: bool = False
    security_warnings: list[tuple[str, str]] = field(default_factory=list)

    # Security fields
    risk_level: RiskLevel = field(init=False)
    security_requirements: SecurityPosture = field(init=False)
    server_name: str | None = field(init=False, default=None)
    verification_task: Any = field(init=False, default=None)

    def __post_init__(self) -> None:
        call = self.part.function_call
        if call:
            self.tool_id = call.get("id", "unknown")
            self.call_id = call.get("call_id")
            self.name = call["name"]
            self.args = call.get("args", {})
            self.thought_signature = self.part.thought_signature

        from llm_cli.security.cass import cass_orchestrator as cass

        # Strip MCP server prefix (e.g., 'gpu__') for risk evaluation
        parts = self.name.split("__")
        if len(parts) > 1:
            self.server_name = parts[0]
            base_name = "__".join(parts[1:])
        else:
            self.server_name = None
            base_name = self.name

        self.risk_level = cass.evaluate_risk(base_name)
        self.security_requirements = cass.get_security_requirements(base_name)
