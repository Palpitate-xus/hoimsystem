"""Fixed recovery guidance and safe attempt metadata for provider failures."""

import logging
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.ai import gateway as gateway_module
from app.ai import text_retry
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.failure_policy import classify_failure
from app.ai.gateway import AIExecutionError, generate
from app.ai.models import AIProvider

PRIVATE = "synthetic-secret-patient-prompt-provider-error"


@pytest.mark.parametrize(
    "status,category,action",
    [
        (401, "authentication", "密钥"),
        (403, "access_denied", "模型权限"),
        (404, "endpoint", "模型名称"),
        (400, "request_invalid", "接口格式"),
        (413, "request_too_large", "输入范围"),
        (422, "request_invalid", "模型参数"),
        (402, "quota", "账单"),
        (429, "rate_limit", "限流"),
        (500, "upstream_error", "运行状态"),
        (501, "upstream_error", "运行状态"),
        (502, "temporary_unavailable", "暂时不可用"),
        (503, "temporary_unavailable", "暂时不可用"),
        (504, "temporary_unavailable", "暂时不可用"),
        (505, "upstream_error", "运行状态"),
        (301, "redirect", "重定向"),
        (302, "redirect", "直接访问"),
        (307, "redirect", "接口地址"),
        (308, "redirect", "接口地址"),
    ],
)
def test_http_failures_identify_the_action_instead_of_recommending_the_same_retry(status, category, action):
    actual_category, message = classify_failure("PROVIDER_HTTP_ERROR", http_status=status)
    assert actual_category == category
    assert action in message
    assert PRIVATE not in message
    if status in {400, 401, 402, 403, 404, 413, 422}:
        assert "手动重新生成" not in message


@pytest.mark.parametrize(
    "code,category,action",
    [
        ("PROVIDER_CONFIGURATION", "configuration", "凭据"),
        ("INVALID_PROVIDER_RESPONSE", "invalid_response", "结构化输出"),
        ("INCOMPLETE_RESPONSE", "incomplete_response", "输出长度"),
        ("MODEL_REFUSAL", "refusal", "使用策略"),
        ("PROVIDER_UNAVAILABLE", "connection", "服务进程"),
    ],
)
def test_known_provider_and_result_errors_have_specific_fixed_guidance(code, category, action):
    actual_category, message = classify_failure(code)
    assert actual_category == category and action in message
    assert PRIVATE not in message


def test_long_retry_after_requires_waiting_instead_of_an_immediate_manual_resend():
    category, message = classify_failure("PROVIDER_HTTP_ERROR", http_status=429, stop_reason="retry_after_limit")
    assert category == "rate_limit"
    assert "等待较长时间" in message and "稍后" in message
    assert "已用完" not in message


@pytest.mark.parametrize("code", ["PROVIDER_TIMEOUT", "RESEARCH_PROVIDER_TIMEOUT", "OPERATIONS_PROVIDER_TIMEOUT"])
def test_timeouts_explain_that_the_provider_may_still_be_processing_the_task(code):
    category, message = classify_failure(code)
    assert category == "timeout"
    assert "先查看任务记录" in message and "服务端执行情况" in message
    assert "手动重新生成" not in message


@pytest.mark.parametrize("code", ["PROVIDER_UNAVAILABLE", "NATIVE_PROVIDER_DELIVERY_FAILED"])
def test_unknown_delivery_guides_the_user_to_check_task_records_before_regenerating(code):
    category, message = classify_failure(code, cause="delivery_unknown")
    assert category == "delivery_unknown"
    assert "先查看任务记录" in message and "确认后" in message
    assert "稍后手动重新生成" not in message


def test_a_total_deadline_expiration_takes_precedence_over_an_earlier_transient_status():
    category, message = classify_failure("PROVIDER_HTTP_ERROR", http_status=503, stop_reason="deadline")
    assert category == "timeout"
    assert "总时限" in message and "先查看任务记录" in message


def test_authority_change_takes_precedence_over_the_upstream_http_failure():
    category, message = classify_failure("PROVIDER_HTTP_ERROR", http_status=401, stop_reason="task_authority_changed")
    assert category == "task_changed"
    assert "刷新任务" in message and "执行租约" in message
    assert "手动重新生成" not in message


def test_a_completed_response_keeps_the_actual_validation_error_instead_of_http_guidance():
    category, message = classify_failure("INVALID_PROVIDER_RESPONSE", http_status=200)
    assert category == "invalid_response"
    assert "结构化输出" in message


@pytest.mark.parametrize("code", ["DOCUMENT_PROVIDER_REPLY_INVALID", "VARIABLE_RESULT_REJECTED", "UNKNOWN_NATIVE_CODE", PRIVATE, None, True, {"untrusted": PRIVATE}])
def test_unknown_native_codes_leave_the_existing_domain_message_to_the_caller(code):
    category, message = classify_failure(code)
    assert category == "domain_error" and message is None
    assert PRIVATE not in category


@pytest.mark.parametrize("status", [PRIVATE, "401", 401.0, True, None, -1, 200, 600, {"untrusted": PRIVATE}])
def test_unknown_or_malformed_status_is_not_echoed_or_coerced(status):
    category, message = classify_failure(PRIVATE, http_status=status, stop_reason=PRIVATE, cause=PRIVATE)
    assert category == "domain_error" and message is None
    assert PRIVATE not in category


@pytest.mark.parametrize("attempts,low,high", [(1, 0.125, 0.25), (2, 0.25, 0.5), (3, 0.5, 1.0), (10, 1.0, 2.0)])
def test_equal_jitter_varies_inside_the_bounded_window(monkeypatch, attempts, low, high):
    observed, delays = [], []
    for edge in (0, 1):
        def choose(lower, upper):
            observed.append((lower, upper))
            return upper if edge else lower

        monkeypatch.setattr(text_retry.random, "uniform", choose)
        delays.append(text_retry.retry_delay(None, attempts))
    assert observed == [(low, high), (low, high)]
    assert delays == [low, high]


@pytest.mark.parametrize("edge", ["minimum", "maximum"])
def test_retry_after_is_a_minimum_even_when_the_jitter_draw_is_shorter(monkeypatch, edge):
    monkeypatch.setattr(text_retry.random, "uniform", lambda low, high: low if edge == "minimum" else high)
    assert text_retry.retry_delay("1", 1) == 1.0
    assert text_retry.retry_delay("2", 1) == 2.0


def test_http_date_retry_after_uses_the_same_minimum_and_refuses_waits_above_the_cap(monkeypatch):
    now = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(text_retry, "datetime", FrozenDateTime)
    monkeypatch.setattr(text_retry.random, "uniform", lambda low, high: low)
    assert text_retry.retry_delay(format_datetime(now + timedelta(seconds=1), usegmt=True), 1) == 1.0
    assert text_retry.retry_delay(format_datetime(now + timedelta(seconds=3), usegmt=True), 1) is None


@pytest.mark.parametrize("header", ["3", "60", "999999999999", "9" * 1000])
def test_retry_after_above_the_cap_stops_instead_of_shortening_the_required_wait(header):
    assert text_retry.retry_delay(header, 1) is None


async def fail_through_gateway(transport):
    provider = AIProvider(
        kind="chat",
        api_base="http://localhost:11434/v1",
        model="synthetic-failure-guidance",
        api_key_env="",
        api_key_encrypted="",
        timeout_seconds=3,
        max_attempts=3,
        max_output_tokens=2000,
        temperature=0.2,
    )
    return await generate(provider, FEATURE_BY_KEY["patient_summary"], "合成任务", {"input": {"question": PRIVATE}}, transport=transport)


@pytest.mark.asyncio
async def test_long_rate_limit_keeps_attempt_metadata_and_safe_logs_without_a_second_call(caplog):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "60"}, text=PRIVATE)

    caplog.set_level(logging.DEBUG)
    with pytest.raises(AIExecutionError) as caught:
        await fail_through_gateway(httpx.MockTransport(respond))
    error = caught.value
    assert error.code == "PROVIDER_HTTP_ERROR"
    assert (error.attempts, error.max_attempts) == (1, 3)
    assert error.retry_exhausted and error.retry_stop_reason == "retry_after_limit"
    expected_details = dict(attempts=1, max_attempts=3, earlier_usage_unknown=False, stop_reason="retry_after_limit", failure_category="rate_limit", http_status=429)
    assert all(error.retry_details.get(key) == value for key, value in expected_details.items())
    assert len(requests) == 1
    assert "限流" in error.message and "等待" in error.message
    assert PRIVATE not in str(error) and PRIVATE not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,code,category",
    [(httpx.ReadTimeout, "PROVIDER_TIMEOUT", "timeout"), (httpx.WriteTimeout, "PROVIDER_TIMEOUT", "timeout"), (httpx.ReadError, "PROVIDER_UNAVAILABLE", "delivery_unknown"), (httpx.WriteError, "PROVIDER_UNAVAILABLE", "delivery_unknown"), (httpx.RemoteProtocolError, "PROVIDER_UNAVAILABLE", "delivery_unknown")],
)
async def test_delivery_failures_keep_unknown_usage_and_point_to_task_records_without_replaying(caplog, failure, code, category):
    requests = []

    def respond(request):
        requests.append(request)
        raise failure(PRIVATE, request=request)

    caplog.set_level(logging.DEBUG)
    with pytest.raises(AIExecutionError) as caught:
        await fail_through_gateway(httpx.MockTransport(respond))
    error = caught.value
    assert error.code == code
    assert (error.attempts, error.max_attempts) == (1, 3)
    assert not error.retry_exhausted and len(requests) == 1
    expected_details = dict(attempts=1, max_attempts=3, earlier_usage_unknown=False, stop_reason="delivery_interrupted", failure_category=category)
    assert all(error.retry_details.get(key) == value for key, value in expected_details.items())
    assert "http_status" not in error.retry_details
    assert error.input_tokens is None and error.output_tokens is None
    assert "先查看任务记录" in error.message
    assert PRIVATE not in str(error) and PRIVATE not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("layer", ["envelope", "model_content"])
async def test_excessively_nested_json_is_a_single_safe_provider_error_with_known_inner_usage(layer, caplog, monkeypatch):
    nested = "[" * 1100 + "0" + "]" * 1100
    requests = []

    def respond(request):
        requests.append(request)
        if layer == "envelope":
            return httpx.Response(200, content=nested.encode(), headers={"Content-Type": "application/json"})
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": nested}}], "usage": {"prompt_tokens": 3, "completion_tokens": 5}})

    caplog.set_level(logging.DEBUG)
    for force_recursion in (False, True):
        requests.clear()
        with monkeypatch.context() as context:
            if force_recursion:
                original_loads = gateway_module.json.loads

                def raise_recursion_for_nested_value(value, *args, **kwargs):
                    text = value.decode() if isinstance(value, (bytes, bytearray)) else value
                    if text == nested:
                        raise RecursionError(PRIVATE)
                    return original_loads(value, *args, **kwargs)

                context.setattr(gateway_module.json, "loads", raise_recursion_for_nested_value)
            with pytest.raises(AIExecutionError) as caught:
                await fail_through_gateway(httpx.MockTransport(respond))
        error = caught.value
        # Decoder nesting limits differ across Python releases. If decoding
        # succeeds, the deeply nested list still fails the result schema.
        assert error.code in ({"INVALID_PROVIDER_RESPONSE"} if force_recursion else {"INVALID_OUTPUT", "INVALID_PROVIDER_RESPONSE"})
        assert len(requests) == 1 and error.attempts == 1
        assert (error.input_tokens, error.output_tokens) == ((3, 5) if layer == "model_content" else (None, None))
        assert PRIVATE not in str(error) and PRIVATE not in caplog.text
        assert nested not in str(error) and nested not in caplog.text


@pytest.mark.asyncio
async def test_transient_response_close_failure_reports_unknown_delivery_without_resending(caplog, monkeypatch):
    from tests.test_ai_text_retry_cleanup import PRIVATE as CLEANUP_PRIVATE
    from tests.test_ai_text_retry_cleanup import TrackedStream, TrackedTransport

    monkeypatch.setattr(text_retry, "BASE_DELAY_SECONDS", 0)
    transport = TrackedTransport(TrackedStream(fail_close=True), status=503)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(AIExecutionError) as caught:
        await fail_through_gateway(transport)
    error = caught.value
    assert error.code == "PROVIDER_UNAVAILABLE"
    assert transport.requests == 1 and error.attempts == 1
    assert error.retry_details["failure_category"] == "delivery_unknown"
    assert error.retry_details["stop_reason"] == "delivery_interrupted"
    assert "先查看任务记录" in error.message
    assert PRIVATE not in str(error) and PRIVATE not in caplog.text
    assert CLEANUP_PRIVATE not in str(error) and CLEANUP_PRIVATE not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_exhausted_connection_timeouts_report_network_failure_without_claiming_the_total_deadline(caplog, monkeypatch):
    requests = []

    def respond(request):
        requests.append(request)
        raise httpx.ConnectTimeout(PRIVATE, request=request)

    monkeypatch.setattr(text_retry, "BASE_DELAY_SECONDS", 0)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(AIExecutionError) as caught:
        await fail_through_gateway(httpx.MockTransport(respond))
    error = caught.value
    assert error.code == "PROVIDER_TIMEOUT"
    assert len(requests) == 3 and (error.attempts, error.max_attempts) == (3, 3)
    assert error.retry_exhausted and error.retry_stop_reason == "connection_failure"
    assert error.retry_details["failure_category"] == "connection"
    assert "网络" in error.message and "接口地址" in error.message
    assert "本次总时限" not in error.message
    assert PRIVATE not in str(error) and PRIVATE not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
