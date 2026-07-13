from dataclasses import dataclass
from typing import Any


@dataclass
class AiResponse:
    content: str
    provider: str
    model: str
    raw: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None


class AIProviderError(Exception):
    """Base exception for AI provider errors"""
    pass


class AIProviderConfigurationError(AIProviderError):
    """Raised when AI provider is not properly configured"""
    pass


class AIProviderUnavailableError(AIProviderError):
    """Raised when AI provider is temporarily unavailable"""
    pass


class AIProviderResponseError(AIProviderError):
    """Raised when AI provider returns an invalid response"""
    pass


class AiProvider:
    """Base interface for AI providers"""

    provider_name = "base"

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ) -> AiResponse:
        """Generate a chat completion response

        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model name to use (provider-specific default if None)
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate

        Returns:
            AiResponse with content, provider, model, and optional raw/usage data

        Raises:
            AIProviderConfigurationError: Provider not configured
            AIProviderUnavailableError: Provider temporarily unavailable
            AIProviderResponseError: Invalid response from provider
        """
        raise NotImplementedError
