"""Actual Source/claim/provider/SQL split view proofs, not Main/JWT yet."""

import hashlib
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import inspect, text

from app.ai import rca_evidence_cancellation as cancel
from app.ai import rca_evidence_contract as c
from app.ai import rca_evidence_execution as execute
from app.ai import rca_evidence_grants as grants
from app.ai import rca_evidence_runtime as runtime
from app.ai import rca_evidence_task_wire_contract as v
from app.ai import rca_evidence_views as views
from app.ai.models import AIRun
from app.models import User
from tests.test_ai_rca_evidence_configuration import configured
from tests.test_ai_rca_evidence_execution import provider_service, setup
from tests.test_ai_rca_evidence_execution import synthetic_host as synthetic_host
from tests.test_ai_rca_evidence_grants import cas
from tests.test_ai_rca_evidence_grants import grant_case as grant_case
from tests.test_ai_rca_evidence_storage import no_task_text


def test_actual_read_only_preview_has_closed_metadata_and_independent_source_locations(grant_case):
    case, db = grant_case, grant_case["db"]
    stored, value, _ = configured(case)
    before = db.query(AIRun).count()
    request = v.RcaPreviewRequest(rca_evidence_case_id=stored.binding.case_id, question="\u2003\t", preview=True)
    preview = views.preview(db, case["actor"], request)
    assert preview.context.rca_evidence_binding == value.binding and preview.model_preview == "no_model_call"
    assert preview.metadata.instructions_digest == stored.metadata.instructions_digest and len(type(preview.metadata).model_fields) == 11
    assert preview.context.source_domain == "published_event_investigation_released_evidence"
    assert db.query(AIRun).count() == before and len(c.utf8(c.canonical(views.response(preview)))) < 65535
    assert "rca_evidence_source" not in preview.context.model_dump() and "case_json" not in c.canonical(preview)


@pytest.mark.parametrize("state", ["queued", "running", "failed", "cancelled"])
def test_actual_non_success_states_keep_null_result_and_nullable_receipt_without_raw_case_in_short_view(grant_case, state):
    case, db = grant_case, grant_case["db"]
    stored, _, current = configured(case)
    identifier = inspect(stored.run).identity[0]
    if state == "running":
        runtime.claim_rca_run(db, identifier)
    elif state == "failed":
        current.provider.model = "changed before claim"
        db.commit()
        runtime.claim_rca_run(db, identifier)
    elif state == "cancelled":
        cancel.stage_cancel(db, case["actor"], identifier)
        db.commit()
    detail = views.run_view(db, case["actor"], identifier)
    assert detail.status == state and detail.result is None and detail.result_reference is None
    assert (detail.input_tokens, detail.output_tokens) == ((0, 0) if state in {"failed", "cancelled"} else (None, None))
    assert detail.usage_receipt_status == ("recorded" if state in {"failed", "cancelled"} else "pending")
    assert views.result_piece(db, case["actor"], identifier)["data"] is None
    assert views.case_piece(db, case["actor"], identifier)["data"]["execution_current"] is False
    assert "identity_secret" not in c.canonical(detail) and "source_json" not in c.canonical(detail)
    assert detail.parts.source.endswith(f"/{identifier}/rca-evidence/source")


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["chat", "responses"])
@pytest.mark.parametrize("missing", [False, True])
async def test_actual_accepted_complete_pieces_trace_raw_bytes_and_exact5_phase_audits(grant_case, kind, missing):
    identifier, lease, owner, _value, factory, active, _state, _reads = setup(grant_case, kind)

    def provider_reply(body):
        if missing:
            del body["usage"]
        return body

    transport, calls = provider_service(kind, provider_reply, active)
    await execute.execute_rca_claimed(identifier, lease, session_factory=factory, transport=transport)
    assert len(calls) == 1
    with factory() as db:
        actor = db.get(User, owner)
        detail = views.run_view(db, actor, identifier)
        summary = views.run_view(db, actor, identifier, False)
        trace = views.trace_view(db, actor, identifier)
        source = views.source_piece(db, actor, identifier)["data"]
        private = views.case_piece(db, actor, identifier)["data"]
        result = views.result_piece(db, actor, identifier)["data"]
        receipt = views.receipt_piece(db, actor, identifier)["data"]
        assert detail.result is None and detail.result_reference is not None and summary.usage_receipt == detail.usage_receipt
        assert result["rca_evidence_draft"]["source_projection_hash"] == c.digest(source)
        assert private["immutable"]["case_id"] == detail.rca_evidence_case_id and private["execution_current"] is False
        assert receipt["usage"]["complete"] is (not missing)
        assert detail.input_tokens == (None if missing else 11) and detail.output_tokens == (None if missing else 13)
        assert detail.usage_receipt_status == "recorded" and detail.usage_receipt.model_call_attempted is True
        artifact = detail.rca_evidence_artifact
        assert len({getattr(trace.phase_audits, key).event_id for key in type(trace.phase_audits).model_fields}) == 5
        for raw_key, anchor in (("input_json", "input_hash"), ("evidence_json", "evidence_hash"), ("context_metadata_json", "metadata_hash")):
            assert hashlib.sha256(getattr(trace.raw_frozen_json, raw_key).encode()).hexdigest() == getattr(artifact, anchor)
        assert json.loads(trace.raw_frozen_json.input_json) == trace.frozen_request.model_dump(mode="json")
        assert trace.parts.source.startswith("/api/ai/admin/") and detail.parts.source.startswith("/api/ai/runs/")
        assert "source_json" not in c.canonical(detail) and "identity_secret" not in c.canonical(detail)
        for piece in (detail, trace, source, private, result, receipt):
            assert len(c.utf8(c.canonical(views.response(piece)))) <= c.MAX_WIRE_BYTES


@pytest.mark.parametrize("reader", [views.run_view, views.trace_view, views.source_piece, views.case_piece, views.result_piece, views.receipt_piece])
def test_purpose_revoked_before_any_view_never_reads_task_body(grant_case, reader):
    case, db = grant_case, grant_case["db"]
    stored, value, _ = configured(case)
    identifier = inspect(stored.run).identity[0]
    grant = grants.grant_detail(db, case["actor"], value.binding.event_grant.grant_id)
    grants.revoke_grant(db, case["actor"], grant.identity.grant_id, cas(grant))
    db.commit()

    def denied():
        with pytest.raises(HTTPException) as failure:
            reader(db, case["actor"], identifier)
        assert failure.value.status_code == 403

    no_task_text(db, denied)


def test_explicit_frozen_source_revocation_never_becomes_ordinary_execution_authority(grant_case):
    from app.ai import rca_evidence_cases as cases

    case, db = grant_case, grant_case["db"]
    stored, value, _ = configured(case)
    identifier = inspect(stored.run).identity[0]
    record = cases.case_detail(db, case["actor"], value.binding.case_id)
    cases.revoke_case(db, case["actor"], value.binding.case_id, cas(record))
    db.commit()
    with pytest.raises(HTTPException) as failure:
        views.run_view(db, case["actor"], identifier)
    assert failure.value.status_code == 409
    trace = views.trace_view(db, case["actor"], identifier)
    assert trace.snapshot_complete and trace.rca_evidence_findings.frozen_task_view
    assert views.case_piece(db, case["actor"], identifier, frozen_audit=True)["data"]["execution_current"] is False


def test_result_and_view_tampering_refuses_instead_of_downgrading_to_generic(grant_case):
    stored, _, _ = configured(grant_case)
    db, identifier = grant_case["db"], inspect(stored.run).identity[0]
    db.execute(text("UPDATE hoimsystem_ai_run SET result_json=:body WHERE run_id=:id"), {"id": identifier, "body": '{"summary":"foreign unaccepted body"}'})
    db.commit()
    with pytest.raises(HTTPException) as failure:
        views.run_view(db, grant_case["actor"], identifier)
    assert failure.value.status_code == 409
