"""Add a separate exact terminal usage receipt to the new satisfaction artifact."""

import sqlalchemy as sa

from alembic import op

revision = "20261021_sat_usage_receipt"
down_revision = "20261021_satisfaction_artifacts"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("hoimsystem_ai_satisfaction_run_artifact") as batch:
        batch.add_column(sa.Column("usage_event_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_sat_artifact_usage", "hoimsystem_ai_audit_event", ["usage_event_id"], ["event_id"])
        batch.create_unique_constraint("uq_sat_artifact_usage", ["usage_event_id"])
        batch.create_check_constraint("ck_sat_artifact_usage", "usage_event_id IS NULL OR usage_event_id>0")


def downgrade():
    with op.batch_alter_table("hoimsystem_ai_satisfaction_run_artifact") as batch:
        batch.drop_constraint("ck_sat_artifact_usage", type_="check")
        batch.drop_constraint("fk_sat_artifact_usage", type_="foreignkey")
        batch.drop_constraint("uq_sat_artifact_usage", type_="unique")
        batch.drop_column("usage_event_id")
