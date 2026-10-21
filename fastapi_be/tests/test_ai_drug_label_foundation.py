"""Strict source/signature requests and additive migration, no remote models."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.ai import drug_label_contract as c
from app.ai.drug_label_models import DRUG_LABEL_MODELS
from app.database import Base
from app.models import User

PATH = Path(__file__).parents[1] / "alembic/versions/20261021_drug_label_sources.py"
spec = importlib.util.spec_from_file_location("drug_label_migration", PATH)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
NOTE = "已完整阅读目录身份与本次提供版本，逐项保留不确定性。"
H = "a" * 64
UID = "00000000-0000-0000-0000-000000000073"


def request():
    return dict(pharmaceutical_id=1, expected_identity_hash=H, original=dict(original_id=UID, content_hash=H, governance_hash=H), basis_note=NOTE)


@pytest.mark.parametrize("field,value", [("pharmaceutical_id", True), ("pharmaceutical_id", 0), ("expected_identity_hash", "A" * 64), ("basis_note", " " * 40), ("signer_user_id", 1)])
def test_create_rejects_unsafe_or_phantom_fields(field, value):
    body = request()
    body[field] = value
    with pytest.raises(ValidationError):
        c.SourceCreate.model_validate(body)


def test_null_catalog_fields_remain_null_and_bool_status_is_not_zero():
    identity = c.Identity(pharmaceutical_id=1, name=None, barcode=None, status=None)
    assert identity.model_dump() == dict(pharmaceutical_id=1, name=None, barcode=None, status=None)
    with pytest.raises(ValidationError):
        c.Identity(pharmaceutical_id=1, name="药品", barcode=None, status=False)


@pytest.mark.parametrize("outcome", ["confirmed", "not_confirmed", "unknown"])
def test_professional_outcomes_are_explicit_and_never_defaulted(outcome):
    body = dict(expected_revision=1, expected_content_hash=H, expected_governance_hash=H, basis_note=NOTE, catalog_match_review=outcome, provided_text_version_review=outcome)
    assert c.ProfessionalSign.model_validate(body).catalog_match_review == outcome
    del body["catalog_match_review"]
    with pytest.raises(ValidationError):
        c.ProfessionalSign.model_validate(body)


def test_utf8_notes_count_codepoints_and_actual_bytes():
    body = dict(expected_revision=1, expected_content_hash=H, expected_governance_hash=H, basis_note="😀" * 1000)
    assert len(c.RevokeRequest.model_validate(body).basis_note.encode()) == 4000
    with pytest.raises(ValidationError):
        c.RevokeRequest.model_validate({**body, "basis_note": "a" * 1001})
    with pytest.raises(ValidationError):
        c.SourceCreate.model_validate({**request(), "basis_note": "😀" * 1001})


def test_additive_upgrade_down_upgrade_preserves_old_tables_and_rows():
    engine = create_engine("sqlite:///:memory:")
    names = {m.__tablename__ for m in DRUG_LABEL_MODELS}
    with engine.begin() as conn:
        Base.metadata.create_all(conn, tables=[t for t in Base.metadata.sorted_tables if t.name not in names])
        conn.execute(User.__table__.insert().values(user_id=1, username="synthetic73", user_role="super_admin"))

        def ddl(exclude=()):
            return {name: sql for name, sql in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name")) if name not in exclude}

        before = ddl()
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert set(inspect(conn).get_table_names()) - set(before) == names
        assert ddl(names) == before
        assert conn.execute(text("SELECT username FROM hoimsystem_users WHERE user_id=1")).scalar_one() == "synthetic73"
        first = ddl()
        for model in DRUG_LABEL_MODELS:
            actual = {col["name"]: col for col in inspect(conn).get_columns(model.__tablename__)}
            assert set(actual) == set(model.__table__.columns.keys())
            assert {c["name"] for c in inspect(conn).get_check_constraints(model.__tablename__)} == {c.name for c in model.__table__.constraints if c.__class__.__name__ == "CheckConstraint"}
            for col in model.__table__.columns:
                assert actual[col.name]["nullable"] == col.nullable
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
        assert ddl() == before
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert ddl() == first
    engine.dispose()


def test_mysql_ddl_is_two_tables_one_mediumtext_five_utc6():
    compiled = "\n".join(str(CreateTable(m.__table__).compile(dialect=mysql.dialect())) for m in DRUG_LABEL_MODELS)
    assert compiled.count("MEDIUMTEXT") == 1 and compiled.count("DATETIME(6)") == 5
    assert "ON DELETE CASCADE" not in compiled
    assert "fk_drug_label_original" in compiled and "fk_drug_label_prof_source" in compiled
    assert migration.down_revision == "20261021_doc_extraction_runs"


def test_professional_governance_boolean_revision_is_not_integer_one():
    with pytest.raises(ValidationError):
        c.ProfessionalGovernance(status="signed", revision=True, revoked_by=None, revoked_at=None, revoke_reason="")
