"""Retain exact claim and one-shot dispatch Audit identities incrementally.

Revision ID: 20261021_deid_dispatch
Revises: 20261021_deid_runs
"""

from sqlalchemy import Column, Integer, text

from alembic import op

revision = "20261021_deid_dispatch"
down_revision = "20261021_deid_runs"
branch_labels = None
depends_on = None
TABLE = "hoimsystem_ai_deidentification_run_result"
CLAIM_CHECK = "claim_event_id IS NULL OR (claim_event_id>0 AND (usage_event_id IS NULL OR claim_event_id<>usage_event_id) AND (accept_event_id IS NULL OR claim_event_id<>accept_event_id))"
DISPATCH_CHECK = "dispatch_event_id IS NULL OR (dispatch_event_id>0 AND claim_event_id IS NOT NULL AND dispatch_event_id<>claim_event_id AND (usage_event_id IS NULL OR dispatch_event_id<>usage_event_id) AND (accept_event_id IS NULL OR dispatch_event_id<>accept_event_id))"


def upgrade():
    with op.batch_alter_table(TABLE) as batch:
        for field in ("claim_event_id", "dispatch_event_id"):
            short = "claim" if field == "claim_event_id" else "dispatch"
            batch.add_column(Column(field, Integer, nullable=True))
            batch.create_foreign_key("fk_deid_" + short + "_audit", "hoimsystem_ai_audit_event", [field], ["event_id"])
            batch.create_unique_constraint("uq_deid_" + short + "_audit", [field])
        batch.create_check_constraint("ck_deid_result_claim", CLAIM_CHECK)
        batch.create_check_constraint("ck_deid_result_dispatch", DISPATCH_CHECK)


def downgrade():
    found = op.get_bind().execute(text("SELECT run_id FROM " + TABLE + " WHERE claim_event_id IS NOT NULL OR dispatch_event_id IS NOT NULL LIMIT 1")).first()
    if found is not None:
        raise RuntimeError("Claimed deidentification tasks cannot lose their original one-shot Audit identity")
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint("ck_deid_result_dispatch", type_="check")
        batch.drop_constraint("ck_deid_result_claim", type_="check")
        for short in ("dispatch", "claim"):
            batch.drop_constraint("fk_deid_" + short + "_audit", type_="foreignkey")
            batch.drop_constraint("uq_deid_" + short + "_audit", type_="unique")
            batch.drop_column(short + "_event_id")
