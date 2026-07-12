"""Retry handler with exponential backoff for embedding providers."""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class ErrorType(Enum):
    """Classification of provider errors."""

    CONFIG_MISSING = "config_missing"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    DIMENSION_MISMATCH = "dimension_mismatch"
    PROVIDER_ERROR = "provider_error"


class RetryHandler:
    """Retry handler with exponential backoff for embedding providers."""

    def __init__(
        self,
        max_retries: int = 3,
        backoff_seconds: float = 2.0,
    ):
        """
        Initialize retry handler.

        Args:
            max_retries: Maximum number of retry attempts.
            backoff_seconds: Base backoff time in seconds (exponential).
        """
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds

    def classify_error(self, error: Exception) -> ErrorType:
        """
        Classify an error into an ErrorType.

        Args:
            error: The exception to classify.

        Returns:
            The ErrorType classification.
        """
        error_message = str(error).lower()

        # Check for specific error patterns
        if "not configured" in error_message or "missing" in error_message:
            return ErrorType.CONFIG_MISSING
        if "rate limit" in error_message or "429" in error_message:
            return ErrorType.RATE_LIMITED
        if "timeout" in error_message:
            return ErrorType.TIMEOUT
        if "dimension" in error_message and "mismatch" in error_message:
            return ErrorType.DIMENSION_MISMATCH
        if "invalid response" in error_message or "parsing" in error_message:
            return ErrorType.INVALID_RESPONSE

        # Default to provider error
        return ErrorType.PROVIDER_ERROR

    def should_retry(self, error: Exception, attempt: int) -> bool:
        """
        Determine if an error should be retried.

        Args:
            error: The exception that occurred.
            attempt: Current attempt number (0-indexed).

        Returns:
            True if error should be retried, False otherwise.
        """
        # Don't retry if we've exceeded max retries
        if attempt >= self.max_retries:
            return False

        # Classify the error
        error_type = self.classify_error(error)

        # Don't retry configuration errors
        if error_type == ErrorType.CONFIG_MISSING:
            return False

        # Don't retry dimension mismatch errors
        if error_type == ErrorType.DIMENSION_MISMATCH:
            return False

        # Retry rate limit, timeout, and provider errors
        if error_type in (ErrorType.RATE_LIMITED, ErrorType.TIMEOUT, ErrorType.PROVIDER_ERROR):
            return True

        # Don't retry invalid response errors
        if error_type == ErrorType.INVALID_RESPONSE:
            return False

        # Default: don't retry
        return False

    def get_backoff_time(self, attempt: int) -> float:
        """
        Calculate exponential backoff time for given attempt.

        Args:
            attempt: Current attempt number (0-indexed).

        Returns:
            Backoff time in seconds.
        """
        return self.backoff_seconds * (2 ** attempt)

    def retry_with_backoff(
        self,
        func: Callable,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Execute function with retry logic and exponential backoff.

        Args:
            func: Function to execute.
            *args: Positional arguments for func.
            **kwargs: Keyword arguments for func.

        Returns:
            Result of func execution.

        Raises:
            Exception: The last exception if all retries are exhausted.
        """
        last_error = None

        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                error_type = self.classify_error(e)

                logger.debug(
                    f"Retry attempt {attempt + 1}/{self.max_retries + 1} failed: "
                    f"error_type={error_type.value}, error={str(e)[:200]}"
                )

                # Check if we should retry
                if not self.should_retry(e, attempt):
                    logger.error(
                        f"Error not retryable: error_type={error_type.value}, "
                        f"error={str(e)[:200]}"
                    )
                    raise

                # Calculate backoff time
                backoff_time = self.get_backoff_time(attempt)

                logger.warning(
                    f"Retrying after {backoff_time:.2f}s: attempt={attempt + 1}, "
                    f"error_type={error_type.value}"
                )

                # Wait before retry
                time.sleep(backoff_time)

        # All retries exhausted
        logger.error(
            f"All {self.max_retries + 1} attempts exhausted: "
            f"error={str(last_error)[:200]}"
        )
        raise last_error
