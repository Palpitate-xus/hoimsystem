"""Feedback text has immutable versions, explicit review and source-bound publication."""

import datetime
from pathlib import Path

import httpx
import pytest
from alembic.config import Config
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app import database
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import encode_json
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIFeedback, AIProvider, AIReviewExcerpt, AIRun
from app.ai.operational_sources import operational_context
from app.ai.review_curation import create_excerpt, describe_excerpt, load_review_source, review_excerpt, source_state
from app.ai.runtime import authorize_run, claim_next_run, create_run, describe_run, execute_claimed
from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact
from app.ai.satisfaction_models import AISatisfactionCase
from app.ai.satisfaction_sources import create_case, preview_input, review_case
from app.ai.schemas import ReviewExcerptReview, ReviewExcerptWrite, RunRequest
from app.models import Department, MedicalRecord, Registration, Review
from tests.test_ai_satisfaction_gateway import envelope


@pytest.fixture
def source_case(seed_data, db_session):
    for model in (AISatisfactionRunArtifact, AISatisfactionCase, AIFeedback, AIRun, AIFeatureConfig, AIProvider, AIReviewExcerpt, AIAuditEvent, Review):
        db_session.query(model).delete()
    now = datetime.datetime.now()
    registration = Registration(patient_id=seed_data["patient"].patient_id, doctor_id=seed_data["doctor"].doctor_id, department_id=seed_data["department"].department_id, time=now)
    db_session.add(registration)
    db_session.flush()
    visit = MedicalRecord(patient_id=registration.patient_id, doctor_id=registration.doctor_id, registration_uuid=registration.registration_uuid)
    db_session.add(visit)
    db_session.flush()
    review = Review(
        patient_id=visit.patient_id,
        doctor_id=visit.doctor_id,
        visit_id=visit.medical_record_id,
        score=2,
        comment=seed_data["patient"].name + "评价" + seed_data["doctor"].name + "：候诊较久，电话13800138000",
        review_time=now,
    )
    db_session.add(review)
    db_session.commit()
    return review, registration, visit


def draft(db_session, seed_data, review, **changes):
    source = load_review_source(db_session, review.review_id)
    request = {"review_id": review.review_id, "expected_source_hash": source.fingerprint, "redacted_text": "候诊较久，希望了解顺序。", "change_note": "删除直接标识，保留原意", **changes}
    item = create_excerpt(db_session, seed_data["super_admin_user"], ReviewExcerptWrite(**request))
    db_session.commit()
    return item


def decide(db_session, seed_data, item, **changes):
    request = {"expected_revision": item.revision, "status": "published", "privacy_checked": True, "faithfulness_checked": True, "review_note": "已检查脱敏和原意", **changes}
    result = review_excerpt(db_session, seed_data["super_admin_user"], item.excerpt_id, ReviewExcerptReview(**request))
    db_session.commit()
    return result


def test_drafts_are_immutable_new_versions_and_audit_contains_no_comment_text(seed_data, db_session, source_case):
    review, _, _ = source_case
    first = draft(db_session, seed_data, review)
    second = draft(db_session, seed_data, review, redacted_text="候诊时间较长，希望了解流程。")
    assert (first.version, second.version) == (1, 2)
    assert first.status == second.status == "draft"
    assert first.redacted_text == "候诊较久，希望了解顺序。"
    assert "redacted_text" not in describe_excerpt(first)
    audit_text = encode_json([event.detail_json for event in db_session.query(AIAuditEvent).filter(AIAuditEvent.action.like("review_excerpt.%")).all()])
    assert review.comment not in audit_text and second.redacted_text not in audit_text and "13800138000" not in audit_text


def test_known_patient_staff_identifiers_are_removed_in_suggestion_and_rejected_in_draft(seed_data, db_session, source_case):
    review, _, _ = source_case
    source = load_review_source(db_session, review.review_id)
    suggestion = source.redact(review.comment)
    for identifier in (seed_data["patient"].name, seed_data["doctor"].name, "13800138000"):
        assert identifier not in suggestion
    with pytest.raises(HTTPException) as error:
        draft(db_session, seed_data, review, redacted_text=review.comment)
    assert error.value.status_code == 422
    review.comment = " "
    db_session.commit()
    with pytest.raises(HTTPException) as error:
        draft(db_session, seed_data, review)
    assert error.value.status_code == 409


def test_publication_requires_both_explicit_checks_and_matching_source(seed_data, db_session, source_case):
    review, _, _ = source_case
    item = draft(db_session, seed_data, review)
    for flags in ({"privacy_checked": False}, {"faithfulness_checked": False}):
        with pytest.raises(HTTPException) as error:
            decide(db_session, seed_data, item, **flags)
        assert error.value.status_code == 422
    review.comment += "原评论已修改"
    db_session.commit()
    assert source_state(db_session, item) == "stale"
    with pytest.raises(HTTPException) as error:
        decide(db_session, seed_data, item)
    assert error.value.status_code == 409
    assert item.status == "draft"


def test_publish_new_version_retires_prior_and_rejects_lost_review_updates(seed_data, db_session, source_case):
    review, _, _ = source_case
    first = decide(db_session, seed_data, draft(db_session, seed_data, review))
    old_revision = first.revision
    second = decide(db_session, seed_data, draft(db_session, seed_data, review, redacted_text="希望了解候诊顺序，等待较久。"))
    db_session.refresh(first)
    assert first.status == "retired" and first.revision == old_revision + 1
    assert second.status == "published" and second.privacy_checked and second.faithfulness_checked
    assert first.reviewed_at is not None and first.retired_at is not None
    with pytest.raises(HTTPException) as error:
        decide(db_session, seed_data, first, status="retired", expected_revision=old_revision)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        decide(db_session, seed_data, first)
    assert error.value.status_code == 409


def test_broken_source_can_be_retired_but_cannot_be_published(seed_data, db_session, source_case):
    review, registration, _ = source_case
    first = decide(db_session, seed_data, draft(db_session, seed_data, review))
    second = draft(db_session, seed_data, review)
    registration.patient_id = seed_data["patient2"].patient_id
    db_session.commit()
    assert source_state(db_session, first) == "unavailable"
    with pytest.raises(HTTPException) as error:
        decide(db_session, seed_data, second)
    assert error.value.status_code == 409
    first = decide(db_session, seed_data, first, status="retired")
    assert first.status == "retired"


def test_effective_original_department_and_known_identity_changes_control_source_hash(seed_data, db_session, source_case):
    review, registration, visit = source_case
    item = draft(db_session, seed_data, review)
    new_department = Department(name="新评价归属")
    db_session.add(new_department)
    db_session.flush()
    seed_data["doctor"].department_id = new_department.department_id
    db_session.commit()
    # An unchanged original registration keeps its real department despite later physician rotation.
    assert source_state(db_session, item) == "current"
    visit.registration_uuid = None
    db_session.commit()
    assert source_state(db_session, item) == "stale"
    new_item = draft(db_session, seed_data, review)
    assert new_item.department_id == new_department.department_id
    seed_data["patient"].phone = "13912345678"
    db_session.commit()
    assert source_state(db_session, new_item) == "stale"


def test_invalid_source_revision_and_request_types_fail_before_draft_write(seed_data, db_session, source_case):
    review, _, _ = source_case
    with pytest.raises(HTTPException) as error:
        draft(db_session, seed_data, review, expected_source_hash="0" * 64)
    assert error.value.status_code == 409
    for review_id in (True, "1", 0):
        with pytest.raises(ValidationError):
            ReviewExcerptWrite(review_id=review_id, expected_source_hash="0" * 64, redacted_text="候诊原文", change_note="脱敏说明")
    assert db_session.query(AIReviewExcerpt).count() == 0


def test_excerpt_migration_upgrade_rollback_preserves_source_review(tmp_path):
    path = tmp_path / "review-excerpt.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        for table, key in (("users", "user_id"), ("department", "department_id"), ("review", "review_id")):
            conn.exec_driver_sql(f"CREATE TABLE hoimsystem_{table} ({key} INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO hoimsystem_review VALUES (7)")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.stamp(config, "20261020_dose_rule_units")
    command.upgrade(config, "20261020_ai_review_excerpts")
    assert "hoimsystem_ai_review_excerpt" in inspect(engine).get_table_names()
    command.downgrade(config, "20261020_dose_rule_units")
    assert "hoimsystem_ai_review_excerpt" not in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT review_id FROM hoimsystem_review")) == 7
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "director", "doctor", "nurse", "cashier", "pharmacist", "guide", "lab_tech", "registrar", "patient"])
async def test_all_curation_endpoints_reject_non_super_roles(role, seed_data, async_client, auth_headers):
    headers = auth_headers(seed_data[role + "_user"].username)
    paths = [
        ("GET", "/api/ai/admin/review-sources", None),
        ("GET", "/api/ai/admin/review-sources/1", None),
        ("GET", "/api/ai/admin/review-excerpts", None),
        ("GET", "/api/ai/admin/review-excerpts/example", None),
        ("POST", "/api/ai/admin/review-excerpts", {"review_id": 1, "expected_source_hash": "0" * 64, "redacted_text": "脱敏片段", "change_note": "保存说明"}),
        ("POST", "/api/ai/admin/review-excerpts/example/review", {"expected_revision": 1, "status": "published", "review_note": "审核说明"}),
    ]
    for method, path, payload in paths:
        response = await async_client.request(method, path, headers=headers, json=payload)
        assert response.status_code == 403, (method, path, response.text)


@pytest.mark.asyncio
async def test_super_admin_can_inspect_draft_and_review_without_inference(seed_data, db_session, source_case, async_client, auth_headers):
    review, _, _ = source_case
    headers = auth_headers(seed_data["super_admin_user"].username)
    response = await async_client.get("/api/ai/admin/review-sources", headers=headers, params={"review_id": review.review_id})
    assert response.status_code == 200
    metadata = response.json()["data"]
    assert metadata["total"] == 1 and metadata["items"][0]["has_comment"] is True
    assert "raw_comment" not in encode_json(metadata) and review.comment not in encode_json(metadata)
    response = await async_client.get(f"/api/ai/admin/review-sources/{review.review_id}", headers=headers)
    source = response.json()["data"]
    assert response.status_code == 200 and source["raw_comment"] == review.comment
    assert "13800138000" not in source["suggested_redacted_text"]
    events = db_session.query(AIAuditEvent).filter_by(action="review_source.read", target=str(review.review_id)).all()
    assert len(events) == 1 and review.comment not in events[0].detail_json
    payload = {"review_id": review.review_id, "expected_source_hash": source["source_hash"], "redacted_text": source["suggested_redacted_text"], "change_note": "人工检查脱敏稿"}
    response = await async_client.post("/api/ai/admin/review-excerpts", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    item = response.json()["data"]
    assert item["status"] == "draft" and item["version"] == 1
    endpoint = f"/api/ai/admin/review-excerpts/{item['excerpt_id']}"
    detail = await async_client.get(endpoint, headers=headers)
    assert detail.json()["data"]["source_state"] == "current"
    request = {"expected_revision": item["revision"], "status": "published", "review_note": "逐条审核通过"}
    denied = await async_client.post(endpoint + "/review", headers=headers, json=request)
    assert denied.status_code == 422
    approved = await async_client.post(endpoint + "/review", headers=headers, json={**request, "privacy_checked": True, "faithfulness_checked": True})
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "published"
    stale = await async_client.post(endpoint + "/review", headers=headers, json={**request, "status": "retired"})
    assert stale.status_code == 409
    listed = await async_client.get("/api/ai/admin/review-excerpts", headers=headers, params={"review_id": review.review_id, "status": "published"})
    assert listed.json()["data"]["total"] == 1 and "redacted_text" not in listed.json()["data"]["items"][0]
    assert db_session.query(AIRun).count() == 0


@pytest.mark.asyncio
async def test_source_change_and_creation_status_override_cannot_bypass_review(seed_data, db_session, source_case, async_client, auth_headers):
    review, _, _ = source_case
    headers = auth_headers(seed_data["super_admin_user"].username)
    response = await async_client.get(f"/api/ai/admin/review-sources/{review.review_id}", headers=headers)
    payload = {"review_id": review.review_id, "expected_source_hash": response.json()["data"]["source_hash"], "redacted_text": "候诊原意保留", "change_note": "人工删除标识"}
    override = await async_client.post("/api/ai/admin/review-excerpts", headers=headers, json={**payload, "status": "published"})
    assert override.status_code == 422
    review.comment += "新的评论"
    db_session.commit()
    stale = await async_client.post("/api/ai/admin/review-excerpts", headers=headers, json=payload)
    assert stale.status_code == 409 and db_session.query(AIReviewExcerpt).count() == 0


def feedback_context(db_session, seed_data):
    return operational_context(db_session, seed_data["director_user"], FEATURE_BY_KEY["feedback_analysis"], {"department_id": seed_data["department"].department_id})


@pytest.mark.asyncio
async def test_legacy_context_keeps_scoped_reviewed_citations_but_http_requires_a_complete_reviewed_case(seed_data, db_session, source_case, async_client, auth_headers):
    review, _, _ = source_case
    published = decide(db_session, seed_data, draft(db_session, seed_data, review))
    draft(db_session, seed_data, review, redacted_text="尚未审核的稿件不得发送")
    foreign = Department(name="不可见评价科室")
    db_session.add(foreign)
    db_session.flush()
    registration = Registration(patient_id=review.patient_id, doctor_id=review.doctor_id, department_id=foreign.department_id, time=review.review_time)
    db_session.add(registration)
    db_session.flush()
    visit = MedicalRecord(patient_id=review.patient_id, doctor_id=review.doctor_id, registration_uuid=registration.registration_uuid)
    db_session.add(visit)
    db_session.flush()
    other = Review(patient_id=review.patient_id, doctor_id=review.doctor_id, visit_id=visit.medical_record_id, score=1, comment="跨科不可见的评价片段", review_time=review.review_time)
    db_session.add(other)
    db_session.commit()
    decide(db_session, seed_data, draft(db_session, seed_data, other, redacted_text="跨科不可见的评价片段"))
    response = await async_client.post(
        "/api/ai/operational-context",
        headers=auth_headers(seed_data["director_user"].username),
        json={"feature_key": "feedback_analysis", "input": {"department_id": seed_data["department"].department_id}},
    )
    # Retain the legacy source helper for old read-only tasks. New HTTP tasks
    # require a complete reviewed Case rather than a clipped department list.
    assert response.status_code == 422, response.text
    bundle = feedback_context(db_session, seed_data)
    data = {"context": bundle.data, "evidence": bundle.evidence}
    rows = data["context"]["reviewed_feedback_excerpts"]["items"]
    assert len(rows) == 1 and rows[0]["excerpt_ref"] == published.excerpt_id
    assert rows[0]["verification_status"] == "reported_feedback_only"
    assert any(item["source_id"] == rows[0]["source_id"] and published.redacted_text in item["content"] for item in data["evidence"])
    serialized = encode_json(data)
    for forbidden in ("跨科不可见", "尚未审核的稿件", "13800138000", seed_data["patient"].name, "source_hash", '"patient_id"', '"doctor_id"', '"review_id"'):
        assert forbidden not in serialized
    assert db_session.query(AIRun).count() == 0


@pytest.mark.parametrize("mutation", ["comment", "association", "department", "artifact", "retire"])
def test_changed_or_withdrawn_text_is_removed_from_future_model_context(mutation, seed_data, db_session, source_case):
    review, registration, _ = source_case
    item = decide(db_session, seed_data, draft(db_session, seed_data, review))
    assert feedback_context(db_session, seed_data).data["reviewed_feedback_excerpts"]["included_excerpt_count"] == 1
    if mutation == "comment":
        review.comment += "原文变化"
    elif mutation == "association":
        registration.patient_id = seed_data["patient2"].patient_id
    elif mutation == "department":
        department = Department(name="已调离的评价科室")
        db_session.add(department)
        db_session.flush()
        registration.department_id = department.department_id
    elif mutation == "artifact":
        item.redacted_text = "直接改库的未审核文本"
    else:
        decide(db_session, seed_data, item, status="retired")
    db_session.commit()
    bundle = feedback_context(db_session, seed_data)
    assert bundle.data["reviewed_feedback_excerpts"]["items"] == []
    assert all("已审核脱敏评价片段" != evidence["title"] for evidence in bundle.evidence)
    assert any("当前范围暂无已审核的评价摘录" in text for text in bundle.data["missing_data"])


def configure_feedback(db_session, seed_data):
    provider = AIProvider(
        name="feedback-isolated", kind="chat", api_base="http://localhost:11434/v1", model="isolated", enabled=1, allows_patient_data=1, created_by=seed_data["super_admin_user"].user_id
    )
    db_session.add(provider)
    db_session.flush()
    db_session.add(
        AIFeatureConfig(
            feature_key="feedback_analysis",
            enabled=1,
            provider_id=provider.provider_id,
            allowed_roles_json=encode_json(FEATURE_BY_KEY["feedback_analysis"].default_roles),
            validation_status="validated",
            validation_note="隔离合成完整评价及逐字引文工程测试，不代表医院真实验证。",
            validated_by=seed_data["super_admin_user"].user_id,
            validated_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
            updated_by=seed_data["super_admin_user"].user_id,
        )
    )
    db_session.commit()


def create_feedback_task(db_session, seed_data):
    configure_feedback(db_session, seed_data)
    item = db_session.query(AIReviewExcerpt).filter_by(status="published").one()
    review = db_session.get(Review, item.review_id)
    period = {"scope_kind": "explicit_doctor_cohort", "doctor_ids": [review.doctor_id], "date_from": review.review_time.date().isoformat(), "date_to": review.review_time.date().isoformat()}
    captured = preview_input(db_session, seed_data["super_admin_user"], period)
    selected = next(value for value in captured["excerpt_options"] if value["excerpt_id"] == item.excerpt_id)
    basis = "隔离合成完整评价范围、人工隐私和原意核查声明，不代表医院真实验证。"
    made = create_case(
        db_session,
        seed_data["super_admin_user"],
        {
            "request": period,
            "expected_collection_digest": captured["collection_digest"],
            "selected_excerpts": [{key: selected[key] for key in ("excerpt_id", "review_token", "content_hash", "governance_hash")}],
            "basis_note": basis,
        },
    )
    reviewed = review_case(db_session, seed_data["super_admin_user"], made["case_id"], {"expected_revision": 1, "decision": "publish", "basis_note": basis})
    return create_run(db_session, seed_data["admin_user"], RunRequest(feature_key="feedback_analysis", input={"satisfaction_case_id": reviewed["case_id"]}))


def feedback_model_draft(db_session, seed_data, run):
    source = describe_run(run, user=seed_data["admin_user"])["satisfaction_findings"]["satisfaction_source"]
    selected = source["safe_snapshot"]["selected_excerpts"][0]
    return {
        "schema_version": "satisfaction_evidence_draft_v1",
        "satisfaction_source_id": source["source_id"],
        "safe_projection_hash": source["safe_projection_hash"],
        "coverage": "partial_themes_no_population_or_causality_claim",
        "themes": [
            {
                "title": "候诊反馈待核查",
                "observation": "原摘录提及等候，实际流程原因尚未核实。",
                "clarification_question": "能否补充可核实的候诊顺序说明？",
                "cited_excerpt_tokens": [selected["excerpt_token"]],
                "citations": [{"excerpt_token": selected["excerpt_token"], "text_hash": selected["text_hash"], "start": 0, "end": len(selected["text"]), "quote": selected["text"]}],
            }
        ],
    }


@pytest.mark.asyncio
async def test_withdrawal_stops_queued_call_and_revokes_ordinary_history_but_preserves_super_audit(seed_data, db_session, source_case):
    item = decide(db_session, seed_data, draft(db_session, seed_data, source_case[0]))
    run = create_feedback_task(db_session, seed_data)
    original_input = run.input_json
    decide(db_session, seed_data, item, status="retired")
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(lambda request: (calls.append(request), httpx.Response(500))[1]))
    db_session.refresh(run)
    assert calls == [] and run.status == "failed" and run.error_code == "TASK_NO_LONGER_AUTHORIZED"
    with pytest.raises(HTTPException) as error:
        authorize_run(db_session, seed_data["admin_user"], run)
    assert error.value.status_code == 409
    authorize_run(db_session, seed_data["super_admin_user"], run)
    assert run.input_json == original_input
    assert describe_run(run, user=seed_data["super_admin_user"])["satisfaction_findings"]["satisfaction_source"]["safe_snapshot"]["selected_excerpts"][0]["text"] == item.redacted_text


@pytest.mark.asyncio
async def test_withdrawal_during_inference_discards_result_without_changing_frozen_evidence(seed_data, db_session, source_case):
    item = decide(db_session, seed_data, draft(db_session, seed_data, source_case[0]))
    run = create_feedback_task(db_session, seed_data)
    original_input = run.input_json
    model_draft = feedback_model_draft(db_session, seed_data, run)
    calls = []

    def reply(request):
        calls.append(request)
        with database.SessionLocal() as session:
            current = session.get(AIReviewExcerpt, item.excerpt_id)
            current.status = "retired"
            current.revision += 1
            session.commit()
        reply = envelope("chat", model_draft)
        reply["usage"] = {"prompt_tokens": 4, "completion_tokens": 5}
        return httpx.Response(200, json=reply)

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(reply))
    db_session.refresh(run)
    assert len(calls) == 1 and run.error_code == "TASK_NO_LONGER_AUTHORIZED"
    assert run.result_json == "{}" and run.input_json == original_input and run.output_tokens == 5


@pytest.mark.asyncio
async def test_model_receives_reviewed_citation_and_replacement_revokes_old_business_result(seed_data, db_session, source_case):
    decide(db_session, seed_data, draft(db_session, seed_data, source_case[0]))
    run = create_feedback_task(db_session, seed_data)
    model_draft = feedback_model_draft(db_session, seed_data, run)
    source_id = model_draft["satisfaction_source_id"]
    calls = []

    def reply(request):
        payload = request.content.decode()
        assert "13800138000" not in payload and source_id in payload
        assert "尚未审核" not in payload
        calls.append(request)
        return httpx.Response(200, json=envelope("chat", model_draft))

    await execute_claimed(*claim_next_run(db_session), transport=httpx.MockTransport(reply))
    db_session.refresh(run)
    assert run.status == "succeeded" and len(calls) == 1
    authorize_run(db_session, seed_data["admin_user"], run)
    replacement = draft(db_session, seed_data, source_case[0], redacted_text="候诊较久，希望完善顺序说明。")
    decide(db_session, seed_data, replacement)
    with pytest.raises(HTTPException):
        authorize_run(db_session, seed_data["admin_user"], run)
    authorize_run(db_session, seed_data["super_admin_user"], run)
