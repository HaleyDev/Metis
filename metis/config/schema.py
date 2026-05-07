from email.policy import default
from operator import ge
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings

class Base(BaseModel):
    """Base class for all models."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

class ChannelsConfig(Base):
    """Configuration for channels."""
    model_config = ConfigDict(extra="allow")

    send_progress: bool = True
    send_tool_hints: bool = False
    send_max_retries: int = Field(default=3, ge=0, le=10)
    transcription_provider: str = "groq"
    transcription_language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}$")


class Config(BaseSettings):
    """Configuration for the application."""
    agents: AgentsConfig = Field(default_factory=AgentsConfig)

class AgentDefaults(Base):
    """Default configuration for agents."""
    workspace: str = "~/.metis/workspace"
    model: str = "ark-code-latest"
    provider: str = (
        "auto"
    )
    max_tokens: int = 8192
    context_window_tokens: int = 65536
    context_block_limit: int | None = None
    temperature: float = 0.1
    max_tool_iterations: int = 200
    max_concurrent_subagents: int = Field(default=1, ge=1)
    max_tool_result_chars: int = 16000
    provider_retry_mode: Literal["standard", "persistent"]= "standard"
    tool_hint_max_length:int = Field(
        default=40,
        ge=20,
        le=500,
        validation_alias=AliasChoices("idleCompactAfterMinutes", "sessionTtlMinutes"),
        serialization_alias="idleCompactAfterMinutes",
    )
    reasoning_effort: str | None = None
    timezone: str = "UTC"
    unified_session: bool = False
    disabled_skills: list[str] = Field(default_factory=list)
    session_ttl_minutes: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("idleCompactAfterMinutes", "sessionTtlMinutes"),
        serialization_alias="idleCompactAfterMinutes",
    )
    max_messages: int = Field(
        default=12,
        ge=0,
    )
    consolidation_ratio: float = Field(
        default=0.5,
        ge=0.1,
        le=0.95,
        validation_alias=AliasChoices("consolidationRatio", "consolidationRatio"),
        serialization_alias="consolidationRatio",
    )

class AgentsConfig(Base):
    """Configuration for agents."""
    defaults: AgentDefaults = Field(default_factory=AgentDefaults)