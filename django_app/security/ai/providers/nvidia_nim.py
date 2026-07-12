import hashlib
import json
import logging
import time

import requests
from django.core.cache import cache
from requests.exceptions import HTTPError, RequestException, Timeout

from .base import (
    AiProvider,
    AiResponse,
    AIProviderConfigurationError,
    AIProviderResponseError,
    AIProviderUnavailableError,
)

logger = logging.getLogger(__name__)


class NvidiaNimProvider(AiProvider):
    """NVIDIA NIM AI provider implementation"""

    provider_name = "nvidia_nim"

    def __init__(self):
        self.timeout = None
        self.retries = None
        self.retry_backoff_seconds = None

    def _get_settings(self):
        """Get settings at runtime"""
        from django.conf import settings

        api_key = getattr(settings, "NVIDIA_NIM_API_KEY", None)
        if not api_key:
            api_key = getattr(settings, "NVIDIA_API_KEY", None)

        return {
            "api_key": api_key,
            "base_url": getattr(settings, "NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            "completions_path": getattr(settings, "NVIDIA_NIM_CHAT_COMPLETIONS_PATH", "/chat/completions"),
            "default_model": getattr(settings, "AI_DEFAULT_MODEL", "meta/llama-3.1-70b-instruct"),
            "default_temperature": getattr(settings, "AI_TEMPERATURE", 0.3),
            "default_max_tokens": getattr(settings, "AI_MAX_TOKENS", 2048),
            "timeout": getattr(settings, "AI_REQUEST_TIMEOUT_SECONDS", 20),
            "retries": getattr(settings, "AI_REQUEST_RETRIES", 0),
            "retry_backoff_seconds": getattr(settings, "AI_RETRY_BACKOFF_SECONDS", 1),
        }

    def _validate_configuration(self, settings_dict):
        """Validate provider configuration"""
        api_key = settings_dict["api_key"]

        if not api_key:
            raise AIProviderConfigurationError("NVIDIA_NIM_API_KEY not configured")

        if api_key in ("your_nvidia_api_key_here", "placeholder", "test"):
            raise AIProviderConfigurationError("NVIDIA_NIM_API_KEY is a placeholder value")

    def _get_cache_key(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate stable cache key for request"""
        key_data = {
            "provider": self.provider_name,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        serialized_key_data = json.dumps(key_data, sort_keys=True, default=str)
        return f"ai_response:{hashlib.sha256(serialized_key_data.encode()).hexdigest()}"

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AiResponse:
        """Generate chat completion using NVIDIA NIM API"""
        settings_dict = self._get_settings()
        self._validate_configuration(settings_dict)

        model = model or settings_dict["default_model"]
        temperature = temperature if temperature is not None else settings_dict["default_temperature"]
        max_tokens = max_tokens if max_tokens is not None else settings_dict["default_max_tokens"]

        timeout = settings_dict["timeout"]
        retries = min(settings_dict["retries"], 3)
        retry_backoff_seconds = settings_dict["retry_backoff_seconds"]

        cache_key = self._get_cache_key(messages, model, temperature, max_tokens)
        cached_response = cache.get(cache_key)

        if cached_response:
            logger.debug(f"AI cache hit for {model}")
            return cached_response

        url = f"{settings_dict['base_url']}{settings_dict['completions_path']}"
        headers = {
            "Authorization": f"Bearer {settings_dict['api_key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error = None

        for attempt in range(retries + 1):
            try:
                logger.info(f"Calling NVIDIA NIM API: {model}, timeout={timeout}s, attempt={attempt + 1}/{retries + 1}")
                response = requests.post(url, json=payload, headers=headers, timeout=timeout)
                response.raise_for_status()

                data = response.json()

                if "choices" not in data or not data["choices"]:
                    raise AIProviderResponseError("Invalid response: no choices in response")

                content = data["choices"][0]["message"]["content"]

                ai_response = AiResponse(
                    content=content,
                    provider=self.provider_name,
                    model=model,
                    raw=data,
                    usage=data.get("usage"),
                )

                cache.set(cache_key, ai_response, timeout=3600)
                logger.info(f"NVIDIA NIM API success: {model}, tokens={data.get('usage', {}).get('total_tokens', 'N/A')}")

                return ai_response

            except Timeout as e:
                last_error = e
                logger.warning(f"NVIDIA NIM API timeout: {model}, attempt={attempt + 1}/{retries + 1}")
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(f"NVIDIA NIM API timeout after {retries + 1} attempts: {model}")
                    raise AIProviderUnavailableError("AI provider timeout")

            except ConnectionError as e:
                last_error = e
                logger.warning(f"NVIDIA NIM API connection error: {model}, attempt={attempt + 1}/{retries + 1}")
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(f"NVIDIA NIM API connection error after {retries + 1} attempts: {model}")
                    raise AIProviderUnavailableError("AI provider unavailable")

            except HTTPError as e:
                status_code = e.response.status_code
                last_error = e

                if status_code in (400, 401, 403):
                    logger.error(f"NVIDIA NIM API client error: {status_code}, model={model}")
                    raise AIProviderUnavailableError(f"AI provider HTTP error: {status_code}")

                if status_code == 404:
                    logger.error(f"NVIDIA NIM API model not found: {model}")
                    raise AIProviderResponseError(f"Model not available: {model}")

                if status_code == 429:
                    logger.warning(f"NVIDIA NIM API rate limited: {model}, attempt={attempt + 1}/{retries + 1}")
                    if attempt < retries:
                        time.sleep(retry_backoff_seconds)
                    else:
                        logger.error(f"NVIDIA NIM API rate limited after {retries + 1} attempts: {model}")
                        raise AIProviderUnavailableError("AI provider rate limited")

                if status_code >= 500:
                    logger.warning(f"NVIDIA NIM API server error: {status_code}, model={model}, attempt={attempt + 1}/{retries + 1}")
                    if attempt < retries:
                        time.sleep(retry_backoff_seconds)
                    else:
                        logger.error(f"NVIDIA NIM API server error after {retries + 1} attempts: {status_code}")
                        raise AIProviderUnavailableError(f"AI provider HTTP error: {status_code}")

                logger.error(f"NVIDIA NIM API HTTP error: {status_code}, model={model}")
                raise AIProviderUnavailableError(f"AI provider HTTP error: {status_code}")

            except RequestException as e:
                last_error = e
                logger.warning(f"NVIDIA NIM API request error: {model}, attempt={attempt + 1}/{retries + 1}")
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(f"NVIDIA NIM API request error after {retries + 1} attempts: {model}")
                    raise AIProviderUnavailableError("AI provider request failed")

            except (KeyError, ValueError) as e:
                last_error = e
                logger.error(f"NVIDIA NIM API response parsing error: {model}")
                raise AIProviderResponseError("Invalid response format")

        logger.error(f"NVIDIA NIM API failed after {retries + 1} attempts: {model}")
        raise AIProviderUnavailableError("AI provider unavailable")
