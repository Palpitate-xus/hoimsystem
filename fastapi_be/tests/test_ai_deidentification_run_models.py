"""Physical task-artifact constraints, not task authorization or a worker test."""

import datetime as dt
import hashlib
import json
import uuid

import pytest
from sqlalchemy import ForeignKeyConstraint, text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app.ai.deidentification_run_models import BODY_BYTES, DEIDENTIFICATION_RUN_MODELS, RESULT_SCHEMA, SOURCE_HASH_FIELDS, SOURCE_SCHEMA, AIDeidentificationRunResult, AIDeidentificationRunSource
from app.ai.models import AIAuditEvent, AIPromptVersion, AIProvider, AIRun
from tests.test_ai_deidentification_models import original_case

NOW = dt.datetime(2026, 10, 21, 12, 34, 56, 123456)


@pytest.fixture(autouse=True)
def actual_foreign_keys(db_session):
    db_session.execute(text("PRAGMA foreign_keys=ON"))
    assert db_session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
    yield
    db_session.rollback()


def audit(db, actor, run_id, action):
    row = AIAuditEvent(actor_id=actor, action=action, target=run_id, detail_json="{}", create_time=NOW)
    db.add(row)
    db.flush()
    return row


def artifact(db, seed_data, *, database_prompt=False):
    """Actual FK parents; placeholder bodies test SQL bounds, not source proof."""
    case = original_case(db, seed_data)
    actor = seed_data["admin_user"].user_id
    provider = AIProvider(name="synthetic-deid-" + uuid.uuid4().hex, kind="chat", api_base="https://synthetic.invalid/v1", model="synthetic-literal", created_by=actor)
    db.add(provider)
    db.flush()
    prompt = None
    if database_prompt:
        version = db.query(AIPromptVersion).filter_by(feature_key="deidentification").count() + 1
        prompt = AIPromptVersion(
            prompt_id=str(uuid.uuid4()),
            feature_key="deidentification",
            version=version,
            task_prompt="actual saved synthetic task",
            change_note="synthetic explicit saved version",
            created_by=actor,
        )
        db.add(prompt)
        db.flush()
    run = AIRun(
        run_id=str(uuid.uuid4()), feature_key="deidentification", provider_id=provider.provider_id, requested_by=actor, patient_id=case.patient_id, prompt_hash="a" * 64, context_digest="b" * 64
    )
    db.add(run)
    db.flush()
    event = audit(db, actor, run.run_id, "deidentification.task.create")
    source = AIDeidentificationRunSource(
        run_id=run.run_id,
        case_id=case.case_id,
        scope_id=case.scope_id,
        patient_id=case.patient_id,
        requested_by=actor,
        provider_id=provider.provider_id,
        prompt_version_id=prompt.prompt_id if prompt else None,
        prompt_origin="database_version" if prompt else "packaged_catalog",
        prompt_version=prompt.version if prompt else 0,
        catalog_version="synthetic-test-catalog",
        native_task_version="deidentification_literal_candidates_v1",
        schema_version=SOURCE_SCHEMA,
        created_at=NOW,
        source_json="{}",
        source_bytes=2,
        create_event_id=event.event_id,
        **{field: hashlib.sha256(b"{}").hexdigest() if field == "source_hash" else "a" * 64 for field in SOURCE_HASH_FIELDS},
    )
    db.add(source)
    db.flush()
    return source


def pending(db, source):
    result = AIDeidentificationRunResult(run_id=source.run_id, schema_version=RESULT_SCHEMA, created_at=NOW)
    db.add(result)
    db.flush()
    return result


def accepted(db, source):
    result = pending(db, source)
    result.usage_event_id = audit(db, source.requested_by, source.run_id, "deidentification.task.usage").event_id
    result.accept_event_id = audit(db, source.requested_by, source.run_id, "deidentification.task.accept").event_id
    result.result_json = "{}"
    result.result_bytes = 2
    result.result_hash = hashlib.sha256(b"{}").hexdigest()
    result.accepted_lease = str(uuid.uuid4())
    result.accepted_at = NOW + dt.timedelta(microseconds=1)
    db.flush()
    return result


def test_exact_two_tables_mysql_compile_utf8_bounds_real_fk_and_seconds():
    ddls = [str(CreateTable(model.__table__).compile(dialect=mysql.dialect())) for model in DEIDENTIFICATION_RUN_MODELS]
    assert sum(ddl.count("DATETIME(6)") for ddl in ddls) == 3
    assert sum(ddl.count("MEDIUMTEXT") for ddl in ddls) == 2
    assert sum(isinstance(c, ForeignKeyConstraint) for model in DEIDENTIFICATION_RUN_MODELS for c in model.__table__.constraints) == 13
    assert all("8388608" in ddl and "CAST(" in ddl and " AS BINARY)" in ddl and "json_valid" in ddl for ddl in ddls)
    assert all("AUTO_INCREMENT" not in ddl and "REGEXP" not in ddl for ddl in ddls)
    assert all(len(c.name or "") <= 64 for model in DEIDENTIFICATION_RUN_MODELS for c in model.__table__.constraints)


@pytest.mark.parametrize("database_prompt", [False, True])
def test_actual_packaged_version_zero_and_real_saved_prompt_roundtrip(db_session, seed_data, database_prompt):
    db = db_session
    source = artifact(db, seed_data, database_prompt=database_prompt)
    pending(db, source)
    db.commit()
    db.refresh(source)
    assert source.prompt_version > 0 if database_prompt else source.prompt_version == 0
    assert (source.prompt_version_id is not None) is database_prompt
    assert source.created_at == NOW
    assert source.source_bytes == len(source.source_json.encode("utf-8"))
    assert db.query(AIPromptVersion).filter(AIPromptVersion.prompt_id == source.prompt_version_id).count() == int(database_prompt)


@pytest.mark.parametrize(
    "changes",
    [
        {"prompt_origin": "packaged_catalog", "prompt_version": 1},
        {"prompt_origin": "database_version", "prompt_version": 1, "prompt_version_id": None},
        {"prompt_origin": "DATABASE_VERSION"},
        {"prompt_origin": "unknown"},
        {"prompt_version": -1},
        {"catalog_version": ""},
        {"native_task_version": ""},
        {"schema_version": SOURCE_SCHEMA.upper()},
        {"source_hash": "A" * 64},
        {"source_hash": "a" * 63},
        {"source_bytes": 1},
        {"source_bytes": 0},
        {"source_json": "{not-json}", "source_bytes": 10},
    ],
)
def test_source_closed_prompt_hash_schema_and_byte_constraints(db_session, seed_data, changes):
    source = artifact(db_session, seed_data)
    for key, value in changes.items():
        setattr(source, key, value)
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize("foreign", ["run_id", "case_id", "scope_id", "patient_id", "requested_by", "provider_id", "create_event_id", "prompt_version_id"])
def test_missing_real_parent_fk_rejects_without_dangling_anchor(db_session, seed_data, foreign):
    source = artifact(db_session, seed_data, database_prompt=foreign == "prompt_version_id")
    setattr(source, foreign, str(uuid.uuid4()) if foreign.endswith("_id") and foreign not in {"patient_id", "provider_id", "create_event_id"} else 2147483647)
    if foreign == "requested_by":
        source.requested_by = 2147483647
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_pending_and_usage_only_failure_have_no_fake_result_or_acceptance(db_session, seed_data):
    db = db_session
    source = artifact(db, seed_data)
    result = pending(db, source)
    assert result.result_json is result.result_hash is result.result_bytes is result.accept_event_id is result.accepted_lease is result.accepted_at is None
    result.usage_event_id = audit(db, source.requested_by, source.run_id, "deidentification.task.usage").event_id
    db.commit()
    db.refresh(result)
    assert result.usage_event_id > 0 and result.accept_event_id is None and result.result_json is None


@pytest.mark.parametrize("missing", ["result_json", "result_hash", "result_bytes", "usage_event_id", "accept_event_id", "accepted_lease", "accepted_at"])
def test_each_missing_acceptance_member_rejected_even_under_sql_null_logic(db_session, seed_data, missing):
    source = artifact(db_session, seed_data)
    result = accepted(db_session, source)
    setattr(result, missing, None)
    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    "field,value",
    [
        ("result_hash", "A" * 64),
        ("result_bytes", 1),
        ("result_bytes", 0),
        ("schema_version", RESULT_SCHEMA.upper()),
        ("result_json", "invalid"),
        ("accepted_lease", "A" * 36),
        ("accepted_lease", "a" * 36),
        ("accepted_lease", "00000000-0000-0000-0000-00000000000G"),
        ("accepted_at", NOW - dt.timedelta(microseconds=1)),
    ],
)
def test_invalid_complete_acceptance_shape_rejected(db_session, seed_data, field, value):
    source = artifact(db_session, seed_data)
    result = accepted(db_session, source)
    setattr(result, field, value)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_usage_and_acceptance_must_be_two_distinct_real_audit_pks(db_session, seed_data):
    source = artifact(db_session, seed_data)
    result = accepted(db_session, source)
    assert len({source.create_event_id, result.usage_event_id, result.accept_event_id}) == 3
    result.accept_event_id = result.usage_event_id
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize("foreign", ["run_id", "usage_event_id", "accept_event_id"])
def test_result_requires_actual_source_and_specific_audit_rows(db_session, seed_data, foreign):
    source = artifact(db_session, seed_data)
    result = accepted(db_session, source)
    setattr(result, foreign, str(uuid.uuid4()) if foreign == "run_id" else 2147483647)
    with pytest.raises(IntegrityError):
        db_session.flush()


def exact_json(size):
    overhead = len(b'{"text":""}')
    emoji, rest = divmod(size - overhead, 4)
    raw = json.dumps({"text": "😀" * emoji + "a" * rest}, ensure_ascii=False, separators=(",", ":"))
    assert len(raw.encode("utf-8")) == size
    return raw


def test_source_and_result_each_exact_eight_mib_and_utf8_roundtrip_without_combined_http_claim(db_session, seed_data):
    db = db_session
    source = artifact(db, seed_data)
    result = accepted(db, source)
    raw = exact_json(BODY_BYTES)
    source.source_json = result.result_json = raw
    source.source_bytes = result.result_bytes = BODY_BYTES
    source.source_hash = result.result_hash = hashlib.sha256(raw.encode()).hexdigest()
    db.commit()
    db.expire_all()
    actual_source = db.get(AIDeidentificationRunSource, source.run_id)
    actual_result = db.get(AIDeidentificationRunResult, source.run_id)
    assert actual_source.source_json == actual_result.result_json == raw
    assert actual_source.source_hash == actual_result.result_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert actual_result.accepted_at == NOW + dt.timedelta(microseconds=1)


@pytest.mark.parametrize("which", ["source", "result"])
def test_whole_oversize_json_rejected_without_truncation(db_session, seed_data, which):
    source = artifact(db_session, seed_data)
    result = accepted(db_session, source)
    raw = exact_json(BODY_BYTES + 1)
    if which == "source":
        source.source_json, source.source_bytes = raw, BODY_BYTES + 1
    else:
        result.result_json, result.result_bytes = raw, BODY_BYTES + 1
    with pytest.raises(IntegrityError):
        db_session.flush()
