"""Complete private AI charge task anchors and optional bounded result bodies."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_charge_runs"
down_revision = "20261021_charge_cases"
branch_labels = None
depends_on = None


def upgrade():
    result_json = sa.Column("result_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=True)
    result_bytes = sa.Column("result_bytes", sa.Integer(), nullable=True)
    hash_fields = ("input_hash", "evidence_hash", "metadata_hash", "prompt_hash", "context_digest", "source_binding_hash")
    op.create_table(
        "hoimsystem_ai_charge_run_artifact",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        sa.Column("case_snapshot_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_charge_case_snapshot.case_snapshot_id"), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("created_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        *(sa.Column(name, sa.String(64), nullable=False) for name in hash_fields),
        result_json,
        sa.Column("result_hash", sa.String(64), nullable=True),
        result_bytes,
        sa.Column("receipt_event_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True),
        sa.Column("accepted_lease", sa.String(36), nullable=True),
        sa.CheckConstraint("HEX(schema_version)=HEX('charge_run_artifact_v1') AND requested_by>0", name="ck_charge_artifact_schema_actor"),
        *(sa.CheckConstraint("HEX(" + name + ") REGEXP '^(3[0-9]|6[1-6]){64}$'", name="ck_charge_artifact_" + name) for name in hash_fields),
        sa.CheckConstraint("result_hash IS NULL OR HEX(result_hash) REGEXP '^(3[0-9]|6[1-6]){64}$'", name="ck_charge_artifact_result_hash"),
        sa.CheckConstraint(
            "(result_json IS NULL AND result_hash IS NULL AND result_bytes IS NULL) OR (result_json IS NOT NULL AND result_hash IS NOT NULL AND result_bytes IS NOT NULL)",
            name="ck_charge_artifact_result_tuple",
        ),
        sa.CheckConstraint(
            result_json.is_(None) | ((result_bytes >= 1) & (result_bytes <= 8388608) & (sa.func.length(sa.cast(result_json, sa.LargeBinary)) == result_bytes)),
            name="ck_charge_artifact_exact_bytes",
        ),
        sa.CheckConstraint("receipt_event_id IS NULL OR receipt_event_id>0", name="ck_charge_artifact_receipt"),
        sa.CheckConstraint(
            "accepted_lease IS NULL OR (accepted_lease REGEXP '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$' AND HEX(accepted_lease)=HEX(LOWER(accepted_lease)))",
            name="ck_charge_artifact_lease",
        ),
    )


def downgrade():
    op.drop_table("hoimsystem_ai_charge_run_artifact")
