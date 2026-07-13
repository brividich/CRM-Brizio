"""Embedding provider interfaces for AI memory retrieval."""

from __future__ import annotations

import hashlib
import logging
import math
import time
from abc import ABC, abstractmethod
from typing import Any

import requests
from django.conf import settings
from requests.exceptions import HTTPError, RequestException, Timeout

from .query_normalizer import normalize_query

logger = logging.getLogger(__name__)


class BaseEmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    provider_name = "base"
    model_name = "base"

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Return the embedding vector dimensions."""
        raise NotImplementedError

    @abstractmethod
    def is_configured(self) -> bool:
        """Check if the provider is properly configured."""
        raise NotImplementedError

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        raise NotImplementedError

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts. Default implementation calls embed_text for each."""
        return [self.embed_text(text) for text in texts]

    def _validate_dimensions(self, embedding: list[float]) -> None:
        """Validate that embedding has correct dimensions."""
        if len(embedding) != self.dimensions:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.dimensions}, got {len(embedding)}"
            )


class DeterministicHashEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic hash-based embedding provider for local development/testing."""

    provider_name = "deterministic_hash"

    def __init__(self, dimensions: int | None = None):
        self._dimensions = int(dimensions or getattr(settings, "AI_MEMORY_EMBEDDING_DIMENSIONS", 384))
        self.model_name = f"hash-bow-{self._dimensions}"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def is_configured(self) -> bool:
        """Deterministic hash provider is always configured."""
        return True

    def embed_text(self, text: str) -> list[float]:
        tokens = normalize_query(text).tokens
        vector = [0.0] * self.dimensions
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + (0.25 if token.startswith("cve-") or "-" in token or "." in token else 0.0)
            vector[index] += sign * weight

        norm = math.sqrt(sum(value * value for value in vector))
        if not norm:
            return vector
        return [round(value / norm, 8) for value in vector]


class OpenAICompatibleEmbeddingProvider(BaseEmbeddingProvider):
    """OpenAI-compatible embedding provider for external embedding APIs."""

    provider_name = "openai_compatible"

    def __init__(self):
        self._settings = self._get_settings()
        self.model_name = self._settings.get("model", "text-embedding-3-small")
        self._dimensions = self._settings.get("dimensions", 1536)

    def _get_settings(self) -> dict[str, Any]:
        """Get OpenAI-compatible provider settings."""
        return {
            "api_key": getattr(settings, "OPENAI_COMPATIBLE_API_KEY", None),
            "base_url": getattr(settings, "OPENAI_COMPATIBLE_BASE_URL", None),
            "embeddings_path": getattr(settings, "OPENAI_COMPATIBLE_EMBEDDINGS_PATH", "/embeddings"),
            "model": getattr(settings, "OPENAI_COMPATIBLE_EMBEDDING_MODEL", None),
            "dimensions": int(getattr(settings, "OPENAI_COMPATIBLE_EMBEDDING_DIMENSIONS", 1536)),
            "timeout": getattr(settings, "AI_REQUEST_TIMEOUT_SECONDS", 20),
            "retries": getattr(settings, "AI_REQUEST_RETRIES", 0),
            "retry_backoff_seconds": getattr(settings, "AI_RETRY_BACKOFF_SECONDS", 1),
        }

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def is_configured(self) -> bool:
        """Check if OpenAI-compatible provider is properly configured."""
        return bool(
            self._settings.get("api_key")
            and self._settings.get("base_url")
            and self._settings.get("model")
        )

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text using OpenAI-compatible API."""
        if not self.is_configured():
            raise RuntimeError("OpenAI-compatible embedding provider is not configured")

        embeddings = self._call_api([text])
        if not embeddings:
            raise RuntimeError("No embeddings returned from API")

        embedding = embeddings[0]
        self._validate_dimensions(embedding)
        return embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using batch API."""
        if not self.is_configured():
            raise RuntimeError("OpenAI-compatible embedding provider is not configured")

        if not texts:
            return []

        embeddings = self._call_api(texts)
        for embedding in embeddings:
            self._validate_dimensions(embedding)

        return embeddings

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Call OpenAI-compatible embeddings API with retry logic."""
        url = f"{self._settings['base_url']}{self._settings['embeddings_path']}"
        headers = {
            "Authorization": f"Bearer {self._settings['api_key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._settings["model"],
            "input": texts,
        }

        timeout = self._settings["timeout"]
        retries = min(self._settings["retries"], 3)
        retry_backoff_seconds = self._settings["retry_backoff_seconds"]

        last_error = None

        for attempt in range(retries + 1):
            try:
                logger.debug(
                    f"Calling OpenAI-compatible embeddings API: model={self._settings['model']}, "
                    f"texts={len(texts)}, attempt={attempt + 1}/{retries + 1}"
                )
                response = requests.post(url, json=payload, headers=headers, timeout=timeout)
                response.raise_for_status()

                data = response.json()

                if "data" not in data or not data["data"]:
                    raise RuntimeError("Invalid response: no data in response")

                embeddings = [item["embedding"] for item in data["data"]]
                logger.debug(
                    f"OpenAI-compatible embeddings API success: model={self._settings['model']}, "
                    f"embeddings={len(embeddings)}"
                )

                return embeddings

            except Timeout as e:
                last_error = e
                logger.warning(
                    f"OpenAI-compatible embeddings API timeout: model={self._settings['model']}, "
                    f"attempt={attempt + 1}/{retries + 1}"
                )
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(
                        f"OpenAI-compatible embeddings API timeout after {retries + 1} attempts: "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError("Embedding provider timeout")

            except ConnectionError as e:
                last_error = e
                logger.warning(
                    f"OpenAI-compatible embeddings API connection error: model={self._settings['model']}, "
                    f"attempt={attempt + 1}/{retries + 1}"
                )
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(
                        f"OpenAI-compatible embeddings API connection error after {retries + 1} attempts: "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError("Embedding provider unavailable")

            except HTTPError as e:
                status_code = e.response.status_code
                last_error = e

                if status_code in (400, 401, 403):
                    logger.error(
                        f"OpenAI-compatible embeddings API client error: {status_code}, "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError(f"Embedding provider HTTP error: {status_code}")

                if status_code == 404:
                    logger.error(
                        f"OpenAI-compatible embeddings API model not found: {self._settings['model']}"
                    )
                    raise RuntimeError(f"Model not available: {self._settings['model']}")

                if status_code == 429:
                    logger.warning(
                        f"OpenAI-compatible embeddings API rate limited: model={self._settings['model']}, "
                        f"attempt={attempt + 1}/{retries + 1}"
                    )
                    if attempt < retries:
                        time.sleep(retry_backoff_seconds)
                    else:
                        logger.error(
                            f"OpenAI-compatible embeddings API rate limited after {retries + 1} attempts: "
                            f"model={self._settings['model']}"
                        )
                        raise RuntimeError("Embedding provider rate limited")

                if status_code >= 500:
                    logger.warning(
                        f"OpenAI-compatible embeddings API server error: {status_code}, "
                        f"model={self._settings['model']}, attempt={attempt + 1}/{retries + 1}"
                    )
                    if attempt < retries:
                        time.sleep(retry_backoff_seconds)
                    else:
                        logger.error(
                            f"OpenAI-compatible embeddings API server error after {retries + 1} attempts: "
                            f"{status_code}"
                        )
                        raise RuntimeError(f"Embedding provider HTTP error: {status_code}")

                logger.error(
                    f"OpenAI-compatible embeddings API HTTP error: {status_code}, "
                    f"model={self._settings['model']}"
                )
                raise RuntimeError(f"Embedding provider HTTP error: {status_code}")

            except RequestException as e:
                last_error = e
                logger.warning(
                    f"OpenAI-compatible embeddings API request error: model={self._settings['model']}, "
                    f"attempt={attempt + 1}/{retries + 1}"
                )
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(
                        f"OpenAI-compatible embeddings API request error after {retries + 1} attempts: "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError("Embedding provider request failed")

            except (KeyError, ValueError) as e:
                last_error = e
                logger.error(
                    f"OpenAI-compatible embeddings API response parsing error: model={self._settings['model']}"
                )
                raise RuntimeError("Invalid response format")

        logger.error(
            f"OpenAI-compatible embeddings API failed after {retries + 1} attempts: "
            f"model={self._settings['model']}"
        )
        raise RuntimeError("Embedding provider unavailable")


class NvidiaNimEmbeddingProvider(BaseEmbeddingProvider):
    """NVIDIA NIM embedding provider for NVIDIA-hosted embedding models."""

    provider_name = "nvidia_nim"

    def __init__(self):
        self._settings = self._get_settings()
        self.model_name = self._settings.get("model", "nvidia/nv-embedqa-e5-v5")
        self._dimensions = self._settings.get("dimensions", 1024)

    def _get_settings(self) -> dict[str, Any]:
        """Get NVIDIA NIM provider settings."""
        api_key = getattr(settings, "NVIDIA_NIM_API_KEY", None)
        if not api_key:
            api_key = getattr(settings, "NVIDIA_API_KEY", None)

        return {
            "api_key": api_key,
            "base_url": getattr(settings, "NVIDIA_NIM_BASE_URL", "https://integrate.api.nvidia.com/v1"),
            "embeddings_path": getattr(settings, "NVIDIA_NIM_EMBEDDINGS_PATH", "/embeddings"),
            "model": getattr(settings, "NVIDIA_NIM_EMBEDDING_MODEL", None),
            "dimensions": int(getattr(settings, "NVIDIA_NIM_EMBEDDING_DIMENSIONS", 1024)),
            "timeout": getattr(settings, "AI_REQUEST_TIMEOUT_SECONDS", 20),
            "retries": getattr(settings, "AI_REQUEST_RETRIES", 0),
            "retry_backoff_seconds": getattr(settings, "AI_RETRY_BACKOFF_SECONDS", 1),
        }

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def is_configured(self) -> bool:
        """Check if NVIDIA NIM provider is properly configured."""
        api_key = self._settings.get("api_key")
        if not api_key or api_key in ("your_nvidia_api_key_here", "placeholder", "test"):
            return False
        return bool(self._settings.get("model"))

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text using NVIDIA NIM API."""
        if not self.is_configured():
            raise RuntimeError("NVIDIA NIM embedding provider is not configured")

        embeddings = self._call_api([text])
        if not embeddings:
            raise RuntimeError("No embeddings returned from API")

        embedding = embeddings[0]
        self._validate_dimensions(embedding)
        return embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using batch API."""
        if not self.is_configured():
            raise RuntimeError("NVIDIA NIM embedding provider is not configured")

        if not texts:
            return []

        embeddings = self._call_api(texts)
        for embedding in embeddings:
            self._validate_dimensions(embedding)

        return embeddings

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Call NVIDIA NIM embeddings API with retry logic."""
        url = f"{self._settings['base_url']}{self._settings['embeddings_path']}"
        headers = {
            "Authorization": f"Bearer {self._settings['api_key']}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._settings["model"],
            "input": texts,
            "encoding_format": "float",
        }

        timeout = self._settings["timeout"]
        retries = min(self._settings["retries"], 3)
        retry_backoff_seconds = self._settings["retry_backoff_seconds"]

        last_error = None

        for attempt in range(retries + 1):
            try:
                logger.debug(
                    f"Calling NVIDIA NIM embeddings API: model={self._settings['model']}, "
                    f"texts={len(texts)}, attempt={attempt + 1}/{retries + 1}"
                )
                response = requests.post(url, json=payload, headers=headers, timeout=timeout)
                response.raise_for_status()

                data = response.json()

                if "data" not in data or not data["data"]:
                    raise RuntimeError("Invalid response: no data in response")

                embeddings = [item["embedding"] for item in data["data"]]
                logger.debug(
                    f"NVIDIA NIM embeddings API success: model={self._settings['model']}, "
                    f"embeddings={len(embeddings)}"
                )

                return embeddings

            except Timeout as e:
                last_error = e
                logger.warning(
                    f"NVIDIA NIM embeddings API timeout: model={self._settings['model']}, "
                    f"attempt={attempt + 1}/{retries + 1}"
                )
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(
                        f"NVIDIA NIM embeddings API timeout after {retries + 1} attempts: "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError("Embedding provider timeout")

            except ConnectionError as e:
                last_error = e
                logger.warning(
                    f"NVIDIA NIM embeddings API connection error: model={self._settings['model']}, "
                    f"attempt={attempt + 1}/{retries + 1}"
                )
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(
                        f"NVIDIA NIM embeddings API connection error after {retries + 1} attempts: "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError("Embedding provider unavailable")

            except HTTPError as e:
                status_code = e.response.status_code
                last_error = e

                if status_code in (400, 401, 403):
                    logger.error(
                        f"NVIDIA NIM embeddings API client error: {status_code}, "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError(f"Embedding provider HTTP error: {status_code}")

                if status_code == 404:
                    logger.error(
                        f"NVIDIA NIM embeddings API model not found: {self._settings['model']}"
                    )
                    raise RuntimeError(f"Model not available: {self._settings['model']}")

                if status_code == 429:
                    logger.warning(
                        f"NVIDIA NIM embeddings API rate limited: model={self._settings['model']}, "
                        f"attempt={attempt + 1}/{retries + 1}"
                    )
                    if attempt < retries:
                        time.sleep(retry_backoff_seconds)
                    else:
                        logger.error(
                            f"NVIDIA NIM embeddings API rate limited after {retries + 1} attempts: "
                            f"model={self._settings['model']}"
                        )
                        raise RuntimeError("Embedding provider rate limited")

                if status_code >= 500:
                    logger.warning(
                        f"NVIDIA NIM embeddings API server error: {status_code}, "
                        f"model={self._settings['model']}, attempt={attempt + 1}/{retries + 1}"
                    )
                    if attempt < retries:
                        time.sleep(retry_backoff_seconds)
                    else:
                        logger.error(
                            f"NVIDIA NIM embeddings API server error after {retries + 1} attempts: "
                            f"{status_code}"
                        )
                        raise RuntimeError(f"Embedding provider HTTP error: {status_code}")

                logger.error(
                    f"NVIDIA NIM embeddings API HTTP error: {status_code}, "
                    f"model={self._settings['model']}"
                )
                raise RuntimeError(f"Embedding provider HTTP error: {status_code}")

            except RequestException as e:
                last_error = e
                logger.warning(
                    f"NVIDIA NIM embeddings API request error: model={self._settings['model']}, "
                    f"attempt={attempt + 1}/{retries + 1}"
                )
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(
                        f"NVIDIA NIM embeddings API request error after {retries + 1} attempts: "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError("Embedding provider request failed")

            except (KeyError, ValueError) as e:
                last_error = e
                logger.error(
                    f"NVIDIA NIM embeddings API response parsing error: model={self._settings['model']}"
                )
                raise RuntimeError("Invalid response format")

        logger.error(
            f"NVIDIA NIM embeddings API failed after {retries + 1} attempts: "
            f"model={self._settings['model']}"
        )
        raise RuntimeError("Embedding provider unavailable")


class LocalHttpEmbeddingProvider(BaseEmbeddingProvider):
    """Local HTTP embedding provider for self-hosted embedding services."""

    provider_name = "local_http"

    def __init__(self):
        self._settings = self._get_settings()
        self.model_name = self._settings.get("model", "local-embedding")
        self._dimensions = self._settings.get("dimensions", 384)

    def _get_settings(self) -> dict[str, Any]:
        """Get local HTTP provider settings."""
        return {
            "base_url": getattr(settings, "LOCAL_HTTP_EMBEDDING_BASE_URL", None),
            "embeddings_path": getattr(settings, "LOCAL_HTTP_EMBEDDINGS_PATH", "/embeddings"),
            "model": getattr(settings, "LOCAL_HTTP_EMBEDDING_MODEL", None),
            "dimensions": int(getattr(settings, "LOCAL_HTTP_EMBEDDING_DIMENSIONS", 384)),
            "timeout": getattr(settings, "AI_REQUEST_TIMEOUT_SECONDS", 20),
            "retries": getattr(settings, "AI_REQUEST_RETRIES", 0),
            "retry_backoff_seconds": getattr(settings, "AI_RETRY_BACKOFF_SECONDS", 1),
        }

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def is_configured(self) -> bool:
        """Check if local HTTP provider is properly configured."""
        return bool(
            self._settings.get("base_url") and self._settings.get("model")
        )

    def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text using local HTTP API."""
        if not self.is_configured():
            raise RuntimeError("Local HTTP embedding provider is not configured")

        embeddings = self._call_api([text])
        if not embeddings:
            raise RuntimeError("No embeddings returned from API")

        embedding = embeddings[0]
        self._validate_dimensions(embedding)
        return embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts using batch API."""
        if not self.is_configured():
            raise RuntimeError("Local HTTP embedding provider is not configured")

        if not texts:
            return []

        embeddings = self._call_api(texts)
        for embedding in embeddings:
            self._validate_dimensions(embedding)

        return embeddings

    def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Call local HTTP embeddings API with retry logic."""
        url = f"{self._settings['base_url']}{self._settings['embeddings_path']}"
        headers = {
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._settings["model"],
            "input": texts,
        }

        timeout = self._settings["timeout"]
        retries = min(self._settings["retries"], 3)
        retry_backoff_seconds = self._settings["retry_backoff_seconds"]

        last_error = None

        for attempt in range(retries + 1):
            try:
                logger.debug(
                    f"Calling local HTTP embeddings API: model={self._settings['model']}, "
                    f"texts={len(texts)}, attempt={attempt + 1}/{retries + 1}"
                )
                response = requests.post(url, json=payload, headers=headers, timeout=timeout)
                response.raise_for_status()

                data = response.json()

                if "data" not in data or not data["data"]:
                    raise RuntimeError("Invalid response: no data in response")

                embeddings = [item["embedding"] for item in data["data"]]
                logger.debug(
                    f"Local HTTP embeddings API success: model={self._settings['model']}, "
                    f"embeddings={len(embeddings)}"
                )

                return embeddings

            except Timeout as e:
                last_error = e
                logger.warning(
                    f"Local HTTP embeddings API timeout: model={self._settings['model']}, "
                    f"attempt={attempt + 1}/{retries + 1}"
                )
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(
                        f"Local HTTP embeddings API timeout after {retries + 1} attempts: "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError("Embedding provider timeout")

            except ConnectionError as e:
                last_error = e
                logger.warning(
                    f"Local HTTP embeddings API connection error: model={self._settings['model']}, "
                    f"attempt={attempt + 1}/{retries + 1}"
                )
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(
                        f"Local HTTP embeddings API connection error after {retries + 1} attempts: "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError("Embedding provider unavailable")

            except HTTPError as e:
                status_code = e.response.status_code
                last_error = e

                if status_code in (400, 401, 403):
                    logger.error(
                        f"Local HTTP embeddings API client error: {status_code}, "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError(f"Embedding provider HTTP error: {status_code}")

                if status_code == 404:
                    logger.error(
                        f"Local HTTP embeddings API model not found: {self._settings['model']}"
                    )
                    raise RuntimeError(f"Model not available: {self._settings['model']}")

                if status_code == 429:
                    logger.warning(
                        f"Local HTTP embeddings API rate limited: model={self._settings['model']}, "
                        f"attempt={attempt + 1}/{retries + 1}"
                    )
                    if attempt < retries:
                        time.sleep(retry_backoff_seconds)
                    else:
                        logger.error(
                            f"Local HTTP embeddings API rate limited after {retries + 1} attempts: "
                            f"model={self._settings['model']}"
                        )
                        raise RuntimeError("Embedding provider rate limited")

                if status_code >= 500:
                    logger.warning(
                        f"Local HTTP embeddings API server error: {status_code}, "
                        f"model={self._settings['model']}, attempt={attempt + 1}/{retries + 1}"
                    )
                    if attempt < retries:
                        time.sleep(retry_backoff_seconds)
                    else:
                        logger.error(
                            f"Local HTTP embeddings API server error after {retries + 1} attempts: "
                            f"{status_code}"
                        )
                        raise RuntimeError(f"Embedding provider HTTP error: {status_code}")

                logger.error(
                    f"Local HTTP embeddings API HTTP error: {status_code}, "
                    f"model={self._settings['model']}"
                )
                raise RuntimeError(f"Embedding provider HTTP error: {status_code}")

            except RequestException as e:
                last_error = e
                logger.warning(
                    f"Local HTTP embeddings API request error: model={self._settings['model']}, "
                    f"attempt={attempt + 1}/{retries + 1}"
                )
                if attempt < retries:
                    time.sleep(retry_backoff_seconds)
                else:
                    logger.error(
                        f"Local HTTP embeddings API request error after {retries + 1} attempts: "
                        f"model={self._settings['model']}"
                    )
                    raise RuntimeError("Embedding provider request failed")

            except (KeyError, ValueError) as e:
                last_error = e
                logger.error(
                    f"Local HTTP embeddings API response parsing error: model={self._settings['model']}"
                )
                raise RuntimeError("Invalid response format")

        logger.error(
            f"Local HTTP embeddings API failed after {retries + 1} attempts: "
            f"model={self._settings['model']}"
        )
        raise RuntimeError("Embedding provider unavailable")


        logger.error(
            f"Local HTTP embeddings API failed after {retries + 1} attempts: "
            f"model={self._settings['model']}"
        )
        raise RuntimeError("Embedding provider unavailable")


def get_embedding_provider(provider_name: str | None = None) -> BaseEmbeddingProvider:
    """
    Factory function to get an embedding provider by name.

    Args:
        provider_name: Name of the provider to use. If None, defaults to 'deterministic_hash'.

    Returns:
        An instance of the requested embedding provider.

    Raises:
        ValueError: If the provider name is unknown.
    """
    provider_name = (provider_name or "deterministic_hash").strip().lower()

    provider_map = {
        "deterministic": DeterministicHashEmbeddingProvider,
        "deterministic_hash": DeterministicHashEmbeddingProvider,
        "hash": DeterministicHashEmbeddingProvider,
        "openai": OpenAICompatibleEmbeddingProvider,
        "openai_compatible": OpenAICompatibleEmbeddingProvider,
        "nvidia": NvidiaNimEmbeddingProvider,
        "nvidia_nim": NvidiaNimEmbeddingProvider,
        "nim": NvidiaNimEmbeddingProvider,
        "local": LocalHttpEmbeddingProvider,
        "local_http": LocalHttpEmbeddingProvider,
    }

    provider_class = provider_map.get(provider_name)
    if not provider_class:
        raise ValueError(f"Unsupported embedding provider: {provider_name}")

    provider = provider_class()

    if not provider.is_configured():
        logger.warning(
            f"Embedding provider '{provider_name}' is not configured. "
            f"Please check your settings."
        )

    return provider
