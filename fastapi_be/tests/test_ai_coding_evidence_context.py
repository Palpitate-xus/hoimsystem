"""Actual synthetic SQL originals with short bindings and literal draft results."""

# ruff: noqa: F811 -- imported pytest fixtures are injected by their names.

import copy
import json

import pytest
from fastapi import HTTPException

from app.ai.coding_evidence_context import binding_for, coding_context, expand_context, public_payload, selection
from app.ai.coding_evidence_contract import CodingEvidenceDraft
from app.ai.coding_evidence_result import result_for_draft, validate_result
from app.ai.coding_evidence_sources import case_current, review
from tests.test_ai_coding_evidence_sources import NOTE, case, published  # noqa: F401
from tests.test_coding_evidence_legacy_writes import coding_case  # noqa: F401


def selected(row):
    return {"coding_case_id": row.case_snapshot_id}


def bundle_for(db, c, row):
    return coding_context(db, c["doctor_user"], c["patient"].patient_id, c["admission"].admission_id, selected(row))


def draft_for(source, projection_hash):
    document = next((row for row in source["documents"] if row["field"] == "operation_summary"), source["documents"][0])
    return CodingEvidenceDraft(
        schema_version="coding_evidence_draft_v1",
        source_id=source["source_id"],
        source_projection_hash=projection_hash,
        claims=[
            {
                "binding_token": row["binding_token"],
                "model_assessment": "conflict_claim",
                "review_note": "这是合成待复核意见，未作临床确认。",
                "clarification_question": None,
                "citations": [{"document_source_id": document["source_id"], "text_hash": document["text_hash"], "start": 0, "end": len(document["text"]), "quote": document["text"]}],
            }
            for row in source["code_bindings"]
        ],
    )


def test_actual_sql_short_reference_expansion_and_minimal_public_request(db_session, case):
    db, c = db_session, case
    row = published(db, c)
    bundle = bundle_for(db, c, row)
    assert set(bundle.data) == {"scope", "source_domain", "department_ids", "selected_sources", "coding_binding", "scope_note", "missing_data", "truncated_sources", "snapshot_time"}
    assert "snapshot" not in bundle.data and "coding_source" not in bundle.data
    assert "snapshot" not in bundle.data["coding_binding"]
    expanded = expand_context(db, bundle.data, user=c["doctor_user"], current=True)
    model = public_payload({"input": selected(row), "context": expanded})
    assert set(model) == {"coding_source", "source_projection_hash", "question"}
    encoded = json.dumps(model, ensure_ascii=False)
    for secret in (c["patient"].name, c["patient"].identity, c["home"].home_id, c["admission"].admission_id, "expected_amount", "coder_id", "identity_secret"):
        assert secret not in encoded
    assert binding_for(case_current(db, c["doctor_user"], row.case_snapshot_id)) == bundle.data["coding_binding"]
    assert len(bundle.evidence) == 1 and bundle.evidence[0]["source_id"] == expanded["coding_source"]["source_id"]


@pytest.mark.parametrize("scope", ["patient", "admission"])
def test_actual_case_cannot_cross_run_envelope_scope(db_session, case, scope):
    db, c = db_session, case
    row = published(db, c)
    with pytest.raises(HTTPException) as exc:
        coding_context(
            db,
            c["doctor_user"],
            c["patient2"].patient_id if scope == "patient" else c["patient"].patient_id,
            "00000000-0000-0000-0000-000000000000" if scope == "admission" else c["admission"].admission_id,
            selected(row),
        )
    assert exc.value.status_code == 403


@pytest.mark.parametrize("values", [{}, {"coding_case_id": None}, {"coding_case_id": "bad"}, {"coding_case_id": "00000000-0000-0000-0000-000000000000", "home_id": "other"}])
def test_closed_selection_rejects_missing_invalid_or_mixed_source_reference(values):
    with pytest.raises(HTTPException) as exc:
        selection(values)
    assert exc.value.status_code == 422


def test_current_revoke_refuses_ordinary_expansion_super_keeps_frozen_audit(db_session, case):
    db, c = db_session, case
    row = published(db, c)
    bundle = bundle_for(db, c, row)
    source = expand_context(db, bundle.data, user=c["doctor_user"], current=True)["coding_source"]
    review(db, c["super_admin_user"], "case", row.case_snapshot_id, {"expected_revision": 2, "expected_content_hash": row.content_hash, "basis_note": NOTE}, revoke=True)
    db.commit()
    with pytest.raises(HTTPException) as exc:
        expand_context(db, bundle.data, user=c["doctor_user"], current=True)
    assert exc.value.status_code == 409
    audit = expand_context(db, bundle.data, user=c["super_admin_user"], current=False)
    assert audit["coding_source"] == source and audit["coding_case"]["status"] == "revoked"
    assert audit["coding_case"]["frozen_task_view"] and not audit["coding_case"]["can_revoke"]


def test_actual_projection_draft_keeps_citation_text_and_fixed_unreviewed_explanation(db_session, case):
    db, c = db_session, case
    row = published(db, c)
    expanded = expand_context(db, bundle_for(db, c, row).data, user=c["doctor_user"], current=True)
    source, projection_hash = expanded["coding_source"], expanded["coding_binding"]["projection_hash"]
    draft = draft_for(source, projection_hash)
    result = result_for_draft(source, draft, projection_hash).model_dump(mode="json")
    assert validate_result(result, source, projection_hash).model_dump(mode="json") == result
    assert result["coding_analysis"]["claims"][0]["citations"][0]["quote"] == source["documents"][0]["text"]
    assert "待复核" in result["summary"] and any("没有执行官方" in item for item in result["warnings"])
    changed = copy.deepcopy(result)
    changed["summary"] = "已确认编码和分组正确"
    with pytest.raises(ValueError):
        validate_result(changed, source, projection_hash)
    changed = copy.deepcopy(result)
    changed["coding_analysis"]["claims"][0]["citations"][0]["quote"] += "不是原文"
    with pytest.raises(ValueError):
        validate_result(changed, source, projection_hash)


def test_extra_private_context_and_rehashed_public_projection_rejected(db_session, case):
    db, c = db_session, case
    row = published(db, c)
    context = bundle_for(db, c, row).data
    with pytest.raises(HTTPException):
        expand_context(db, {**context, "private_text": "must not be accepted"}, user=c["doctor_user"], current=True)
    expanded = expand_context(db, context, user=c["doctor_user"], current=True)
    expanded["coding_source"]["documents"][0]["text"] += "changed"
    with pytest.raises(ValueError):
        public_payload({"input": selected(row), "context": expanded})


def test_coding_metadata_always_advertises_strict_evidence_input_and_actual_system_contract(db_session):
    from app.ai.catalog import FEATURE_BY_KEY
    from app.ai.coding_evidence_prompt import CODING_SYSTEM_PROMPT
    from app.ai.governance import describe_config, digest

    spec = FEATURE_BY_KEY["drg_evidence_review"]
    ordinary = describe_config(db_session, spec, None)
    management = describe_config(db_session, spec, None, management=True)
    assert ordinary["input_mode"] == management["input_mode"] == "coding_evidence"
    assert ordinary["source_reference_keys"] == ["coding_case_id"]
    assert "doctor" in ordinary["allowed_roles"]
    assert management["system_prompt_hash"] == digest(CODING_SYSTEM_PROMPT)
