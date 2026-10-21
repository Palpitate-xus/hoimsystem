"""Add complete comparison task artifacts and lease-bound result storage."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_document_change_runs"
down_revision = "20261021_document_change"
branch_labels = None
depends_on = None

HASH_FIELDS = (
    "scope_content_hash",
    "scope_governance_hash",
    "baseline_original_content_hash",
    "baseline_original_governance_hash",
    "candidate_original_content_hash",
    "candidate_original_governance_hash",
    "inventory_hash",
    "source_digest",
    "prompt_hash",
    "context_digest",
    "input_hash",
    "evidence_hash",
    "metadata_hash",
)


def utc6():
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def medium_text():
    return sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def hash_constraint(field, prefix):
    remainder = field
    for character in "0123456789abcdef":
        remainder = f"replace({remainder}, '{character}', '')"
    return sa.CheckConstraint(f"length({field}) = 64 AND length({remainder}) = 0", name=f"ck_dcr_{prefix}_{field}")


def upgrade():
    op.create_table(
        "hoimsystem_ai_document_change_run_artifact",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        sa.Column("scope_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_document_change_scope.scope_id"), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("recorded_at", utc6(), nullable=False),
        sa.Column("baseline_original_id", sa.String(36), nullable=False),
        sa.Column("candidate_original_id", sa.String(36), nullable=False),
        *(sa.Column(name, sa.String(64), nullable=False) for name in HASH_FIELDS),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.Column("source_bytes", sa.Integer(), nullable=False),
        sa.Column("source_json", medium_text(), nullable=False),
        sa.Column("scope_governance_json", sa.Text(), nullable=False),
        sa.Column("scope_created_audit_event_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False),
        sa.Column("scope_review_audit_event_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False),
        sa.Column("created_audit_event_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False),
        sa.Column("usage_event_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True),
        sa.CheckConstraint("schema_version = 'document_change_run_artifact_v1'", name="ck_dcr_artifact_schema"),
        sa.CheckConstraint("requested_by > 0", name="ck_dcr_artifact_actor"),
        sa.CheckConstraint("member_count >= 2 AND member_count <= 8192", name="ck_dcr_artifact_members"),
        sa.CheckConstraint("source_bytes > 0 AND source_bytes <= 8388608 AND length(source_json) > 0 AND length(source_json) <= 8388608", name="ck_dcr_artifact_source"),
        sa.CheckConstraint("length(scope_governance_json) > 0 AND length(scope_governance_json) <= 65535", name="ck_dcr_artifact_review"),
        sa.CheckConstraint(
            "created_audit_event_id > 0 AND scope_created_audit_event_id > 0 AND scope_review_audit_event_id > 0 AND (usage_event_id IS NULL OR usage_event_id > 0)", name="ck_dcr_artifact_audits"
        ),
        sa.UniqueConstraint("usage_event_id", name="uq_dcr_usage_event"),
        sa.ForeignKeyConstraint(
            ["baseline_original_id", "baseline_original_content_hash"], ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"], name="fk_dcr_artifact_baseline"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_original_id", "candidate_original_content_hash"],
            ["hoimsystem_ai_document_original.original_id", "hoimsystem_ai_document_original.content_hash"],
            name="fk_dcr_artifact_candidate",
        ),
        sa.CheckConstraint("baseline_original_id <> candidate_original_id", name="ck_dcr_artifact_two_originals"),
        *(hash_constraint(name, "a") for name in HASH_FIELDS),
    )
    op.create_index("idx_dcr_artifact_scope", "hoimsystem_ai_document_change_run_artifact", ["scope_id", "recorded_at"])
    op.create_table(
        "hoimsystem_ai_document_change_run_result",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_document_change_run_artifact.run_id"), primary_key=True),
        sa.Column("scope_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_document_change_scope.scope_id"), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("lease_token", sa.String(36), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("result_bytes", sa.Integer(), nullable=False),
        sa.Column("result_json", medium_text(), nullable=False),
        sa.Column("source_binding_hash", sa.String(64), nullable=False),
        sa.Column("accepted_at", utc6(), nullable=False),
        sa.Column("accept_audit_event_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False),
        sa.CheckConstraint("schema_version = 'document_change_run_result_v1'", name="ck_dcr_result_schema"),
        sa.CheckConstraint("result_bytes > 0 AND result_bytes <= 8388608 AND length(result_json) > 0 AND length(result_json) <= 8388608", name="ck_dcr_result_bytes"),
        sa.CheckConstraint("accept_audit_event_id > 0", name="ck_dcr_result_audit"),
        sa.UniqueConstraint("accept_audit_event_id", name="uq_dcr_result_accept_audit"),
        *(hash_constraint(name, "r") for name in ("content_hash", "source_binding_hash")),
    )


def downgrade():
    op.drop_table("hoimsystem_ai_document_change_run_result")
    op.drop_index("idx_dcr_artifact_scope", table_name="hoimsystem_ai_document_change_run_artifact")
    op.drop_table("hoimsystem_ai_document_change_run_artifact")
