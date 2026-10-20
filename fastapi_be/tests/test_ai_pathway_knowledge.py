"""Hospital templates are usable only through scoped, current reviewed snapshots."""

import datetime
import json
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import digest
from app.ai.knowledge import evidence_is_current, retrieve_evidence
from app.ai.models import AIKnowledgeDocument, AIRun, utcnow
from app.ai.pathway_knowledge import PATHWAY_URI_PREFIX, eligible_pathway_documents, import_content, parse_pathway_steps, pathway_hash, source_state
from app.models import ClinicalPathway


@pytest.fixture
def pathway_case(seed_data, db_session):
    db_session.query(AIKnowledgeDocument).delete()
    row = ClinicalPathway(
        name="院内测试路径",
        disease_code="TEST",
        disease_name="测试适用病种",
        steps=json.dumps({"inclusion": "原纳入条件", "exclusion": "原排除条件必须保留", "steps": [{"day": 1, "content": "原路径措施"}]}),
        expected_days=7,
        status=0,
        create_time=datetime.datetime.now(),
    )
    db_session.add(row)
    db_session.commit()
    return row


def document(db_session, seed_data, row, **changes):
    content = import_content(row)
    item = AIKnowledgeDocument(
        title="路径知识",
        version="test-" + str(db_session.query(AIKnowledgeDocument).count()),
        source_uri=PATHWAY_URI_PREFIX + str(row.pathway_id),
        source_kind="clinical_pathway",
        source_reference_id=row.pathway_id,
        source_snapshot_hash=pathway_hash(row),
        content=content,
        content_hash=digest(content),
        category="clinical",
        feature_keys_json='["treatment_pathway"]',
        status="draft",
        created_by=seed_data["super_admin_user"].user_id,
        **changes,
    )
    db_session.add(item)
    db_session.commit()
    return item


def test_source_snapshot_keeps_all_original_fields_without_implying_review(seed_data, db_session, pathway_case):
    content = import_content(pathway_case)
    assert "原排除条件必须保留" in content and "启用状态不代表临床有效性" in content
    assert pathway_case.steps in json.loads(content.split("\n")[-1]).values()
    item = document(db_session, seed_data, pathway_case)
    assert source_state(db_session, item) == "current"
    assert eligible_pathway_documents(db_session, [pathway_case.pathway_id], "treatment_pathway", set()) == []


@pytest.mark.parametrize(
    "value", ["[]", "not-json", "[1]", '[""]', "[{}]", '{"steps":true}', '["x",NaN]', "[" * 1001, '{"steps":["first"],"steps":["last"]}', '[{"exclusion":"first","exclusion":"last"}]']
)
def test_unusable_or_ambiguous_step_structure_is_not_imported(value):
    with pytest.raises(HTTPException) as error:
        parse_pathway_steps(value)
    assert error.value.status_code == 422


def test_publication_scope_feature_validity_and_source_changes_all_apply(seed_data, db_session, pathway_case):
    item = document(db_session, seed_data, pathway_case, department_id=seed_data["department"].department_id)
    item.status = "published"
    item.reviewed_by = seed_data["super_admin_user"].user_id
    item.reviewed_at = utcnow()
    db_session.commit()
    ids, departments = [pathway_case.pathway_id], {seed_data["department"].department_id}
    assert eligible_pathway_documents(db_session, ids, "treatment_pathway", departments) == [item]
    assert eligible_pathway_documents(db_session, ids, "response_review", departments) == []
    assert eligible_pathway_documents(db_session, ids, "treatment_pathway", set()) == []
    item.effective_to = utcnow() - datetime.timedelta(seconds=1)
    db_session.commit()
    assert eligible_pathway_documents(db_session, ids, "treatment_pathway", departments) == []
    item.effective_to = None
    pathway_case.steps = '["修改后的治疗措施"]'
    db_session.commit()
    assert source_state(db_session, item) == "changed"
    assert eligible_pathway_documents(db_session, ids, "treatment_pathway", departments) == []


def test_disabled_missing_and_invalid_links_are_not_treated_as_current(seed_data, db_session, pathway_case):
    item = document(db_session, seed_data, pathway_case)
    pathway_case.status = 1
    db_session.commit()
    assert source_state(db_session, item) == "disabled"
    with pytest.raises(HTTPException):
        import_content(pathway_case)
    pathway_case.status = 0
    item.source_uri = "https://not-the-linked-source.example"
    db_session.commit()
    assert source_state(db_session, item) == "invalid_link"
    item.source_uri = PATHWAY_URI_PREFIX + str(pathway_case.pathway_id)
    db_session.delete(pathway_case)
    db_session.commit()
    assert source_state(db_session, item) == "missing"


def test_migration_preserves_unlinked_knowledge_and_has_reversible_columns(tmp_path):
    path = tmp_path / "pathway-knowledge.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE hoimsystem_ai_knowledge_document (document_id TEXT PRIMARY KEY, content TEXT)")
        conn.exec_driver_sql("INSERT INTO hoimsystem_ai_knowledge_document VALUES ('original', '原审核内容')")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.stamp(config, "20261020_adr_resolution")
    command.upgrade(config, "20261020_pathway_knowledge")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT content, source_kind, source_snapshot_hash FROM hoimsystem_ai_knowledge_document")).one() == ("原审核内容", None, None)
    command.downgrade(config, "20261020_adr_resolution")
    assert "source_kind" not in {item["name"] for item in inspect(engine).get_columns("hoimsystem_ai_knowledge_document")}
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT content FROM hoimsystem_ai_knowledge_document")) == "原审核内容"
    engine.dispose()


def test_decoded_numeric_text_preserves_precision_and_explicit_zero():
    data = parse_pathway_steps('[{"value":0.123456789123456789,"day":0,"required":false,"unknown":null}]')
    assert data == [{"value": "0.123456789123456789", "day": "0", "required": False, "unknown": None}]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["admin", "director", "doctor", "nurse", "pharmacist", "cashier", "guide", "lab_tech", "registrar", "patient"])
async def test_only_super_admin_can_list_or_import_pathway_sources(role, seed_data, async_client, auth_headers):
    headers = auth_headers(seed_data[role + "_user"].username)
    response = await async_client.get("/api/ai/admin/pathway-sources", headers=headers)
    assert response.status_code == 403
    response = await async_client.post("/api/ai/admin/pathway-sources/1/import", headers=headers, json={"expected_source_hash": "0" * 64})
    assert response.status_code == 403


async def import_source(async_client, auth_headers, row):
    return await async_client.post(f"/api/ai/admin/pathway-sources/{row.pathway_id}/import", headers=auth_headers("super01"), json={"expected_source_hash": pathway_hash(row)})


@pytest.mark.asyncio
async def test_import_freezes_draft_then_explicit_review_enables_scoped_retrieval(seed_data, db_session, pathway_case, async_client, auth_headers):
    headers = auth_headers("super01")
    listed = await async_client.get("/api/ai/admin/pathway-sources", headers=headers)
    source = next(item for item in listed.json()["data"]["items"] if item["pathway_id"] == pathway_case.pathway_id)
    assert source["importable"] is True and "steps" not in source
    original = pathway_case.steps
    imported = await import_source(async_client, auth_headers, pathway_case)
    assert imported.status_code == 200, imported.text
    data = imported.json()["data"]
    assert data["status"] == "draft"
    endpoint = "/api/ai/admin/knowledge/" + data["document_id"]
    detail = await async_client.get(endpoint, headers=headers)
    assert detail.json()["data"]["source_state"] == "current"
    assert "原排除条件必须保留" in detail.json()["data"]["content"]
    assert retrieve_evidence(db_session, FEATURE_BY_KEY["treatment_pathway"], "院内测试路径", set(), preferred_pathway_ids={pathway_case.pathway_id}) == []
    approved = await async_client.post(endpoint + "/review", headers=headers, json={"status": "published", "content_hash": data["content_hash"]})
    assert approved.status_code == 200, approved.text
    db_session.expire_all()
    evidence = retrieve_evidence(db_session, FEATURE_BY_KEY["treatment_pathway"], "完全不同检索词", set(), preferred_pathway_ids={pathway_case.pathway_id})
    assert evidence and all(item["source_reference_id"] == pathway_case.pathway_id for item in evidence)
    assert evidence_is_current(db_session, evidence) is True
    assert db_session.get(ClinicalPathway, pathway_case.pathway_id).steps == original
    assert db_session.query(AIRun).count() == 0


@pytest.mark.asyncio
async def test_changed_template_cannot_publish_stale_draft_and_retired_version_cannot_reactivate(seed_data, db_session, pathway_case, async_client, auth_headers):
    headers = auth_headers("super01")
    old_hash = pathway_hash(pathway_case)
    imported = (await import_source(async_client, auth_headers, pathway_case)).json()["data"]
    pathway_case.expected_days = 9
    db_session.commit()
    stale_import = await async_client.post(f"/api/ai/admin/pathway-sources/{pathway_case.pathway_id}/import", headers=headers, json={"expected_source_hash": old_hash})
    assert stale_import.status_code == 409
    endpoint = "/api/ai/admin/knowledge/" + imported["document_id"] + "/review"
    assert (await async_client.post(endpoint, headers=headers, json={"status": "published", "content_hash": imported["content_hash"]})).status_code == 409
    fresh = (await import_source(async_client, auth_headers, pathway_case)).json()["data"]
    assert fresh["version"] != imported["version"]
    endpoint = "/api/ai/admin/knowledge/" + fresh["document_id"] + "/review"
    assert (await async_client.post(endpoint, headers=headers, json={"status": "published", "content_hash": fresh["content_hash"]})).status_code == 200
    assert (await async_client.post(endpoint, headers=headers, json={"status": "retired", "content_hash": fresh["content_hash"]})).status_code == 200
    assert (await async_client.post(endpoint, headers=headers, json={"status": "published", "content_hash": fresh["content_hash"]})).status_code == 409


@pytest.mark.asyncio
async def test_source_edit_invalidates_inference_evidence_and_setup_knowledge_dependency(seed_data, db_session, pathway_case, async_client, auth_headers):
    headers = auth_headers("super01")
    data = (await import_source(async_client, auth_headers, pathway_case)).json()["data"]
    await async_client.post("/api/ai/admin/knowledge/" + data["document_id"] + "/review", headers=headers, json={"status": "published", "content_hash": data["content_hash"]})
    db_session.expire_all()
    evidence = retrieve_evidence(db_session, FEATURE_BY_KEY["treatment_pathway"], "测试", set(), preferred_pathway_ids={pathway_case.pathway_id})
    assert evidence
    pathway_case.steps = '["新的未审核步骤"]'
    db_session.commit()
    assert evidence_is_current(db_session, evidence) is False
    assert retrieve_evidence(db_session, FEATURE_BY_KEY["treatment_pathway"], "测试", set(), preferred_pathway_ids={pathway_case.pathway_id}) == []
    response = await async_client.get("/api/ai/admin/features", headers=headers)
    setup = next(item for item in response.json()["data"] if item["key"] == "treatment_pathway")["setup_check"]
    assert "KNOWLEDGE_NOT_PUBLISHED" in {item["code"] for item in setup["issues"]}


@pytest.mark.asyncio
async def test_internal_source_uri_cannot_be_forged_through_generic_knowledge_creation(seed_data, db_session, pathway_case, async_client, auth_headers):
    body = {
        "title": "手工伪装路径",
        "version": "v1",
        "source_uri": PATHWAY_URI_PREFIX + str(pathway_case.pathway_id),
        "category": "clinical",
        "content": "没有绑定真实路径快照的手工文字内容，需要明确拒绝",
        "feature_keys": ["treatment_pathway"],
    }
    response = await async_client.post("/api/ai/admin/knowledge", headers=auth_headers("super01"), json=body)
    assert response.status_code == 422
    assert db_session.query(AIKnowledgeDocument).count() == 0


@pytest.mark.asyncio
async def test_disable_then_restore_identical_template_does_not_revive_old_review(seed_data, db_session, pathway_case, async_client, auth_headers):
    item = document(db_session, seed_data, pathway_case)
    item.status, item.reviewed_by, item.reviewed_at = "published", seed_data["super_admin_user"].user_id, utcnow()
    db_session.commit()
    headers = auth_headers(seed_data["doctor_user"].username)
    endpoint = "/api/clinicalPathway/update"
    original = pathway_case.source_revision
    disabled = await async_client.post(endpoint, headers=headers, json={"pathway_id": pathway_case.pathway_id, "status": 1, "expected_source_revision": original})
    assert disabled.status_code == 200, disabled.text
    stale = await async_client.post(endpoint, headers=headers, json={"pathway_id": pathway_case.pathway_id, "status": 0, "expected_source_revision": original})
    assert stale.status_code == 409
    restored = await async_client.post(endpoint, headers=headers, json={"pathway_id": pathway_case.pathway_id, "status": 0, "expected_source_revision": original + 1})
    assert restored.status_code == 200, restored.text
    db_session.expire_all()
    assert pathway_case.source_revision == original + 2
    assert source_state(db_session, item) == "changed"
    assert eligible_pathway_documents(db_session, [pathway_case.pathway_id], "treatment_pathway", set()) == []


def test_source_revision_migration_preserves_legacy_pathway_content(tmp_path):
    path = tmp_path / "pathway-revision.db"
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE hoimsystem_clinical_pathway (pathway_id INTEGER PRIMARY KEY, steps TEXT, status INTEGER)")
        conn.exec_driver_sql("INSERT INTO hoimsystem_clinical_pathway VALUES (1, '[\"原有措施\"]', 0)")
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.stamp(config, "20261020_pathway_knowledge")
    command.upgrade(config, "20261020_pathway_revision")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT steps, status, source_revision FROM hoimsystem_clinical_pathway")).one() == ('["原有措施"]', 0, 1)
    command.downgrade(config, "20261020_pathway_knowledge")
    assert "source_revision" not in {item["name"] for item in inspect(engine).get_columns("hoimsystem_clinical_pathway")}
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT steps FROM hoimsystem_clinical_pathway")) == '["原有措施"]'
    engine.dispose()
