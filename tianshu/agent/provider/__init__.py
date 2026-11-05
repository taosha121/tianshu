from .base import Provider, ProviderResponse, ToolCall
from .anthropic_provider import AnthropicProvider
from .openai_provider import OpenAIProvider


def make_provider(model: str) -> Provider:
    if model.startswith("claude"):
        return AnthropicProvider()
    return OpenAIProvider()


__all__ = ["Provider", "ProviderResponse", "ToolCall", "make_provider"]
