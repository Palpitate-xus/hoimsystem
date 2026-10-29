"""Keep text response and transport cleanup inside the original request budget."""

import asyncio
import json
import time

import httpx
import pytest

from app.ai import text_retry
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError, generate
from app.ai.models import AIProvider

PRIVATE = "synthetic-private-provider-cleanup-error"
BODY = json.dumps(
    {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps({"summary": "合成摘要", "sections": [{"title": "记录", "content": "合成来源。", "source_ids": ["known"]}], "warnings": [], "missing_data": []})
                },
            }
        ],
        "usage": {"prompt_tokens": 3, "completion_tokens": 5},
    }
).encode()


class TrackedStream(httpx.AsyncByteStream):
    def __init__(self, *, read_delay=0, close_delay=0, fail_read=False, fail_close=False):
        self.read_delay = read_delay
        self.close_delay = close_delay
        self.fail_read = fail_read
        self.fail_close = fail_close
        self.close_calls = 0

    async def __aiter__(self):
        if self.read_delay:
            await asyncio.sleep(self.read_delay)
        if self.fail_read:
            yield BODY[:10]
            raise httpx.ReadError(PRIVATE)
        yield BODY

    async def aclose(self):
        self.close_calls += 1
        if self.close_delay:
            await asyncio.sleep(self.close_delay)
        if self.fail_close:
            raise httpx.ReadError(PRIVATE)


class TrackedTransport(httpx.AsyncBaseTransport):
    def __init__(self, stream, *, status=200, close_delay=0, fail_close=False):
        self.stream = stream
        self.status = status
        self.close_delay = close_delay
        self.fail_close = fail_close
        self.requests = 0
        self.close_calls = 0
        self.started_at = None

    async def handle_async_request(self, request):
        if self.started_at is None:
            self.started_at = time.monotonic()
        self.requests += 1
        return httpx.Response(self.status, stream=self.stream)

    async def aclose(self):
        self.close_calls += 1
        if self.close_delay:
            await asyncio.sleep(self.close_delay)
        if self.fail_close:
            raise httpx.ReadError(PRIVATE)


async def invoke(transport, *, timeout=0.06):
    provider = AIProvider(
        kind="chat",
        api_base="http://localhost:11434/v1",
        model="synthetic-cleanup-boundary",
        api_key_env="",
        api_key_encrypted="",
        timeout_seconds=timeout,
        max_attempts=3,
        max_output_tokens=2000,
        temperature=0.2,
    )
    # Bound a regression which could otherwise leave an unbounded close hanging.
    async with asyncio.timeout(0.8):
        return await generate(provider, FEATURE_BY_KEY["patient_summary"], "合成任务", {"evidence": [{"source_id": "known"}]}, transport=transport)


def assert_closed_once_without_replay(transport):
    assert transport.requests == 1
    assert transport.stream.close_calls == 1
    assert transport.close_calls == 1


@pytest.mark.asyncio
async def test_slow_successful_response_close_expires_the_original_total_deadline():
    transport = TrackedTransport(TrackedStream(close_delay=0.2))
    with pytest.raises(AIExecutionError) as caught:
        await invoke(transport)
    assert caught.value.code == "PROVIDER_TIMEOUT"
    assert transport.started_at is not None
    assert time.monotonic() - transport.started_at < 0.25
    assert_closed_once_without_replay(transport)


@pytest.mark.asyncio
async def test_slow_transport_close_expires_the_original_total_deadline():
    transport = TrackedTransport(TrackedStream(), close_delay=0.2)
    with pytest.raises(AIExecutionError) as caught:
        await invoke(transport)
    assert caught.value.code == "PROVIDER_TIMEOUT"
    assert transport.started_at is not None
    assert time.monotonic() - transport.started_at < 0.25
    assert_closed_once_without_replay(transport)


@pytest.mark.asyncio
@pytest.mark.parametrize("last_close", ["response", "transport"])
async def test_cleanup_shares_the_body_budget_instead_of_starting_a_fresh_timeout(last_close):
    stream = TrackedStream(read_delay=0.04, close_delay=0.04 if last_close == "response" else 0)
    transport = TrackedTransport(stream, close_delay=0.04 if last_close == "transport" else 0)
    with pytest.raises(AIExecutionError) as caught:
        await invoke(transport, timeout=0.06)
    assert caught.value.code == "PROVIDER_TIMEOUT"
    assert_closed_once_without_replay(transport)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["response_close", "transport_close", "body_read"])
async def test_failures_after_response_delivery_are_safe_and_never_replayed(failure):
    transport = TrackedTransport(TrackedStream(fail_read=failure == "body_read", fail_close=failure == "response_close"), fail_close=failure == "transport_close")
    with pytest.raises(AIExecutionError) as caught:
        await invoke(transport)
    assert caught.value.code == "PROVIDER_UNAVAILABLE"
    assert PRIVATE not in str(caught.value)
    assert_closed_once_without_replay(transport)


@pytest.mark.asyncio
async def test_slow_transient_response_cleanup_stops_before_a_second_attempt(monkeypatch):
    monkeypatch.setattr(text_retry, "BASE_DELAY_SECONDS", 0)
    transport = TrackedTransport(TrackedStream(close_delay=0.2), status=503)
    with pytest.raises(AIExecutionError) as caught:
        await invoke(transport)
    assert caught.value.code == "PROVIDER_TIMEOUT"
    assert_closed_once_without_replay(transport)


@pytest.mark.asyncio
async def test_successful_text_request_closes_response_and_transport_once():
    transport = TrackedTransport(TrackedStream())
    result, inputs, outputs = await invoke(transport)
    assert result.summary == "合成摘要"
    assert (inputs, outputs) == (3, 5)
    assert_closed_once_without_replay(transport)
