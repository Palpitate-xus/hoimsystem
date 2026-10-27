"""Real HTTPX retry boundaries and worker persistence with synthetic responses."""

import asyncio
import json
import time
from types import SimpleNamespace

import httpx
import pytest

from app.ai import text_retry
from app.ai.gateway import AIExecutionError
from app.ai.models import AIAuditEvent, AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure, successful_transport


@pytest.fixture(autouse=True)
def short_backoff(monkeypatch):
    monkeypatch.setattr(text_retry, "BASE_DELAY_SECONDS", 0)


@text_retry.text_retries()
async def call(provider, *, transport=None, receipt=False):
    try:
        async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False) as client:
            async with client.stream("POST", "http://localhost/v1/chat/completions", json={"synthetic": True}) as response:
                if response.status_code != 200:
                    raise AIExecutionError("PROVIDER_HTTP_ERROR", "模型服务返回失败状态")
                raw = await response.aread()
        value = json.loads(raw)
        if value != {"ok": True}:
            raise AIExecutionError("INVALID_OUTPUT", "模型结果结构已拒绝")
        if receipt:
            return value, dict(input_tokens=5, output_tokens=7, complete=True, model_call_attempted=True), 1
        return value, 5, 7
    except httpx.HTTPError as exc:
        raise AIExecutionError("PROVIDER_UNAVAILABLE", "模型调用未完整返回") from exc


def provider(**changes):
    return SimpleNamespace(kind="chat", max_attempts=3, timeout_seconds=3, **changes)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", (429, 502, 503, 504))
@pytest.mark.parametrize("receipt", (False, True))
async def test_transient_http_then_success_keeps_entire_attempt_usage_unknown(status, receipt):
    bodies = []

    def respond(request):
        bodies.append(bytes(request.content))
        return httpx.Response(status if len(bodies) < 3 else 200, json={"ok": True})

    result = await call(provider(), transport=httpx.MockTransport(respond), receipt=receipt)
    assert len(bodies) == 3 and len(set(bodies)) == 1 and result[0] == {"ok": True}
    if receipt:
        assert result[1] == dict(input_tokens=None, output_tokens=None, complete=False, model_call_attempted=True)
    else:
        assert result[1:] == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", (400, 401, 403, 404, 422, 500))
async def test_nontransient_http_never_replays_or_echoes_provider_body(status):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(status, text="private-provider-response-not-for-users")

    with pytest.raises(AIExecutionError) as caught:
        await call(provider(), transport=httpx.MockTransport(respond))
    assert len(requests) == 1 and caught.value.code == "PROVIDER_HTTP_ERROR"
    assert caught.value.attempts == 1 and "1/3" in caught.value.message
    assert "private-provider" not in caught.value.message


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", (httpx.ConnectError, httpx.ConnectTimeout))
async def test_failed_connection_establishment_can_retry_without_discarding_final_known_usage(failure):
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) < 3:
            raise failure("synthetic", request=request)
        return httpx.Response(200, json={"ok": True})

    result = await call(provider(), transport=httpx.MockTransport(respond))
    assert len(requests) == 3 and result[1:] == (5, 7)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", (httpx.ReadTimeout, httpx.WriteTimeout, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError))
async def test_delivery_or_partial_response_failures_do_not_replay(failure):
    requests = []

    def respond(request):
        requests.append(request)
        raise failure("synthetic", request=request)

    with pytest.raises(AIExecutionError) as caught:
        await call(provider(), transport=httpx.MockTransport(respond))
    assert len(requests) == 1 and caught.value.attempts == 1
    assert caught.value.input_tokens is None and caught.value.output_tokens is None


@pytest.mark.asyncio
async def test_exhaustion_has_safe_attempt_count_and_unknown_usage():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(503, text="private-provider-body")

    with pytest.raises(AIExecutionError) as caught:
        await call(provider(), transport=httpx.MockTransport(respond))
    assert len(requests) == 3 and caught.value.retry_exhausted
    assert "3/3" in caught.value.message and "手动" in caught.value.message
    assert caught.value.input_tokens is None and "private-provider" not in str(caught.value)


@pytest.mark.asyncio
async def test_shared_to_specialized_gateway_delegation_uses_one_attempt_budget():
    @text_retry.text_retries()
    async def delegate(provider, *, transport=None):
        return await call(provider, transport=transport)

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(503)

    with pytest.raises(AIExecutionError) as caught:
        await delegate(provider(), transport=httpx.MockTransport(respond))
    assert len(requests) == 3 and caught.value.attempts == 3
    assert caught.value.message.count("3/3") == 1


@pytest.mark.asyncio
async def test_invalid_output_is_not_a_retry_trigger():
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": False})

    with pytest.raises(AIExecutionError) as caught:
        await call(provider(), transport=httpx.MockTransport(respond))
    assert len(requests) == 1 and caught.value.code == "INVALID_OUTPUT"


@pytest.mark.asyncio
async def test_header_attempts_share_one_total_deadline():
    requests = []

    async def respond(request):
        requests.append(request)
        await asyncio.sleep(0.035)
        return httpx.Response(503)

    configured = provider()
    configured.timeout_seconds = 0.05
    started = time.monotonic()
    with pytest.raises(AIExecutionError) as caught:
        await call(configured, transport=httpx.MockTransport(respond))
    assert len(requests) == 2 and time.monotonic() - started < 0.2
    assert caught.value.retry_stop_reason == "deadline" and caught.value.retry_exhausted


@pytest.mark.asyncio
async def test_slow_partial_body_deadline_is_not_reset_for_each_chunk():
    class Partial(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(10):
                await asyncio.sleep(0.025)
                yield b" "

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, stream=Partial())

    configured = provider()
    configured.timeout_seconds = 0.05
    with pytest.raises(AIExecutionError) as caught:
        await call(configured, transport=httpx.MockTransport(respond))
    assert len(requests) == 1 and caught.value.retry_stop_reason == "deadline"


@pytest.mark.asyncio
async def test_task_cancellation_or_lost_lease_prevents_the_next_attempt():
    active, requests = True, []

    def respond(request):
        nonlocal active
        requests.append(request)
        active = False
        return httpx.Response(503)

    token = text_retry._LEASE_CHECK.set(lambda: active)
    try:
        with pytest.raises(AIExecutionError) as caught:
            await call(provider(), transport=httpx.MockTransport(respond))
    finally:
        text_retry._LEASE_CHECK.reset(token)
    assert len(requests) == 1 and caught.value.retry_stop_reason == "task_authority_changed"


@pytest.mark.parametrize(("value", "expected"), (("999999999999", None), ("-2", 0), ("nan", 0), ("invalid", 0)))
def test_retry_after_is_bounded_and_invalid_values_do_not_create_unbounded_waits(value, expected):
    assert text_retry.retry_delay(value, 1) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("header_kind", ("numeric", "date", "huge_integer", "past_deadline"))
async def test_valid_retry_after_is_never_shortened_into_an_early_request(header_kind):
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    headers = {"numeric": "60", "huge_integer": "9" * 1000, "date": format_datetime(datetime.now(UTC) + timedelta(seconds=60)), "past_deadline": "1"}
    configured = provider()
    if header_kind == "past_deadline":
        configured.timeout_seconds = 0.05
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(503, headers={"Retry-After": headers[header_kind]})

    with pytest.raises(AIExecutionError) as caught:
        await call(configured, transport=httpx.MockTransport(respond))
    assert len(requests) == 1
    assert caught.value.retry_stop_reason == ("deadline" if header_kind == "past_deadline" else "retry_after_limit")


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ("provider_disabled", "provider_revision", "feature_disabled", "feature_revision", "prompt", "actor_role", "grant"))
async def test_real_worker_rechecks_current_authority_before_any_resend(seed_data, db_session, mutation):
    import datetime
    import uuid

    from app import database
    from app.ai.models import AIFeatureConfig, AIPatientGrant, AIProvider, utcnow
    from app.models import Patient, User

    configured, config = configure(db_session, seed_data)
    actor = seed_data["doctor_user"]
    grant = None
    if mutation == "grant":
        actor = User(username="retry-" + uuid.uuid4().hex[:12], password="synthetic", user_role="doctor")
        db_session.add(actor)
        db_session.flush()
        grant = AIPatientGrant(user_id=actor.user_id, patient_id=seed_data["patient"].patient_id, category="cdss", reason="合成重试授权核查", expires_at=utcnow() + datetime.timedelta(hours=1), created_by=seed_data["super_admin_user"].user_id)
        db_session.add(grant)
        db_session.commit()
    run = create_run(db_session, actor, RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id))
    claim = claim_next_run(db_session)
    requests = []
    original_role, original_permission = seed_data["doctor_user"].user_role, seed_data["patient"].permission

    def respond(request):
        requests.append(request)
        with database.SessionLocal() as other:
            if mutation.startswith("provider"):
                other.query(AIProvider).filter_by(provider_id=configured.provider_id).update({"enabled": 0} if mutation.endswith("disabled") else {"revision": configured.revision + 1})
            elif mutation.startswith("feature"):
                other.query(AIFeatureConfig).filter_by(feature_key=config.feature_key).update({"enabled": 0} if mutation.endswith("disabled") else {"revision": config.revision + 1})
            elif mutation == "prompt":
                other.query(AIFeatureConfig).filter_by(feature_key=config.feature_key).update({"active_prompt_id": "synthetic-missing-prompt"})
            elif mutation == "actor_role":
                other.query(User).filter_by(user_id=seed_data["doctor_user"].user_id).update({"user_role": "patient"})
            else:
                other.query(AIPatientGrant).filter_by(grant_id=grant.grant_id).update({"revoked": 1})
            other.commit()
        return httpx.Response(503)

    try:
        await execute_claimed(*claim, transport=httpx.MockTransport(respond))
    finally:
        with database.SessionLocal() as other:
            other.query(User).filter_by(user_id=seed_data["doctor_user"].user_id).update({"user_role": original_role})
            other.query(Patient).filter_by(patient_id=seed_data["patient"].patient_id).update({"permission": original_permission})
            other.commit()
    assert len(requests) == 1
    db_session.refresh(run)
    assert run.status == "failed" and (run.input_tokens, run.output_tokens) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", ("success_after_http", "exhausted_http", "cancel_before_retry"))
async def test_real_worker_preserves_unknown_usage_and_cancellation_without_duplicate_calls(seed_data, db_session, async_client, auth_headers, scenario):
    from app import database

    configured, _config = configure(db_session, seed_data)
    assert configured.max_attempts == 3
    run = create_run(db_session, seed_data["doctor_user"], RunRequest(feature_key="patient_summary", patient_id=seed_data["patient"].patient_id))
    claim = claim_next_run(db_session)
    assert claim[0] == run.run_id
    seen, successful = [], successful_transport([])

    def respond(request):
        seen.append(request)
        if scenario == "cancel_before_retry":
            with database.SessionLocal() as other:
                other.query(AIRun).filter_by(run_id=run.run_id).update({"status": "cancelled"})
                other.commit()
        if scenario != "success_after_http" or len(seen) < 3:
            return httpx.Response(503)
        return successful.handle_request(request)

    await execute_claimed(*claim, transport=httpx.MockTransport(respond))
    db_session.refresh(run)
    assert run.status == {"success_after_http": "succeeded", "exhausted_http": "failed", "cancel_before_retry": "cancelled"}[scenario]
    assert len(seen) == (1 if scenario == "cancel_before_retry" else 3)
    assert run.input_tokens is None and run.output_tokens is None
    audit = db_session.query(AIAuditEvent).filter_by(target=run.run_id, action="run.text_model.usage").one()
    usage = json.loads(audit.detail_json)
    assert usage["input_tokens"] is None and usage["output_tokens"] is None and not usage["complete"]
    assert usage["attempts"] == len(seen) and usage["model_call_attempted"] is True
    view = await async_client.get("/api/ai/runs/" + run.run_id, headers=auth_headers(seed_data["doctor_user"].username))
    assert view.status_code == 200 and view.json()["data"]["input_tokens"] is None
    if scenario == "exhausted_http":
        assert "3/3" in run.error_message
