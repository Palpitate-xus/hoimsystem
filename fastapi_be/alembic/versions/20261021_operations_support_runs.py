"""Add operations task split artifacts without altering any existing table."""

from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, LargeBinary, String, Text, UniqueConstraint, and_, cast, column, func
from sqlalchemy.dialects import mysql

from alembic import op
from app.sql_constraints import PortableCheckConstraint as CheckConstraint

revision = "20261021_ops_runs"
down_revision = "20261021_ops_sources"
branch_labels = None
depends_on = None
ARTIFACT_SCHEMA = "operations_support_artifact_v1"
RESULT_SCHEMA = "operations_support_result_v1"
FRAME_BYTES = 262144
WHOLE_BYTES = 8388608
ARTIFACT_HASHES = (
    "case_private_hash",
    "case_public_hash",
    "case_membership_hash",
    "source_binding_hash",
    "source_projection_hash",
    "prompt_snapshot_hash",
    "execution_snapshot_hash",
    "instructions_digest",
    "input_hash",
    "evidence_hash",
    "metadata_hash",
    "run_header_hash",
)
AUDIT_FIELDS = ("created_audit_event_id", "claim_event_id", "dispatch_event_id", "usage_event_id")


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def medium_text():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def byte_bounds(value, maximum, name):
    size = func.length(cast(value, LargeBinary))
    return CheckConstraint(and_(size >= 1, size <= maximum), name=name)


def upgrade():
    op.create_table(
        "hoimsystem_ai_operations_run_artifact",
        Column("run_id", String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        Column("schema_version", String(48), nullable=False),
        Column("case_id", String(36), nullable=False),
        Column("case_requested_by", Integer, nullable=False),
        Column("case_private_hash", String(64), nullable=False),
        Column("case_public_hash", String(64), nullable=False),
        Column("case_membership_hash", String(64), nullable=False),
        Column("requested_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("actor_token_invalid_before", utc6(), nullable=True),
        Column("recorded_at", utc6(), nullable=False),
        Column("objective", String(40), nullable=False),
        Column("source_binding_hash", String(64), nullable=False),
        Column("source_json", medium_text(), nullable=False),
        Column("source_bytes", Integer, nullable=False),
        Column("source_projection_hash", String(64), nullable=False),
        Column("prompt_id", String(36), ForeignKey("hoimsystem_ai_prompt_version.prompt_id"), nullable=True),
        Column("prompt_version", Integer, nullable=False),
        Column("prompt_snapshot_json", medium_text(), nullable=False),
        Column("prompt_snapshot_hash", String(64), nullable=False),
        Column("provider_id", Integer, ForeignKey("hoimsystem_ai_provider.provider_id"), nullable=False),
        Column("provider_revision", Integer, nullable=False),
        Column("config_revision", Integer, nullable=False),
        Column("execution_snapshot_json", medium_text(), nullable=False),
        Column("execution_snapshot_hash", String(64), nullable=False),
        Column("instructions_digest", String(64), nullable=False),
        Column("input_hash", String(64), nullable=False),
        Column("evidence_hash", String(64), nullable=False),
        Column("metadata_hash", String(64), nullable=False),
        Column("run_header_hash", String(64), nullable=False),
        Column("created_audit_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
        Column("claim_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        Column("dispatch_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        Column("usage_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        ForeignKeyConstraint(
            ["case_id", "case_private_hash", "case_public_hash", "case_requested_by"],
            ["hoimsystem_ai_operations_case.case_id", "hoimsystem_ai_operations_case.private_hash", "hoimsystem_ai_operations_case.public_hash", "hoimsystem_ai_operations_case.requested_by"],
            name="fk_ops_run_case",
        ),
        UniqueConstraint("run_id", "source_binding_hash", "instructions_digest", name="uq_ops_run_result_binding"),
        CheckConstraint(f"HEX(schema_version)=HEX('{ARTIFACT_SCHEMA}')", name="ck_ops_run_schema"),
        CheckConstraint("objective IN ('explain_observations','prepare_reviewed_checks','compare_declared_versions')", name="ck_ops_run_objective"),
        CheckConstraint("requested_by>0 AND case_requested_by>0 AND provider_revision>0 AND config_revision>0 AND prompt_version>=0", name="ck_ops_run_positive"),
        CheckConstraint("(prompt_id IS NULL AND prompt_version=0) OR (prompt_id IS NOT NULL AND prompt_version>0)", name="ck_ops_run_prompt_origin"),
        CheckConstraint("source_bytes>0 AND source_bytes<=8388608", name="ck_ops_run_source_bytes"),
        CheckConstraint(column("source_projection_hash") == column("case_public_hash"), name="ck_ops_run_public_identity"),
        byte_bounds(column("source_json"), WHOLE_BYTES, "ck_ops_run_source_body"),
        CheckConstraint(column("source_bytes") == func.length(cast(column("source_json"), LargeBinary)), name="ck_ops_run_exact_source_bytes"),
        byte_bounds(column("prompt_snapshot_json"), FRAME_BYTES, "ck_ops_run_prompt_body"),
        byte_bounds(column("execution_snapshot_json"), FRAME_BYTES, "ck_ops_run_execution_body"),
        *(CheckConstraint("length(" + field + ")=64", name="ck_ops_run_" + field) for field in ARTIFACT_HASHES),
        *(CheckConstraint(field + ">0", name="ck_ops_run_" + field + "_positive") for field in AUDIT_FIELDS),
        *(
            CheckConstraint(left + " IS NULL OR " + right + " IS NULL OR " + left + "<>" + right, name="ck_ops_run_audit_distinct_" + str(i))
            for i, (left, right) in enumerate(((left, right) for at, left in enumerate(AUDIT_FIELDS) for right in AUDIT_FIELDS[at + 1 :]))
        ),
    )
    op.create_table(
        "hoimsystem_ai_operations_run_result",
        Column("run_id", String(36), primary_key=True),
        Column("schema_version", String(48), nullable=False),
        Column("lease_token", String(36), nullable=False),
        Column("accepted_at", utc6(), nullable=False),
        Column("result_json", medium_text(), nullable=False),
        Column("result_bytes", Integer, nullable=False),
        Column("result_hash", String(64), nullable=False),
        Column("source_binding_hash", String(64), nullable=False),
        Column("instructions_digest", String(64), nullable=False),
        Column("accept_audit_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
        ForeignKeyConstraint(
            ["run_id", "source_binding_hash", "instructions_digest"],
            ["hoimsystem_ai_operations_run_artifact.run_id", "hoimsystem_ai_operations_run_artifact.source_binding_hash", "hoimsystem_ai_operations_run_artifact.instructions_digest"],
            name="fk_ops_result_original_binding",
        ),
        CheckConstraint(f"HEX(schema_version)=HEX('{RESULT_SCHEMA}')", name="ck_ops_result_schema"),
        CheckConstraint("result_bytes>0 AND result_bytes<=8388608 AND accept_audit_event_id>0", name="ck_ops_result_bytes_receipt"),
        byte_bounds(column("result_json"), WHOLE_BYTES, "ck_ops_result_body"),
        CheckConstraint(column("result_bytes") == func.length(cast(column("result_json"), LargeBinary)), name="ck_ops_result_exact_bytes"),
        *(CheckConstraint("length(" + field + ")=64", name="ck_ops_result_" + field) for field in ("result_hash", "source_binding_hash", "instructions_digest")),
    )
    op.create_index("idx_ops_run_case_actor", "hoimsystem_ai_operations_run_artifact", ["case_id", "requested_by", "recorded_at"])


def downgrade():
    op.drop_table("hoimsystem_ai_operations_run_result")
    op.drop_table("hoimsystem_ai_operations_run_artifact")
