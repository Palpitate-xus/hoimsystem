"""Incremental nullable Prompt FK, no fabricated version/governance records."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, event, inspect, text

from app.ai.research_cohort_artifact_models import RESEARCH_COHORT_RUN_MODELS, AIResearchCohortRunArtifact
from app.database import Base


def migration(name):
    path = Path(__file__).resolve().parents[1] / "alembic/versions" / name
    spec = importlib.util.spec_from_file_location("isolated_" + path.stem, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_full_research_artifact_incremental_chain_up_down_up_preserves_prior_ddl_and_rows():
    original = migration("20261021_research_runs.py")
    origin = migration("20261021_research_prompt_origin.py")
    assert origin.down_revision == original.revision
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def foreign_keys(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    new = {model.__tablename__ for model in RESEARCH_COHORT_RUN_MODELS}
    Base.metadata.create_all(engine, tables=[table for name, table in Base.metadata.tables.items() if name not in new])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO hoimsystem_users(user_id,username,user_role) VALUES(987652,'synthetic-prompt-origin','admin')"))
        before = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
        for phase in ("upgrade", "downgrade", "upgrade"):
            steps = ((original, "upgrade"), (origin, "upgrade")) if phase == "upgrade" else ((origin, "downgrade"), (original, "downgrade"))
            for change, action in steps:
                change.op = Operations(MigrationContext.configure(conn))
                getattr(change, action)()
            current = conn.execute(text("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name")).all()
            assert [row for row in current if row.tbl_name not in new] == before
            assert conn.execute(text("SELECT username FROM hoimsystem_users WHERE user_id=987652")).scalar_one() == "synthetic-prompt-origin"
            if phase == "upgrade":
                for model in RESEARCH_COHORT_RUN_MODELS:
                    assert {value["name"] for value in inspect(conn).get_columns(model.__tablename__)} == set(model.__table__.columns.keys()) - (
                        {"dispatch_event_id"} if model is AIResearchCohortRunArtifact else set()
                    )
                    assert len(inspect(conn).get_check_constraints(model.__tablename__)) == len([value for value in model.__table__.constraints if value.__class__.__name__ == "CheckConstraint"]) - (
                        model is AIResearchCohortRunArtifact
                    )
                    assert len(inspect(conn).get_foreign_keys(model.__tablename__)) == len(model.__table__.foreign_key_constraints) - (model is AIResearchCohortRunArtifact)
                columns = inspect(conn).get_columns("hoimsystem_ai_research_cohort_run_artifact")
                assert next(value for value in columns if value["name"] == "prompt_id")["nullable"] is True
    engine.dispose()
