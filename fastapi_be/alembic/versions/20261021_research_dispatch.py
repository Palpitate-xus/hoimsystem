"""Persist one dispatch reservation before model I/O; never replay a claim.

Revision ID: 20261021_research_dispatch
Revises: 20261021_research_prompt_origin
"""

from sqlalchemy import Column, Integer, text

from alembic import op

revision = "20261021_research_dispatch"
down_revision = "20261021_research_prompt_origin"
branch_labels = None
depends_on = None

TABLE = "hoimsystem_ai_research_cohort_run_artifact"
CHECK = "dispatch_event_id IS NULL OR (dispatch_event_id>0 AND dispatch_event_id<>created_audit_event_id AND (usage_event_id IS NULL OR dispatch_event_id<>usage_event_id))"


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(Column("dispatch_event_id", Integer, nullable=True))
        batch.create_foreign_key("fk_rcr_dispatch_audit", "hoimsystem_ai_audit_event", ["dispatch_event_id"], ["event_id"])
        batch.create_unique_constraint("uq_rcr_dispatch_audit", ["dispatch_event_id"])
        batch.create_check_constraint("ck_rcr_artifact_dispatch", CHECK)


def downgrade():
    found = op.get_bind().execute(text("SELECT run_id FROM " + TABLE + " WHERE dispatch_event_id IS NOT NULL LIMIT 1")).first()
    if found is not None:
        raise RuntimeError("Dispatched research tasks cannot lose their durable non-replay audit identity")
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint("ck_rcr_artifact_dispatch", type_="check")
        batch.drop_constraint("fk_rcr_dispatch_audit", type_="foreignkey")
        batch.drop_constraint("uq_rcr_dispatch_audit", type_="unique")
        batch.drop_column("dispatch_event_id")
