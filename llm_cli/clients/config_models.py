# llm_cli/clients/config_models.py

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GeneralConfig:
    """General application settings."""

    unified_default_provider: str = "google"
    pdf_as_base64: bool = True
    request_timeout: int = 1800
    command_timeout: int = 300
    max_command_memory_mb: int = 1024
    max_output_length: int = 30000
    max_output_lines: int = 500
    max_chat_log_lines: int = 10000
    max_security_log_lines: int = 1000
    image_save_path: str = "~/Pictures/llm-cli"


@dataclass
class ProviderConfig:
    """Configuration for an LLM provider."""

    api_key: str | None = None
    api_url: str | None = None
    system_prompt: str | None = None
    disable_date_prompt: bool = False
    max_tokens: int | None = None
    models: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SecurityConfig:
    """Security and guardrail settings."""

    default_roles: list[str] = field(default_factory=lambda: ["user"])
    default_user_id: str = "current_user"
    allowed_paths: list[str] = field(default_factory=lambda: ["."])
    blocked_paths: list[str] = field(default_factory=list)
    allowed_env_vars: list[str] = field(default_factory=list)
    static_analysis_is_error: bool = True
    scaling_patterns: list[str] = field(default_factory=list)


@dataclass
class SentinelConfig:
    """Reasoning Sentinel (Mamba-SSM Guard) settings."""

    enabled: bool = True
    mode: str = "learn"
    d_model: int = 128
    n_layers: int = 2
    d_state: int = 8
    d_conv: int = 4
    expand: int = 1
    lr: float = 0.001
    checkpoint_path: str = "sentinel_state.npz"


@dataclass
class McpServerConfig:
    """MCP Server configuration."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    zero_trust: bool = False


@dataclass
class AppConfig:
    """Root configuration model."""

    general: GeneralConfig = field(default_factory=GeneralConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    sentinel: SentinelConfig = field(default_factory=SentinelConfig)
    mcp_servers: list[McpServerConfig] = field(default_factory=list)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)
    templates: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        """Creates an AppConfig from a dictionary."""
        general = GeneralConfig(
            **{
                k: v
                for k, v in data.get("general", {}).items()
                if k in GeneralConfig.__annotations__
            }
        )
        security = SecurityConfig(
            **{
                k: v
                for k, v in data.get("security", {}).items()
                if k in SecurityConfig.__annotations__
            }
        )
        sentinel = SentinelConfig(
            **{
                k: v
                for k, v in data.get("sentinel", {}).items()
                if k in SentinelConfig.__annotations__
            }
        )

        mcp_servers = [McpServerConfig(**s) for s in data.get("mcp_servers", [])]

        providers = {}
        provider_names = ["google", "openai", "anthropic", "xai", "brave", "ollama"]
        for name in provider_names:
            if name in data:
                p_data = data[name]
                p_known = {
                    k: v
                    for k, v in p_data.items()
                    if k in ProviderConfig.__annotations__
                }
                p_extra = {
                    k: v
                    for k, v in p_data.items()
                    if k not in ProviderConfig.__annotations__
                }
                providers[name] = ProviderConfig(**p_known, extra=p_extra)

        return cls(
            general=general,
            security=security,
            sentinel=sentinel,
            mcp_servers=mcp_servers,
            providers=providers,
            templates=data.get("templates", {}),
        )
