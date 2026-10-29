"""Finite transient retries for text requests before response delivery begins."""

import asyncio
import functools
import inspect
import json
import logging
import math
import random
from contextvars import ContextVar
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.ai.failure_policy import classify_failure
from app.ai.retry_policy import configured_attempts

TRANSIENT_STATUSES = frozenset({429, 502, 503, 504})
BASE_DELAY_SECONDS = 0.25
MAX_DELAY_SECONDS = 2.0
_LEASE_CHECK = ContextVar("text_retry_lease_check", default=None)
logger = logging.getLogger("ai.text_retry")


def _task_state(db, run_id, lease):
    from app.ai.models import AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
    from app.models import User

    row = db.query(AIRun.feature_key, AIRun.provider_id, AIRun.requested_by, AIRun.status, AIRun.lease_token, AIRun.preview, AIRun.provider_revision, AIRun.prompt_version).filter_by(run_id=run_id).one_or_none()
    if row is None or row.status != "running" or row.lease_token != lease:
        return None
    config = db.query(*AIFeatureConfig.__table__.columns).filter_by(feature_key=row.feature_key).one_or_none()
    provider = db.query(*AIProvider.__table__.columns).filter_by(provider_id=row.provider_id).one_or_none()
    actor = db.query(User.username, User.user_role, User.token_invalid_before).filter_by(user_id=row.requested_by).one_or_none()
    if config is None or provider is None or actor is None or provider.enabled != 1 or (not row.preview and config.enabled != 1):
        return None
    roles = json.loads(config.allowed_roles_json)
    if type(roles) is not list or actor.user_role not in roles:
        return None
    prompt = db.query(AIPromptVersion.prompt_id, AIPromptVersion.feature_key, AIPromptVersion.version, AIPromptVersion.task_prompt).filter_by(prompt_id=config.active_prompt_id).one_or_none() if config.active_prompt_id else None
    return tuple(row), tuple(config), tuple(provider), tuple(actor), tuple(prompt) if prompt is not None else None


def _current_source_authority(db, run_id):
    """Reuse native source-first execution guards; never read accepted results."""
    import importlib

    from sqlalchemy import select
    from sqlalchemy.orm import attributes, defer

    from app.ai.models import AIRun
    from app.models import User
    from app.sql_text import UTF8Bytes

    run = db.query(AIRun).options(defer(AIRun.result_json, raiseload=True)).filter_by(run_id=run_id).one()
    # Classifiers need only the pristine marker: prove its exact two UTF-8
    # bytes in SQL, without fetching any result text or changing saved data.
    pristine = db.scalar(select((AIRun.result_json == "{}") & (UTF8Bytes(AIRun.result_json) == 2)).where(AIRun.run_id == run_id))
    if pristine is not True and pristine != 1:
        raise ValueError("A text retry requires the original empty result marker")
    attributes.set_committed_value(run, "result_json", "{}")
    actor = db.query(User).filter_by(user_id=run.requested_by).one()
    entry = {
        "guideline_ingestion": ("document_extraction_runtime", "recheck", "run"),
        "guideline_change_review": ("document_change_runtime", "recheck", "run"),
        "drug_label_extraction": ("drug_label_runtime", "recheck", "label"),
        "charge_reconciliation": ("charge_reconciliation_runtime", "recheck", "run"),
        "feedback_analysis": ("satisfaction_runtime", "recheck", "run"),
        "clinical_training": ("clinical_training_storage", "load_artifact", "execution"),
        "operations_support": ("operations_support_storage", "load_artifact", "execution"),
        "research_cohort": ("research_cohort_storage", "load_artifact", "execution"),
        "deidentification": ("deidentification_storage", "load_snapshot", "execution"),
        "research_extraction": ("research_variables_task_reader", "load_task", "for_execution"),
        "incident_rca": ("rca_evidence_configuration", "for_execution", "rca"),
    }.get(run.feature_key)
    if entry is None:
        from app.ai.runtime import _recheck_task

        _recheck_task(db, run)
        return
    module, name, mode = entry
    guard = getattr(importlib.import_module("app.ai." + module), name)
    if mode == "run":
        guard(db, run)
    elif mode == "label":
        from app.ai.drug_label_storage import load_snapshot

        guard(db, load_snapshot(db, run_id))
    elif mode == "rca":
        guard(db, actor, run_id, exclusive=False)
    else:
        guard(db, actor, run_id, **{mode: True})


def task_retry_scope(call):
    """Bind production shared/native dispatch retries to the original lease."""
    @functools.wraps(call)
    async def scoped(run_id, lease, *args, **kwargs):
        from app import database

        try:
            with database.SessionLocal() as db:
                original = _task_state(db, run_id, lease)
        except Exception:
            original = None

        def still_active():
            try:
                with database.SessionLocal() as db:
                    from sqlalchemy import event
                    from sqlalchemy.orm import defer

                    from app.ai.models import AIRun

                    def source_only(state):
                        if state.is_select and any(description.get("expr") is AIRun for description in getattr(state.statement, "column_descriptions", ())):
                            state.statement = state.statement.options(defer(AIRun.result_json, raiseload=True))

                    event.listen(db, "do_orm_execute", source_only)
                    if original is None or _task_state(db, run_id, lease) != original:
                        return False
                    _current_source_authority(db, run_id)
                    return True
            except Exception:
                return False

        token = _LEASE_CHECK.set(still_active)
        try:
            return await call(run_id, lease, *args, **kwargs)
        finally:
            _LEASE_CHECK.reset(token)

    return scoped


def _get(provider, key, default=None):
    return provider.get(key, default) if isinstance(provider, dict) else getattr(provider, key, default)


def retry_delay(value, attempts):
    ceiling = min(BASE_DELAY_SECONDS * 2 ** (attempts - 1), MAX_DELAY_SECONDS)
    # Equal jitter spreads concurrent retries. Retry-After is a minimum and
    # never gets shortened by jitter or by this request's remaining budget.
    delay = random.uniform(ceiling / 2, ceiling)
    if value:
        if value.isascii() and value.isdecimal() and len(value) > 10:
            return None
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                seconds = (date - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                seconds = 0
        if math.isfinite(seconds):
            if seconds > MAX_DELAY_SECONDS:
                return None
            delay = max(delay, max(seconds, 0))
    return delay


class _DeadlineStream(httpx.AsyncByteStream):
    def __init__(self, stream, policy, request):
        self.stream, self.policy, self.request = stream, policy, request
        self.closed = False

    async def __aiter__(self):
        try:
            async with asyncio.timeout_at(self.policy.deadline):
                async for chunk in self.stream:
                    yield chunk
        except TimeoutError as exc:
            self.policy.stop_reason = "deadline"
            self.policy.exhausted = True
            self.policy.cause = "delivery_unknown"
            raise httpx.ReadTimeout("Text provider total deadline exceeded", request=self.request) from exc
        except httpx.HTTPError:
            self.policy.stop_reason = "delivery_interrupted"
            self.policy.cause = "delivery_unknown"
            raise

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        try:
            async with asyncio.timeout_at(self.policy.deadline):
                await self.stream.aclose()
        except TimeoutError as exc:
            self.policy.stop_reason, self.policy.exhausted = "deadline", True
            self.policy.cause = "delivery_unknown"
            raise httpx.ReadTimeout("Text provider total deadline exceeded", request=self.request) from exc
        except httpx.HTTPError:
            self.policy.stop_reason = "delivery_interrupted"
            self.policy.cause = "delivery_unknown"
            raise


class TextRetryTransport(httpx.AsyncBaseTransport):
    def __init__(self, provider, transport=None):
        self.transport = transport
        self.max_attempts = configured_attempts(provider)
        self.timeout_seconds = _get(provider, "timeout_seconds")
        self.attempts = 0
        self.usage_unknown = False
        self.exhausted = False
        self.stop_reason = "not_started"
        self.deadline = None
        self.lease_check = _LEASE_CHECK.get()
        self.closed = False
        self.http_status = None
        self.cause = None

    def details(self, code=None, *, succeeded=False):
        category, _ = classify_failure(code, http_status=self.http_status, stop_reason=self.stop_reason, cause=self.cause)
        details = dict(attempts=self.attempts, max_attempts=self.max_attempts, earlier_usage_unknown=self.usage_unknown, stop_reason=self.stop_reason, failure_category="success" if succeeded else category)
        if self.http_status is not None:
            details["http_status"] = self.http_status
        return details

    def log_retry(self, delay):
        logger.info("text_model_retry attempt=%d max_attempts=%d http_status=%s cause=%s delay_seconds=%.3f", self.attempts, self.max_attempts, self.http_status, self.cause or "temporary_http", delay)

    async def handle_async_request(self, request):
        loop = asyncio.get_running_loop()
        if self.transport is None:
            self.transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False)
        if self.deadline is None:
            self.deadline = loop.time() + self.timeout_seconds
        # Only rewindable JSON text is eligible. Never replay file/multipart
        # streams even if an incorrect caller supplied a text-kind provider.
        allowed = self.max_attempts if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() == "application/json" else 1
        try:
            async with asyncio.timeout_at(self.deadline):
                await request.aread()
                while True:
                    if self.attempts >= allowed:
                        self.exhausted = True
                        self.stop_reason = "attempt_limit"
                        raise httpx.RequestError("Text provider attempt limit exhausted", request=request)
                    if self.attempts and self.lease_check is not None and not await asyncio.to_thread(self.lease_check):
                        self.stop_reason = "task_authority_changed"
                        raise httpx.RequestError("Text retry stopped because current task authority is inactive", request=request)
                    if loop.time() >= self.deadline:
                        self.stop_reason, self.exhausted = "deadline", True
                        raise httpx.ReadTimeout("Text provider total deadline exceeded", request=request)
                    self.attempts += 1
                    self.stop_reason = "response_received"
                    self.http_status = self.cause = None
                    try:
                        response = await self.transport.handle_async_request(request)
                    except (httpx.ConnectError, httpx.ConnectTimeout):
                        self.stop_reason = "connection_failure"
                        self.cause = "connection_failure"
                        if self.attempts >= allowed:
                            self.exhausted = True
                            raise
                        delay = retry_delay(None, self.attempts)
                        if loop.time() + delay >= self.deadline:
                            self.exhausted = True
                            self.stop_reason = "deadline"
                            raise
                        self.log_retry(delay)
                        await asyncio.sleep(delay)
                        continue
                    except httpx.HTTPError:
                        self.stop_reason = "delivery_interrupted"
                        self.cause = "delivery_unknown"
                        raise
                    self.http_status = response.status_code
                    if response.status_code in TRANSIENT_STATUSES:
                        self.stop_reason = "temporary_http"
                        delay = retry_delay(response.headers.get("retry-after"), self.attempts)
                        if delay is None or self.attempts >= allowed or loop.time() + delay >= self.deadline:
                            self.exhausted = True
                            if delay is None:
                                self.stop_reason = "retry_after_limit"
                            elif self.attempts < allowed:
                                self.stop_reason = "deadline"
                        else:
                            # No response body is delivered to a parser. Its
                            # possible billable usage cannot be reconstructed
                            # from a later successful attempt's receipt.
                            self.usage_unknown = True
                            try:
                                await response.aclose()
                            except httpx.HTTPError:
                                self.stop_reason = "delivery_interrupted"
                                self.cause = "delivery_unknown"
                                raise
                            self.log_retry(delay)
                            await asyncio.sleep(delay)
                            continue
                    response.stream = _DeadlineStream(response.stream, self, request)
                    return response
        except TimeoutError as exc:
            self.stop_reason, self.exhausted = "deadline", True
            self.cause = "delivery_unknown"
            raise httpx.ReadTimeout("Text provider total deadline exceeded", request=request) from exc

    async def aclose(self):
        if self.closed:
            return
        self.closed = True
        if self.transport is not None:
            try:
                async with asyncio.timeout_at(self.deadline):
                    await self.transport.aclose()
            except TimeoutError as exc:
                self.stop_reason, self.exhausted = "deadline", True
                self.cause = "delivery_unknown"
                raise httpx.ReadTimeout("Text provider total deadline exceeded") from exc
            except httpx.HTTPError:
                self.stop_reason = "delivery_interrupted"
                self.cause = "delivery_unknown"
                raise


def _unknown_receipt(value):
    return {**value, "input_tokens": None, "output_tokens": None, "complete": False, **({"model_call_attempted": True} if "model_call_attempted" in value else {})}


class _Reply(tuple):
    def __new__(cls, values, policy):
        reply = super().__new__(cls, values)
        reply.retry_details = policy.details(succeeded=True)
        return reply


def text_retries(*, provider_argument="provider", frozen_snapshot=False):
    """Keep each existing parser and result/error type; retry only transport."""
    def decorate(call):
        signature = inspect.signature(call)

        @functools.wraps(call)
        async def bounded(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            # Shared dispatch delegates some text domains to another decorated
            # gateway. One logical call owns one budget, deadline and receipt.
            if isinstance(bound.arguments.get("transport"), TextRetryTransport):
                return await call(*args, **kwargs)
            provider = bound.arguments.get(provider_argument)
            if frozen_snapshot:
                provider = _get(provider, "provider_snapshot")
            if _get(provider, "kind") not in {"chat", "responses"} or any(bound.arguments.get(field) is not None for field in ("audio", "image", "ecg")):
                return await call(*args, **kwargs)
            policy = TextRetryTransport(provider, bound.arguments.get("transport"))
            bound.arguments["transport"] = policy
            try:
                result = await call(*bound.args, **bound.kwargs)
                if policy.usage_unknown:
                    if isinstance(result[1], dict):
                        result = result[0], _unknown_receipt(result[1]), result[2]
                    else:
                        result = result[0], None, None
                return _Reply(result, policy)
            except Exception as exc:
                if policy.attempts:
                    exc.model_call_attempted = True
                    exc.attempts = policy.attempts
                    exc.max_attempts = policy.max_attempts
                    exc.retry_exhausted = policy.exhausted
                    exc.retry_stop_reason = policy.stop_reason
                    exc.retry_details = policy.details(getattr(exc, "code", None))
                    if policy.usage_unknown:
                        exc.input_tokens = exc.output_tokens = None
                        for field in ("usage", "usage_receipt"):
                            receipt = getattr(exc, field, None)
                            if isinstance(receipt, dict):
                                setattr(exc, field, _unknown_receipt(receipt))
                    if hasattr(exc, "message"):
                        _, guidance = classify_failure(getattr(exc, "code", None), http_status=policy.http_status, stop_reason=policy.stop_reason, cause=policy.cause)
                        message = guidance or exc.message.replace("未自动重试", "未继续重试").replace("未重试", "未继续重试")
                        status = f"HTTP {policy.http_status}；" if policy.http_status is not None and policy.http_status != 200 else ""
                        exc.message = f"{message}（{status}已尝试{policy.attempts}/{policy.max_attempts}次）"
                        exc.args = (exc.message,)
                    logger.warning("text_model_failed category=%s attempt=%d max_attempts=%d http_status=%s stop_reason=%s", exc.retry_details["failure_category"], policy.attempts, policy.max_attempts, policy.http_status, policy.stop_reason)
                raise

        return bounded
    return decorate
