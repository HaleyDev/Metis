
from dataclasses import dataclass

from metis.providers.base import LLMProvider


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: LLMProvider
    model: str
    context_window_tokens: int
    signature: tuple[object, ...]


def make_provider(config: Config)