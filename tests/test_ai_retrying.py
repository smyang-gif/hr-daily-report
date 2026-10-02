"""AI calls retry transient failures but surface permanent errors immediately."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from src.ai.enricher import ContentEnricher
from src.ai.retrying import describe_ai_error, is_retryable_ai_error


class StatusError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize("status", [408, 409, 425, 429, 500, 529])
def test_retryable_status_codes(status: int) -> None:
    assert is_retryable_ai_error(StatusError(status, "temporary"))


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422])
def test_permanent_status_codes_are_not_retried(status: int) -> None:
    assert not is_retryable_ai_error(StatusError(status, "permanent"))


def test_error_description_keeps_provider_message_and_request_id() -> None:
    error = StatusError(400, "credit balance is too low")
    error.request_id = "req_123"

    assert describe_ai_error(error) == (
        "StatusError: credit balance is too low (request_id=req_123)"
    )


def _enricher(client) -> ContentEnricher:  # type: ignore[no-untyped-def]
    enricher = ContentEnricher.__new__(ContentEnricher)
    enricher.client = client
    return enricher


def test_enricher_does_not_retry_http_400() -> None:
    calls = 0

    async def complete(**_):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        raise StatusError(400, "credit balance is too low")

    enricher = _enricher(SimpleNamespace(complete=complete))

    with pytest.raises(StatusError, match="credit balance"):
        asyncio.run(enricher._complete(system="s", user="u"))
    assert calls == 1


def test_enricher_retries_transient_failure() -> None:
    calls = 0

    async def complete(**_):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls < 3:
            raise StatusError(529, "overloaded")
        return "ok"

    enricher = _enricher(SimpleNamespace(complete=complete))

    assert asyncio.run(enricher._complete(system="s", user="u")) == "ok"
    assert calls == 3
