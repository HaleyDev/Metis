from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

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
