"""Incremental anti-replay FK migration; preserve all earlier revision meaning."""

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

from app.ai.models import AIAuditEvent
from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
from tests.test_ai_research_cohort_artifact_models import artifact_foreign_keys as artifact_foreign_keys  # noqa: F401
from tests.test_ai_research_cohort_artifact_models import storage_rows as storage_rows  # noqa: F401
from tests.test_ai_research_cohort_prompt_origin_migration import migration
from tests.test_ai_research_cohort_sources import research_case as research_case  # noqa: F401


def test_dispatch_fk_and_unique_identity_are_in_actual_mysql_compiled_model():
    ddl = str(CreateTable(AIResearchCohortRunArtifact.__table__).compile(dialect=mysql.dialect()))
    assert "fk_rcr_dispatch_audit" in ddl and "uq_rcr_dispatch_audit" in ddl and "ck_rcr_artifact_dispatch" in ddl
    assert "dispatch_event_id IS NULL" in ddl and "dispatch_event_id<>usage_event_id" in ddl
    assert migration("20261021_research_dispatch.py").down_revision == "20261021_research_prompt_origin"


def test_actual_incremental_down_up_down_up_preserves_prior_source_artifact_rows_and_every_other_ddl(storage_rows):
    db, _, _, values = storage_rows
    db.add(AIResearchCohortRunArtifact(**values))
    db.commit()
    change = migration("20261021_research_dispatch.py")
    table = AIResearchCohortRunArtifact.__tablename__
    conn = db.connection()
    before = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND tbl_name<>:table ORDER BY type,name"), {"table": table}).all()
    source = conn.execute(text("SELECT run_id,source_json,source_bytes,prompt_id,prompt_version,created_audit_event_id FROM " + table)).all()
    for phase in ("downgrade", "upgrade", "downgrade", "upgrade"):
        change.op = Operations(MigrationContext.configure(conn))
        getattr(change, phase)()
        after = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' AND tbl_name<>:table ORDER BY type,name"), {"table": table}).all()
        assert after == before
        assert conn.execute(text("SELECT run_id,source_json,source_bytes,prompt_id,prompt_version,created_audit_event_id FROM " + table)).all() == source
        columns = {item["name"] for item in inspect(conn).get_columns(table)}
        assert ("dispatch_event_id" in columns) == (phase == "upgrade")
        if phase == "upgrade":
            assert columns == set(AIResearchCohortRunArtifact.__table__.columns.keys())
            assert {tuple(fk["constrained_columns"]) for fk in inspect(conn).get_foreign_keys(table)} == {
                tuple(column.name for column in fk.columns) for fk in AIResearchCohortRunArtifact.__table__.foreign_key_constraints
            }
    db.rollback()


def test_dispatched_rows_cannot_be_downgraded_by_losing_the_nonreplay_identity(storage_rows):
    db, run_id, _, values = storage_rows
    reservation = AIAuditEvent(actor_id=values["requested_by"], action="synthetic.migration.dispatch", target=run_id, detail_json="{}")
    db.add(reservation)
    db.flush()
    db.add(AIResearchCohortRunArtifact(**values, dispatch_event_id=reservation.event_id))
    db.commit()
    change = migration("20261021_research_dispatch.py")
    conn = db.connection()
    before = conn.execute(text("SELECT sql FROM sqlite_master WHERE name=:name"), {"name": AIResearchCohortRunArtifact.__tablename__}).scalar()
    change.op = Operations(MigrationContext.configure(conn))
    with pytest.raises(RuntimeError, match="cannot lose"):
        change.downgrade()
    assert conn.execute(text("SELECT sql FROM sqlite_master WHERE name=:name"), {"name": AIResearchCohortRunArtifact.__tablename__}).scalar() == before
    assert conn.execute(text("SELECT dispatch_event_id FROM hoimsystem_ai_research_cohort_run_artifact WHERE run_id=:id"), {"id": run_id}).scalar() == reservation.event_id
