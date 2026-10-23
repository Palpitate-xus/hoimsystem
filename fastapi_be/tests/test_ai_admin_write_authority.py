"""Management mutations retain the authenticated identity through SQL and awaits."""

import datetime
import importlib
import json
import uuid

import pytest
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select, text

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.gateway import AIExecutionError
from app.ai.governance import digest
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIKnowledgeDocument, AIPatientGrant, AIPromptVersion, AIProvider, utcnow
from app.ai.pathway_knowledge import pathway_hash
from app.ai.schemas import FeatureWrite, KnowledgeReview, KnowledgeWrite, PathwayKnowledgeImport, PatientGrantWrite, PromptActivate, PromptWrite, ProviderCheck, ProviderWrite
from app.database import get_db
from app.dependencies import get_current_user
from app.main import app
from app.models import ClinicalPathway, Patient, User
from app.routers import ai_admin


TABLES = (AIFeatureConfig, AIProvider, AIPromptVersion, AIKnowledgeDocument, AIPatientGrant, AIAuditEvent)
ACTIONS = ("feature", "provider_create", "provider_update", "prompt_create", "prompt_activate", "knowledge_create", "knowledge_review", "pathway_import", "grant_create", "grant_revoke")
PROBES = (
    ("speech", "medical_transcription", "speech", "speech"),
    ("ecg", "ecg_analysis", "ecg", "ecg"),
    ("image", "imaging_detection", "imaging", "imaging"),
    ("forecast", "visit_forecast", "forecast", "forecast"),
    ("news2", "deterioration_risk", "news2", "news2"),
    ("aki", "aki_risk", "aki", "aki"),
    ("qsofa", "sepsis_risk", "qsofa", "qsofa"),
    ("sofa", "sepsis_risk", "sofa", "sofa"),
    ("roster", "roster_optimization", "roster", "roster"),
    ("bed", "bed_forecast", "bed", "bed"),
    ("surgery", "surgery_scheduling", "surgery", "surgery"),
    ("supply", "supply_forecast", "supply", "supply"),
    ("inventory", "inventory_optimization", "inventory", "inventory"),
)


def snapshot(db):
    return {model.__tablename__: sorted((tuple(row) for row in db.execute(select(*model.__table__.columns))), key=repr) for model in TABLES}


def subject(actor):
    return {key: getattr(actor, key) for key in ("user_id", "username", "user_role", "token_invalid_before")}


def change_subject(db, original, axis):
    values = {"role": ("user_role", "pharmacist"), "epoch": ("token_invalid_before", "2099-01-02 03:04:05.123456"), "username": ("username", "moved-" + uuid.uuid4().hex[:12])}
    column, value = values[axis]
    db.execute(text(f"UPDATE hoimsystem_users SET {column}=:value WHERE user_id=:pk"), {"value": value, "pk": original["user_id"]})
    # Commit a revocation independently of the mutation's eventual rollback,
    # while deliberately retaining the already authenticated ORM snapshot.
    previous = db.expire_on_commit
    db.expire_on_commit = False
    try:
        db.commit()
    finally:
        db.expire_on_commit = previous


def restore_subject(db, original):
    db.rollback()
    db.execute(text("UPDATE hoimsystem_users SET username=:username, user_role=:user_role, token_invalid_before=:token_invalid_before WHERE user_id=:user_id"), original)
    db.commit()


def mutation(db, actor, action):
    key = "patient_summary"
    suffix = uuid.uuid4().hex
    config = db.get(AIFeatureConfig, key)
    revision = config.revision if config else 0
    provider_body = ProviderWrite(name="authority-" + suffix, api_base="http://localhost:11434/v1", model="synthetic")
    if action == "feature":
        return lambda: ai_admin.update_feature(key, FeatureWrite(expected_revision=revision, daily_limit=83), db, actor)
    if action == "provider_create":
        return lambda: ai_admin.create_provider(provider_body, db, actor)
    if action == "provider_update":
        provider = AIProvider(name="before-" + suffix, api_base=provider_body.api_base, model="before", created_by=actor.user_id)
        db.add(provider)
        db.commit()
        provider_body.expected_revision = provider.revision
        return lambda: ai_admin.update_provider(provider.provider_id, provider_body, db, actor)
    if action == "prompt_create":
        req = PromptWrite(expected_revision=revision, task_prompt="整理已提供资料，保留证据来源和不确定性，由医生审核后决定下一步。" * 2, change_note="仅用于合成权限验证")
        return lambda: ai_admin.create_prompt(key, req, db, actor)
    if action == "prompt_activate":
        return lambda: ai_admin.activate_prompt(key, PromptActivate(expected_revision=revision), db, actor)
    if action == "knowledge_create":
        req = KnowledgeWrite(title="合成规范" + suffix, version="v1", source_uri="hospital://synthetic/authority", content="仅用于权限验证的完整合成知识内容，不提供实际诊疗建议。" * 2, feature_keys=[key])
        return lambda: ai_admin.create_knowledge(req, db, actor)
    if action == "knowledge_review":
        content = "仅用于权限校验的合成知识正文。"
        doc = AIKnowledgeDocument(title="待审合成规范" + suffix, version="v1", source_uri="hospital://synthetic/authority", content=content, content_hash=digest(content), feature_keys_json=json.dumps([key]), created_by=actor.user_id)
        db.add(doc)
        db.commit()
        req = KnowledgeReview(content_hash=doc.content_hash, status="published")
        return lambda: ai_admin.review_knowledge(doc.document_id, req, db, actor)
    if action == "pathway_import":
        row = ClinicalPathway(name="合成路径", disease_code="SYNTHETIC", disease_name="测试范围", steps='["仅供测试的路径步骤"]', expected_days=1, status=0, create_time=utcnow())
        db.add(row)
        db.commit()
        req = PathwayKnowledgeImport(expected_source_hash=pathway_hash(row))
        return lambda: ai_admin.import_pathway_knowledge(row.pathway_id, req, db, actor)
    target_id = db.query(User.user_id).filter_by(user_role="doctor").first()[0]
    patient_id = db.query(Patient.patient_id).first()[0]
    req = PatientGrantWrite(user_id=target_id, patient_id=patient_id, category=FEATURE_BY_KEY[key].category, reason="仅验证合成授权的权限与回滚", expires_at=utcnow() + datetime.timedelta(days=1))
    if action == "grant_create":
        return lambda: ai_admin.create_grant(req, db, actor)
    grant = AIPatientGrant(**req.model_dump(), created_by=actor.user_id)
    db.add(grant)
    db.commit()
    grant_id = grant.grant_id
    return lambda: ai_admin.revoke_grant(grant_id, db, actor)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("axis", ("role", "epoch", "username"))
def test_stale_authenticated_admin_cannot_mutate_any_configuration(db_session, seed_data, action, axis):
    actor = seed_data["super_admin_user"]
    invoke = mutation(db_session, actor, action)
    original = subject(actor)
    before = snapshot(db_session)
    change_subject(db_session, original, axis)
    assert subject(actor) == original
    try:
        with pytest.raises(HTTPException) as caught:
            invoke()
        assert caught.value.status_code == 403
        assert snapshot(db_session) == before
    finally:
        restore_subject(db_session, original)


@pytest.mark.parametrize("action", ACTIONS)
def test_current_admin_can_still_perform_each_configuration_write(db_session, seed_data, action):
    actor = seed_data["super_admin_user"]
    invoke = mutation(db_session, actor, action)
    before = db_session.query(AIAuditEvent).count()
    assert invoke()["code"] == 200
    assert db_session.query(AIAuditEvent).count() == before + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("probe", PROBES, ids=lambda item: item[0])
@pytest.mark.parametrize("axis", ("role", "epoch", "username"))
@pytest.mark.parametrize("when", ("before", "during"))
async def test_probe_never_uses_or_restores_revoked_authority(db_session, seed_data, monkeypatch, probe, axis, when):
    route, key, module, inspector = probe
    actor = seed_data["super_admin_user"]
    provider = AIProvider(name="probe-" + uuid.uuid4().hex, kind="specialist", api_base="http://localhost:11434/v1", model="synthetic", supported_features_json=json.dumps([key]), created_by=actor.user_id)
    db_session.add(provider)
    db_session.commit()
    provider_id, revision = provider.provider_id, provider.revision
    original = subject(actor)
    before = snapshot(db_session)
    calls = []

    async def inspect_provider(detached):
        calls.append(detached.provider_id)
        change_subject(db_session, original, axis)
        raise AIExecutionError("synthetic_probe_failure", "合成能力检测失败")

    name = f"inspect_{inspector}_capabilities"
    monkeypatch.setattr(importlib.import_module(f"app.ai.{module}_probe"), name, inspect_provider)
    if hasattr(ai_admin, name):
        monkeypatch.setattr(ai_admin, name, inspect_provider)
    if when == "before":
        change_subject(db_session, original, axis)
    try:
        with pytest.raises(HTTPException) as caught:
            await getattr(ai_admin, f"check_{route}_provider")(provider_id, ProviderCheck(expected_revision=revision), db_session, actor)
        assert caught.value.status_code == 403
        assert calls == ([] if when == "before" else [provider_id])
        assert snapshot(db_session) == before
    finally:
        restore_subject(db_session, original)


@pytest.mark.parametrize("axis,assignment", (("role", "user_role='pharmacist'"), ("epoch", "token_invalid_before='2099-01-02 03:04:05.123456'"), ("username", "username='changed-by-audit'")))
def test_authority_change_in_actual_audit_sql_rolls_back_every_write(db_session, seed_data, axis, assignment):
    actor = seed_data["super_admin_user"]
    invoke = mutation(db_session, actor, "feature")
    original = subject(actor)
    before = snapshot(db_session)
    db_session.execute(text(f"CREATE TRIGGER revoke_admin_during_audit AFTER INSERT ON hoimsystem_ai_audit_event BEGIN UPDATE hoimsystem_users SET {assignment} WHERE user_id={original['user_id']}; END"))
    db_session.commit()
    try:
        with pytest.raises(HTTPException) as caught:
            invoke()
        assert caught.value.status_code == 403
        assert snapshot(db_session) == before
        assert subject(db_session.query(User).filter_by(user_id=original["user_id"]).populate_existing().one()) == original
    finally:
        db_session.rollback()
        db_session.execute(text("DROP TRIGGER revoke_admin_during_audit"))
        db_session.commit()
        restore_subject(db_session, original)


@pytest.mark.asyncio
@pytest.mark.parametrize("axis", ("role", "epoch", "username"))
async def test_main_jwt_snapshot_cannot_write_after_database_revocation(async_client, seed_data, auth_headers, db_session, axis):
    original = subject(seed_data["super_admin_user"])
    before = snapshot(db_session)
    headers = auth_headers(original["username"])

    def authenticate_then_revoke(request: Request, access_token: str = Header(None, alias="accesstoken"), db=Depends(get_db)):
        actor = get_current_user(request, access_token, db)
        change_subject(db, original, axis)
        assert subject(actor) == original
        return actor

    previous = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = authenticate_then_revoke
    try:
        response = await async_client.post("/api/ai/admin/providers", headers=headers, json={"name": "jwt-revoked-" + uuid.uuid4().hex, "api_base": "http://localhost:11434/v1", "model": "synthetic"})
        assert response.status_code == 403, response.text
        assert snapshot(db_session) == before
    finally:
        if previous is None:
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = previous
        restore_subject(db_session, original)
