"""Hospital templates are usable only through scoped, current reviewed snapshots."""

import datetime
import json
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.ai.governance import digest
from app.ai.models import AIKnowledgeDocument, utcnow
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


@pytest.mark.parametrize("value", ["[]", "not-json", "[1]", '[""]', "[{}]", '{"steps":true}', '["x",NaN]', "[" * 1001])
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
