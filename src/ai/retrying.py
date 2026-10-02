"""Retry and error-reporting policy for AI provider calls."""

from __future__ import annotations

from typing import Optional

from tenacity import RetryError


_RETRYABLE_STATUS_CODES = {408, 409, 425, 429}
_RETRYABLE_EXCEPTION_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "RateLimitError",
}


def _status_code(exc: BaseException) -> Optional[int]:
    value = getattr(exc, "status_code", None)
    if value is None:
        response = getattr(exc, "response", None)
        value = getattr(response, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def is_retryable_ai_error(exc: BaseException) -> bool:
    """Return true only for failures that can plausibly recover on retry.

    Authentication, billing, permission, malformed-request, and missing-model
    responses are permanent until configuration or account state changes. In
    particular, retrying HTTP 400 once per collected item hid the useful error
    behind ``tenacity.RetryError`` and multiplied a credit outage into hundreds
    of doomed calls.
    """
    status = _status_code(exc)
    if status is not None:
        return status in _RETRYABLE_STATUS_CODES or status >= 500

    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True

    return type(exc).__name__ in _RETRYABLE_EXCEPTION_NAMES


def describe_ai_error(exc: BaseException) -> str:
    """Preserve the provider's actionable response instead of a wrapper."""
    if isinstance(exc, RetryError):
        last = exc.last_attempt.exception()
        if last is not None:
            exc = last

    message = str(exc).strip() or repr(exc)
    request_id = getattr(exc, "request_id", None)
    if request_id and str(request_id) not in message:
        message = f"{message} (request_id={request_id})"
    return f"{type(exc).__name__}: {message}"
