"""Allow explicitly packaged Prompt version0 without creating governance rows.

Revision ID: 20261021_research_prompt_origin
Revises: 20261021_research_runs
"""

from sqlalchemy import String, text

from alembic import op

revision = "20261021_research_prompt_origin"
down_revision = "20261021_research_runs"
branch_labels = None
depends_on = None

TABLE = "hoimsystem_ai_research_cohort_run_artifact"
POSITIVE = "requested_by>0 AND prompt_version>=0 AND provider_revision>0 AND config_revision>0 AND created_audit_event_id>0 AND (usage_event_id IS NULL OR (usage_event_id>0 AND usage_event_id<>created_audit_event_id))"


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint("ck_rcr_artifact_positive", type_="check")
        batch.alter_column("prompt_id", existing_type=String(36), nullable=True)
        batch.create_check_constraint("ck_rcr_artifact_positive", POSITIVE)
        batch.create_check_constraint("ck_rcr_artifact_prompt_origin", "(prompt_id IS NULL AND prompt_version=0) OR (prompt_id IS NOT NULL AND prompt_version>0)")


def downgrade():
    # The old schema cannot represent a legitimate packaged task. Refuse before
    # any DDL or data mutation rather than delete it or invent a PromptVersion.
    found = op.get_bind().execute(text("SELECT run_id FROM " + TABLE + " WHERE prompt_id IS NULL OR prompt_version=0 LIMIT 1")).first()
    if found is not None:
        raise RuntimeError("Packaged research tasks cannot be represented by the prior database-Prompt-only schema")
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint("ck_rcr_artifact_prompt_origin", type_="check")
        batch.drop_constraint("ck_rcr_artifact_positive", type_="check")
        batch.alter_column("prompt_id", existing_type=String(36), nullable=False)
        batch.create_check_constraint("ck_rcr_artifact_positive", POSITIVE.replace("prompt_version>=0", "prompt_version>0"))
