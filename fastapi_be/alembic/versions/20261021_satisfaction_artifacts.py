"""Add one task anchor and complete satisfaction result artifact table."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op
from app.sql_constraints import PortableCheckConstraint

revision = "20261021_satisfaction_artifacts"
down_revision = "20261021_satisfaction_sources"
branch_labels = None
depends_on = None


def _hex(name, size=64):
    remaining = name
    for character in "0123456789abcdef":
        remaining = "replace(" + remaining + ",'" + character + "','')"
    return "length(" + name + ")=" + str(size) + " AND length(" + remaining + ")=0"


def upgrade():
    utc = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    body = sa.Column("result_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=True)
    size = sa.Column("result_bytes", sa.Integer(), nullable=True)
    anchors = ("input_hash", "evidence_hash", "metadata_hash", "prompt_hash", "context_digest", "source_binding_hash")
    lease_positions = " AND ".join("substr(accepted_lease," + str(position) + ",1)='-'" for position in (9, 14, 19, 24))
    op.create_table(
        "hoimsystem_ai_satisfaction_run_artifact",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_run.run_id"), nullable=False, primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_satisfaction_case.case_id"), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("created_at", utc, nullable=False),
        *(sa.Column(name, sa.String(64), nullable=False) for name in anchors),
        body,
        sa.Column("result_hash", sa.String(64), nullable=True),
        size,
        sa.Column("receipt_event_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        sa.Column("accepted_lease", sa.String(36), nullable=True),
        sa.Column("accepted_at", utc, nullable=True),
        PortableCheckConstraint("HEX(schema_version)=HEX('satisfaction_run_artifact_v1') AND requested_by>0", name="ck_satisfaction_artifact_schema"),
        *(PortableCheckConstraint(_hex(name), name="ck_satisfaction_artifact_" + name) for name in anchors),
        PortableCheckConstraint("result_hash IS NULL OR (" + _hex("result_hash") + ")", name="ck_satisfaction_artifact_result_hash"),
        PortableCheckConstraint(
            "(result_json IS NULL AND result_hash IS NULL AND result_bytes IS NULL AND receipt_event_id IS NULL AND accepted_lease IS NULL AND accepted_at IS NULL) OR (result_json IS NOT NULL AND result_hash IS NOT NULL AND result_bytes IS NOT NULL AND receipt_event_id IS NOT NULL AND accepted_lease IS NOT NULL AND accepted_at IS NOT NULL)",
            name="ck_satisfaction_artifact_complete_result",
        ),
        PortableCheckConstraint(body.is_(None) | ((size >= 1) & (size <= 8388608) & (sa.func.length(sa.cast(body, sa.LargeBinary())) == size)), name="ck_satisfaction_artifact_exact_bytes"),
        PortableCheckConstraint("receipt_event_id IS NULL OR receipt_event_id>0", name="ck_satisfaction_artifact_receipt"),
        PortableCheckConstraint(
            "accepted_lease IS NULL OR (length(accepted_lease)=36 AND " + lease_positions + " AND " + _hex("replace(accepted_lease,'-','')", 32) + ")", name="ck_satisfaction_artifact_lease"
        ),
        PortableCheckConstraint("accepted_at IS NULL OR accepted_at>=created_at", name="ck_satisfaction_artifact_clock"),
    )


def downgrade():
    op.drop_table("hoimsystem_ai_satisfaction_run_artifact")
