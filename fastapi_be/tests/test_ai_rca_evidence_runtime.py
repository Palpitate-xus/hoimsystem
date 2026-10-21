"""Actual dedicated creation and claim SQL; inference/shared Main added later."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import inspect, text

from app.ai import gateway
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_receipts as receipts
from app.ai import rca_evidence_runtime as runtime
from app.ai import rca_evidence_storage as storage
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.models import AIRun
from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact
from app.ai.schemas import ClinicalContextRequest, OperationalContextRequest, RunRequest
from app.config import settings
from tests.test_ai_rca_evidence_configuration import configured
from tests.test_ai_rca_evidence_grants import cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_storage import no_task_text, task_counts


@pytest.fixture(autouse=True)
def synthetic_provider_host(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "synthetic.invalid")


def request(value, **changes):
    return RunRequest.model_validate({"feature_key": "incident_rca", "input": {"rca_evidence_case_id": value.binding.case_id}, "preview": True, **changes})


@pytest.mark.parametrize("question", [None, "", "\u0085\u3000", "补充原样🙂\r\n"])
def test_real_current_configuration_full_wire_preflight_short_create_then_one_actual_claim(grant_case, question):
    case, db = grant_case, grant_case["db"]
    _, value, current = configured(case)
    req = request(value, input={"rca_evidence_case_id": value.binding.case_id, "question": question})
    before = task_counts(db)
    run = runtime.create_rca_run(db, case["actor"], req)
    identifier = inspect(run).identity[0]  # Never reload expired Task TEXT for its ID.
    after = task_counts(db)
    assert tuple(a - b for a, b in zip(after, before, strict=True)) == (1, 1, 0, 1, 0)
    stored = storage.load_task(db, case["actor"], identifier)
    assert stored.snapshot.payload.input.question == question
    assert stored.snapshot.task_prompt == FEATURE_BY_KEY["incident_rca"].task_prompt
    assert stored.snapshot.provider_snapshot.model == current.provider.model
    db.rollback()
    lease = runtime.claim_rca_run(db, identifier)
    row = db.query(AIRcaEvidenceRunArtifact.claim_lease, AIRcaEvidenceRunArtifact.claim_event_id).filter_by(run_id=identifier).one()
    assert lease == row.claim_lease and row.claim_event_id is not None
    assert db.query(AIRun.status).filter_by(run_id=identifier).scalar() == "running"
    before = task_counts(db)
    result, columns = no_task_text(db, lambda: runtime.claim_rca_run(db, identifier))
    assert result is None and not columns and task_counts(db) == before


@pytest.mark.parametrize("failure", ["quota", "disabled", "role"])
def test_native_creation_current_quota_activation_and_role_never_write_a_partial_task(grant_case, failure):
    case, db = grant_case, grant_case["db"]
    _, value, current = configured(case)
    preview = True
    if failure == "quota":
        current.config.daily_limit = 1
    elif failure == "disabled":
        preview = False
    else:
        db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": inspect(case["actor"]).identity[0]})
    db.commit()
    before = task_counts(db)
    with pytest.raises(HTTPException) as rejected:
        runtime.create_rca_run(db, case["actor"], request(value, preview=preview))
    assert rejected.value.status_code == {"quota": 429, "disabled": 409, "role": 403}[failure]
    assert task_counts(db) == before


def test_claim_rechecks_frozen_provider_instead_of_turning_a_changed_task_running(grant_case):
    case, db = grant_case, grant_case["db"]
    _, value, current = configured(case)
    run = runtime.create_rca_run(db, case["actor"], request(value))
    identifier = inspect(run).identity[0]
    current.provider.model = "actual changed provider before claim"
    db.commit()
    before = task_counts(db)
    assert runtime.claim_rca_run(db, identifier) is None
    assert tuple(a - b for a, b in zip(task_counts(db), before, strict=True)) == (0, 0, 0, 1, 0)
    assert db.query(AIRun.status, AIRun.lease_token).filter_by(run_id=identifier).one() == ("failed", None)
    actual = receipts.read_receipt(db, receipts.technical_header(db, identifier))
    assert actual.usage.model_call_attempted is False and actual.usage.complete is True


@pytest.mark.parametrize("loss", ["role", "grant"])
def test_queued_source_or_role_loss_is_known_zero_terminal_not_a_permanently_blocking_claim(grant_case, loss):
    case, db = grant_case, grant_case["db"]
    _, value, _ = configured(case)
    run = runtime.create_rca_run(db, case["actor"], request(value))
    identifier = inspect(run).identity[0]
    if loss == "role":
        db.execute(text("UPDATE hoimsystem_users SET user_role='admin' WHERE user_id=:id"), {"id": inspect(case["actor"]).identity[0]})
    else:
        original = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
        grants.revoke_grant(db, case["actor"], original.identity.grant_id, cas(original))
    db.commit()
    result, columns = no_task_text(db, lambda: runtime.claim_rca_run(db, identifier))
    assert result is None and not columns
    actual = receipts.read_receipt(db, receipts.technical_header(db, identifier))
    assert actual.status == "failed" and actual.claim_event_id is None and actual.dispatch_event_id is None
    assert actual.usage.input_tokens == actual.usage.output_tokens == 0 and actual.usage.model_call_attempted is False


@pytest.mark.parametrize("input_value", [{}, {"rca_evidence_case_id": None}, {"rca_evidence_case_id": "x"}, {"rca_evidence_case_id": "00000000-0000-0000-0000-000000000001", "text": "不接自由原件"}])
def test_request_requires_closed_case_selection(input_value):
    with pytest.raises(ValidationError):
        RunRequest.model_validate({"feature_key": "incident_rca", "input": input_value, "preview": True})


@pytest.mark.parametrize("axis,value", [("preview", 1), ("preview", "true"), ("patient_id", 1), ("patient_id", False), ("encounter_ref", "")])
def test_request_does_not_coerce_preview_or_mixed_patient_encounter(axis, value):
    body = {"feature_key": "incident_rca", "input": {"rca_evidence_case_id": "00000000-0000-0000-0000-000000000001"}, axis: value}
    with pytest.raises(ValidationError):
        RunRequest.model_validate(body)


@pytest.mark.parametrize("value", [None, "00000000-0000-0000-0000-000000000001"])
def test_foreign_feature_never_accepts_rca_reference_even_null(value):
    with pytest.raises(ValidationError):
        RunRequest.model_validate({"feature_key": "patient_summary", "input": {"rca_evidence_case_id": value}})


@pytest.mark.parametrize("feature", ["incident_rca", "patient_summary"])
def test_legacy_clinical_and_operational_previews_never_accept_native_rca_scope(feature):
    identifier = "00000000-0000-0000-0000-000000000001"
    with pytest.raises(ValidationError):
        ClinicalContextRequest.model_validate({"feature_key": feature, "patient_id": 1, "source_refs": {"rca_evidence_case_id": identifier}})
    with pytest.raises(ValidationError):
        OperationalContextRequest.model_validate({"feature_key": feature, "input": {"rca_evidence_case_id": identifier}})


@pytest.mark.asyncio
@pytest.mark.parametrize("axis", ["feature", "input", "binding_null", "source_null", "domain", "selection_null"])
async def test_generic_gateway_refuses_every_native_rca_anchor_before_provider_access_or_http(axis):
    spec = FEATURE_BY_KEY["incident_rca" if axis == "feature" else "patient_summary"]
    data = {"input": {}, "context": {}}
    if axis == "input":
        data["input"]["rca_evidence_case_id"] = None
    elif axis == "binding_null":
        data["context"]["rca_evidence_binding"] = None
    elif axis == "source_null":
        data["context"]["rca_evidence_source"] = None
    elif axis == "domain":
        data["context"]["source_domain"] = "published_event_investigation_released_evidence"
    elif axis == "selection_null":
        data["context"]["selected_sources"] = {"rca_evidence_case_id": None}
    with pytest.raises(gateway.AIExecutionError) as failure:
        await gateway.generate(SimpleNamespace(), spec, "not-used", data)
    assert failure.value.code == "RCA_DEDICATED_PROTOCOL_REQUIRED"
