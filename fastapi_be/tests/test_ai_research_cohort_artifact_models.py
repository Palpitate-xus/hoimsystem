"""Actual synthetic SQL storage constraints, not a runtime/worker claim."""

import copy
import hashlib
import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, func, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai.models import AIAuditEvent, AIPromptVersion, AIProvider, AIRun
from app.ai.research_cohort_artifact_models import ANCHOR_HASHES, ARTIFACT_SCHEMA, RESEARCH_COHORT_RUN_MODELS, RESULT_SCHEMA, AIResearchCohortRunArtifact, AIResearchCohortRunResult
from app.ai.research_cohort_cases import binding_for
from app.ai.research_cohort_contract import canonical_json
from app.ai.research_cohort_draft import COVERAGE, digest
from app.ai.research_cohort_prompt import RESEARCH_SYSTEM_PROMPT, RESEARCH_TASK_PROMPT, instructions_for
from app.ai.research_cohort_result import result_for_draft
from app.ai.research_cohort_sources import utcnow
from app.database import Base
from tests.test_ai_research_cohort_cases import published
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


@pytest.fixture(autouse=True)
def artifact_foreign_keys(db_session):
    # Legacy shared SQLite fixtures default to FK OFF. These tests verify real
    # FK failures on their own connection and restore the original setting.
    previous = db_session.execute(text("PRAGMA foreign_keys")).scalar_one()
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    try:
        yield
    finally:
        db_session.rollback()
        db_session.execute(text("PRAGMA foreign_keys=" + str(previous)))
        db_session.commit()


@pytest.fixture
def storage_rows(db_session, research_case):
    db, case = db_session, research_case
    _, _, _, _, full = published(db, case, external_model_use="recorded_permitted")
    source = full["public_source"]
    user_id = case["admin_user"].user_id
    provider = AIProvider(name="isolated-research-" + uuid.uuid4().hex, kind="chat", api_base="https://synthetic.invalid", model="synthetic-no-call", created_by=user_id)
    version = db.query(func.coalesce(func.max(AIPromptVersion.version), 0)).filter_by(feature_key="research_cohort").scalar() + 1
    prompt = AIPromptVersion(feature_key="research_cohort", version=version, task_prompt=RESEARCH_TASK_PROMPT, change_note="Synthetic ORM fixture, no dispatch", created_by=user_id)
    db.add_all([provider, prompt])
    db.flush()
    run = AIRun(
        feature_key="research_cohort",
        requested_by=user_id,
        provider_id=provider.provider_id,
        provider_revision=1,
        prompt_version=version,
        prompt_hash=hashlib.sha256(instructions_for(RESEARCH_TASK_PROMPT).encode()).hexdigest(),
        context_digest="1" * 64,
        status="running",
        lease_token=str(uuid.uuid4()),
        input_json=canonical_json({"research_cohort_case_id": full["case_id"]}),
        evidence_json="[]",
        context_metadata_json="{}",
    )
    db.add(run)
    db.flush()
    created = AIAuditEvent(actor_id=user_id, action="research.artifact.model_fixture", target=run.run_id, detail_json="{}")
    db.add(created)
    db.flush()
    binding = binding_for(full, source)
    prompt_snapshot = {"system": RESEARCH_SYSTEM_PROMPT, "task": RESEARCH_TASK_PROMPT}
    # These fixture frames prove only model/DDL constraints. Future storage
    # services must independently validate their full semantic closure.
    execution_snapshot = {"schema_version": "synthetic_orm_frame_not_runtime", "model": provider.model}
    values = {
        "run_id": run.run_id,
        "case_id": full["case_id"],
        "scope_id": full["scope_id"],
        "requested_by": user_id,
        "schema_version": ARTIFACT_SCHEMA,
        "recorded_at": utcnow(),
        "source_json": canonical_json(source),
        "source_bytes": len(canonical_json(source).encode("utf-8")),
        "source_projection_hash": digest(source),
        "source_binding_json": canonical_json(binding),
        "source_binding_hash": digest(binding),
        "prompt_id": prompt.prompt_id,
        "prompt_version": version,
        "prompt_snapshot_json": canonical_json(prompt_snapshot),
        "prompt_snapshot_hash": digest(prompt_snapshot),
        "provider_id": provider.provider_id,
        "provider_revision": 1,
        "config_revision": 1,
        "execution_snapshot_json": canonical_json(execution_snapshot),
        "execution_snapshot_hash": digest(execution_snapshot),
        "instructions_digest": run.prompt_hash,
        "context_digest": run.context_digest,
        "input_hash": digest({"research_cohort_case_id": full["case_id"]}),
        "evidence_hash": digest([]),
        "metadata_hash": digest({}),
        "created_audit_event_id": created.event_id,
        "usage_event_id": None,
    }
    db.commit()
    return db, run.run_id, source, values


def test_mysql_models_use_separate_bounded_mediumtext_utc6_and_real_foreign_keys():
    ddl = "\n".join(str(CreateTable(model.__table__).compile(dialect=mysql.dialect())) for model in RESEARCH_COHORT_RUN_MODELS)
    assert ddl.count("MEDIUMTEXT") == 4 and ddl.count("DATETIME(6)") == 2
    assert "AUTO_INCREMENT" not in ddl and "json_valid" in ddl and "BINARY" in ddl
    artifact = AIResearchCohortRunArtifact.__table__
    assert {"run_id", "case_id", "scope_id", "requested_by", "prompt_id", "provider_id", "created_audit_event_id", "usage_event_id", "dispatch_event_id"} == {
        next(iter(fk.columns)).name for fk in artifact.foreign_key_constraints
    }
    assert set(ANCHOR_HASHES) <= set(artifact.columns.keys())
    assert "usage_event_id IS NULL" in ddl and "uq_rcr_accept_audit" in ddl


def test_actual_split_source_retains_all_bytes_while_run_raw_three_remain_short(storage_rows):
    db, run_id, source, values = storage_rows
    db.add(AIResearchCohortRunArtifact(**values))
    db.commit()
    row = db.get(AIResearchCohortRunArtifact, run_id)
    assert row.source_json == canonical_json(source) and row.source_bytes == len(row.source_json.encode("utf-8"))
    run = db.get(AIRun, run_id)
    assert all(len(getattr(run, name).encode("utf-8")) <= 65535 for name in ("input_json", "evidence_json", "context_metadata_json"))
    assert "outcomes" not in run.input_json and "identity_secret" not in row.source_json
    assert row.usage_event_id is None


@pytest.mark.parametrize("change", ["character_count_is_not_utf8_bytes", "invalid_json", "invalid_hash", "wrong_prompt_fk", "usage_is_not_creation_receipt", "over_source_budget"])
def test_actual_sql_rejects_malformed_artifacts_without_accepting_partial_source(storage_rows, change):
    db, _, _, original = storage_rows
    values = copy.deepcopy(original)
    if change == "character_count_is_not_utf8_bytes":
        values["source_bytes"] = len(values["source_json"])
        assert values["source_bytes"] != len(values["source_json"].encode("utf-8"))
    elif change == "invalid_json":
        values.update(source_json="{", source_bytes=1)
    elif change == "invalid_hash":
        values["source_projection_hash"] = "G" * 64
    elif change == "wrong_prompt_fk":
        values["prompt_id"] = str(uuid.uuid4())
    elif change == "usage_is_not_creation_receipt":
        values["usage_event_id"] = values["created_audit_event_id"]
    else:
        values["source_json"] = canonical_json({"text": "x" * (8 * 1024 * 1024)})
        values["source_bytes"] = len(values["source_json"].encode())
    db.add(AIResearchCohortRunArtifact(**values))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
    assert db.query(AIResearchCohortRunArtifact).filter_by(run_id=original["run_id"]).count() == 0


def test_actual_result_and_usage_have_distinct_specific_audit_keys_and_current_lease_bytes(storage_rows):
    db, run_id, source, values = storage_rows
    db.add(AIResearchCohortRunArtifact(**values))
    db.flush()
    run = db.get(AIRun, run_id)
    usage = AIAuditEvent(actor_id=values["requested_by"], action="research.usage.model_fixture", target=run_id, detail_json="{}")
    accept = AIAuditEvent(actor_id=values["requested_by"], action="research.accept.model_fixture", target=run_id, detail_json="{}")
    db.add_all([usage, accept])
    db.flush()
    assert len({usage.event_id, accept.event_id, values["created_audit_event_id"]}) == 3
    db.get(AIResearchCohortRunArtifact, run_id).usage_event_id = usage.event_id
    draft = {"schema_version": "research_cohort_questions_v1", "research_source_id": source["source_id"], "source_projection_hash": digest(source), "coverage": COVERAGE, "questions": []}
    body = result_for_draft(draft, source)
    raw = canonical_json(body)
    db.add(
        AIResearchCohortRunResult(
            run_id=run_id,
            case_id=values["case_id"],
            scope_id=values["scope_id"],
            schema_version=RESULT_SCHEMA,
            lease_token=run.lease_token,
            accepted_at=utcnow(),
            result_json=raw,
            result_bytes=len(raw.encode()),
            content_hash=digest(body),
            source_binding_hash=values["source_binding_hash"],
            instructions_digest=values["instructions_digest"],
            accept_audit_event_id=accept.event_id,
        )
    )
    db.commit()
    stored = db.get(AIResearchCohortRunResult, run_id)
    assert stored.result_json == raw and stored.lease_token == run.lease_token
    assert stored.accept_audit_event_id == accept.event_id and db.get(AIResearchCohortRunArtifact, run_id).usage_event_id == usage.event_id


def test_incremental_frozen_migration_up_down_up_preserves_all_prior_source_and_business_ddl():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/20261021_research_runs.py"
    spec = importlib.util.spec_from_file_location("isolated_research_runs_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "20261021_research_cohort"
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enforce_foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    new = {model.__tablename__ for model in RESEARCH_COHORT_RUN_MODELS}
    old = [table for name, table in Base.metadata.tables.items() if name not in new]
    Base.metadata.create_all(engine, tables=old)
    with engine.begin() as conn:
        conn.execute(Base.metadata.tables["hoimsystem_users"].insert().values(user_id=987653, username='synthetic-research-artifact', user_role='admin'))
        before = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
        for action in ("upgrade", "downgrade", "upgrade"):
            migration.op = Operations(MigrationContext.configure(conn))
            getattr(migration, action)()
            assert set(inspect(conn).get_table_names()) == {table.name for table in old} | (new if action == "upgrade" else set())
            after = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
            assert [row for row in after if row.tbl_name not in new] == before
            assert conn.execute(text("SELECT username FROM hoimsystem_users WHERE user_id=987653")).scalar_one() == "synthetic-research-artifact"
            if action == "upgrade":
                for model in RESEARCH_COHORT_RUN_MODELS:
                    assert {value["name"] for value in inspect(conn).get_columns(model.__tablename__)} == set(model.__table__.columns.keys()) - (
                        {"dispatch_event_id"} if model is AIResearchCohortRunArtifact else set()
                    )
                    assert {value["name"] for value in inspect(conn).get_indexes(model.__tablename__)} == {index.name for index in model.__table__.indexes}
                    # This original migration is the frozen database-Prompt-only
                    # stage. A later additive revision permits packaged version0.
                    expected = len([value for value in model.__table__.constraints if value.__class__.__name__ == "CheckConstraint"])
                    assert len(inspect(conn).get_check_constraints(model.__tablename__)) == expected - (2 if model is AIResearchCohortRunArtifact else 0)
                    if model is AIResearchCohortRunArtifact:
                        assert next(value for value in inspect(conn).get_columns(model.__tablename__) if value["name"] == "prompt_id")["nullable"] is False
                    assert len(inspect(conn).get_foreign_keys(model.__tablename__)) == len(model.__table__.foreign_key_constraints) - (model is AIResearchCohortRunArtifact)
    engine.dispose()
