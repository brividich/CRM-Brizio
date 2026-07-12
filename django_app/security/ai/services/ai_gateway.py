"""AI Gateway service for provider abstraction and model routing"""

import logging
from typing import Optional

from django.conf import settings

from ..providers.base import (
    AIProviderConfigurationError,
    AIProviderResponseError,
    AIProviderUnavailableError,
    AiProvider,
    AiResponse,
)
from ..providers.nvidia_nim import NvidiaNimProvider

logger = logging.getLogger(__name__)

SUPPORTED_TASKS = {
    "chat",
    "configuration_copilot",
    "report_summary",
    "alert_explanation",
    "rule_generation",
    "rule_simulation_explanation",
    "provider_test",
}


def select_model_for_task(task: str, requested_model: Optional[str] = None) -> str:
    """Select appropriate model for a given task based on routing configuration

    Args:
        task: Task type (chat, configuration_copilot, report_summary, etc.)
        requested_model: Explicitly requested model (takes precedence if provided)

    Returns:
        Model name to use

    Raises:
        ValueError: If task is not supported
    """
    if task not in SUPPORTED_TASKS:
        raise ValueError(f"Unsupported task: {task}")

    if requested_model:
        return requested_model

    route_mode = getattr(settings, "AI_MODEL_ROUTE_MODE", "speed")
    speed_model = getattr(settings, "AI_SPEED_MODEL", "meta/llama-3.2-1b-instruct")
    fast_model = getattr(settings, "AI_FAST_MODEL", "meta/llama-3.1-8b-instruct")
    default_model = getattr(settings, "AI_DEFAULT_MODEL", "meta/llama-3.1-70b-instruct")
    complex_model = getattr(settings, "AI_COMPLEX_MODEL", default_model)

    if route_mode == "speed":
        return speed_model

    if route_mode == "balanced":
        if task in ("configuration_copilot", "rule_generation"):
            return fast_model
        if task == "report_summary":
            return fast_model
        return speed_model

    if route_mode == "quality":
        if task in ("configuration_copilot", "rule_generation"):
            return fast_model
        if task == "report_summary":
            return fast_model
        return default_model

    return speed_model


def get_ai_provider() -> AiProvider:
    """Get configured AI provider instance

    Returns:
        AiProvider instance based on AI_PROVIDER setting

    Raises:
        AIProviderConfigurationError: If provider is not supported
    """
    provider_name = getattr(settings, "AI_PROVIDER", "nvidia_nim")

    if provider_name == "nvidia_nim":
        return NvidiaNimProvider()

    raise AIProviderConfigurationError(f"Unsupported AI provider: {provider_name}")


def chat_completion(
    messages: list[dict[str, str]],
    *,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    task: str = "chat",
    enable_fallback: bool = True,
) -> AiResponse:
    """Generate chat completion using configured AI provider with model routing and fallback

    Args:
        messages: List of message dicts with 'role' and 'content'
        model: Model name to use (uses routing if None)
        temperature: Sampling temperature (uses AI_TEMPERATURE if None)
        max_tokens: Maximum tokens to generate (uses AI_MAX_TOKENS if None)
        task: Task type for model routing
        enable_fallback: Whether to enable fast model fallback on timeout

    Returns:
        AiResponse with content, provider, model, and optional raw/usage data

    Raises:
        AIProviderConfigurationError: Provider not configured
        AIProviderUnavailableError: Provider temporarily unavailable
        AIProviderResponseError: Invalid response from provider
    """
    provider = get_ai_provider()

    selected_model = select_model_for_task(task, model)

    if temperature is None:
        temperature = getattr(settings, "AI_TEMPERATURE", 0.3)

    if max_tokens is None:
        max_tokens = getattr(settings, "AI_MAX_TOKENS", 2048)

    try:
        return provider.chat_completion(
            messages=messages,
            model=selected_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except (AIProviderUnavailableError, AIProviderResponseError) as e:
        if not enable_fallback:
            raise

        fallback_enabled = getattr(settings, "AI_ENABLE_FAST_FALLBACK", True)
        if not fallback_enabled:
            raise

        speed_model = getattr(settings, "AI_SPEED_MODEL", "meta/llama-3.2-1b-instruct")
        fast_model = getattr(settings, "AI_FAST_MODEL", "meta/llama-3.1-8b-instruct")

        if selected_model in (speed_model, fast_model):
            raise

        fallback_model = speed_model if speed_model != selected_model else fast_model
        if fallback_model == selected_model:
            raise

        logger.warning(f"Primary model {selected_model} failed, falling back to {fallback_model}")

        return provider.chat_completion(
            messages=messages,
            model=fallback_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
