"""Complete private AI charge task anchors and optional bounded result bodies."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op
from schema_constraints_v1 import PortableCheckConstraint

revision = "20261021_charge_runs"
down_revision = "20261021_charge_cases"
branch_labels = None
depends_on = None


def lower_hex_sql(name, size=64):
    remaining = name
    for character in "0123456789abcdef":
        remaining = "replace(" + remaining + ",'" + character + "','')"
    return "length(" + name + ")=" + str(size) + " AND length(" + remaining + ")=0"


def lease_sql():
    positions = " AND ".join("substr(accepted_lease," + str(position) + ",1)='-'" for position in (9, 14, 19, 24))
    return "accepted_lease IS NULL OR (length(accepted_lease)=36 AND " + positions + " AND " + lower_hex_sql("replace(accepted_lease,'-','')", 32) + ")"


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
        PortableCheckConstraint("HEX(schema_version)=HEX('charge_run_artifact_v1') AND requested_by>0", name="ck_charge_artifact_schema_actor"),
        *(PortableCheckConstraint(lower_hex_sql(name), name="ck_charge_artifact_" + name) for name in hash_fields),
        PortableCheckConstraint("result_hash IS NULL OR (" + lower_hex_sql("result_hash") + ")", name="ck_charge_artifact_result_hash"),
        PortableCheckConstraint(
            "(result_json IS NULL AND result_hash IS NULL AND result_bytes IS NULL) OR (result_json IS NOT NULL AND result_hash IS NOT NULL AND result_bytes IS NOT NULL)",
            name="ck_charge_artifact_result_tuple",
        ),
        PortableCheckConstraint(
            result_json.is_(None) | ((result_bytes >= 1) & (result_bytes <= 8388608) & (sa.func.length(sa.cast(result_json, sa.LargeBinary)) == result_bytes)),
            name="ck_charge_artifact_exact_bytes",
        ),
        PortableCheckConstraint("receipt_event_id IS NULL OR receipt_event_id>0", name="ck_charge_artifact_receipt"),
        PortableCheckConstraint(lease_sql(), name="ck_charge_artifact_lease"),
    )


def downgrade():
    op.drop_table("hoimsystem_ai_charge_run_artifact")
