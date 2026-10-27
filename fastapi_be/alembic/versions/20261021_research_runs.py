"""Split research Source/Result artifacts, independently additive and frozen.

Revision ID: 20261021_research_runs
Revises: 20261021_research_cohort
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, cast, column, func
from sqlalchemy.dialects import mysql

from alembic import op
from app.sql_constraints import PortableCheckConstraint as CheckConstraint

revision = "20261021_research_runs"
down_revision = "20261021_research_cohort"
branch_labels = None
depends_on = None
SNAPSHOT_BYTES = 8388608
FRAME_BYTES = 262144
BINDING_BYTES = 32768
ARTIFACT_SCHEMA = "research_cohort_run_artifact_v1"
RESULT_SCHEMA = "research_cohort_run_result_v1"
ANCHOR_HASHES = (
    "source_projection_hash",
    "source_binding_hash",
    "prompt_snapshot_hash",
    "execution_snapshot_hash",
    "instructions_digest",
    "context_digest",
    "input_hash",
    "evidence_hash",
    "metadata_hash",
)


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def original_json():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def _bytes(name):
    return func.length(cast(column(name), LargeBinary))


def _json_constraint(name, maximum, label):
    return CheckConstraint((_bytes(name) > 0) & (_bytes(name) <= maximum) & (func.json_valid(column(name)) == 1), name=label)


def _hash_constraint(name, label, *, nullable=False):
    remaining = name
    for character in "0123456789abcdef":
        remaining = "replace(" + remaining + ",'" + character + "','')"
    expression = "length(" + name + ")=64 AND length(" + remaining + ")=0"
    return CheckConstraint((name + " IS NULL OR (" + expression + ")") if nullable else expression, name=label)


def upgrade():
    op.create_table(
        "hoimsystem_ai_research_cohort_run_artifact",
        Column("run_id", String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        Column("case_id", String(36), ForeignKey("hoimsystem_ai_research_cohort_case.case_id"), nullable=False),
        Column("scope_id", String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False),
        Column("requested_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("schema_version", String(48), nullable=False),
        Column("recorded_at", utc6(), nullable=False),
        Column("source_bytes", Integer, nullable=False),
        Column("source_json", original_json(), nullable=False),
        Column("source_projection_hash", String(64), nullable=False),
        Column("source_binding_json", Text, nullable=False),
        Column("source_binding_hash", String(64), nullable=False),
        Column("prompt_id", String(36), ForeignKey("hoimsystem_ai_prompt_version.prompt_id"), nullable=False),
        Column("prompt_version", Integer, nullable=False),
        Column("prompt_snapshot_json", original_json(), nullable=False),
        Column("prompt_snapshot_hash", String(64), nullable=False),
        Column("provider_id", Integer, ForeignKey("hoimsystem_ai_provider.provider_id"), nullable=False),
        Column("provider_revision", Integer, nullable=False),
        Column("config_revision", Integer, nullable=False),
        Column("execution_snapshot_json", original_json(), nullable=False),
        Column("execution_snapshot_hash", String(64), nullable=False),
        Column("instructions_digest", String(64), nullable=False),
        Column("context_digest", String(64), nullable=False),
        Column("input_hash", String(64), nullable=False),
        Column("evidence_hash", String(64), nullable=False),
        Column("metadata_hash", String(64), nullable=False),
        Column("created_audit_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False),
        Column("usage_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True),
        CheckConstraint(f"HEX(schema_version)=HEX('{ARTIFACT_SCHEMA}')", name="ck_rcr_artifact_schema"),
        CheckConstraint(
            "requested_by>0 AND prompt_version>0 AND provider_revision>0 AND config_revision>0 AND created_audit_event_id>0 AND (usage_event_id IS NULL OR (usage_event_id>0 AND usage_event_id<>created_audit_event_id))",
            name="ck_rcr_artifact_positive",
        ),
        CheckConstraint(f"source_bytes>0 AND source_bytes<={SNAPSHOT_BYTES}", name="ck_rcr_artifact_source_bytes"),
        _json_constraint("source_json", SNAPSHOT_BYTES, "ck_rcr_artifact_source_json"),
        CheckConstraint(column("source_bytes") == _bytes("source_json"), name="ck_rcr_artifact_exact_bytes"),
        _json_constraint("source_binding_json", BINDING_BYTES, "ck_rcr_artifact_binding_json"),
        _json_constraint("prompt_snapshot_json", FRAME_BYTES, "ck_rcr_artifact_prompt_json"),
        _json_constraint("execution_snapshot_json", FRAME_BYTES, "ck_rcr_artifact_execution_json"),
        *(_hash_constraint(field, "ck_rcr_artifact_" + field) for field in ANCHOR_HASHES),
        UniqueConstraint("created_audit_event_id", name="uq_rcr_created_audit"),
        UniqueConstraint("usage_event_id", name="uq_rcr_usage_audit"),
    )
    op.create_table(
        "hoimsystem_ai_research_cohort_run_result",
        Column("run_id", String(36), ForeignKey("hoimsystem_ai_research_cohort_run_artifact.run_id"), primary_key=True),
        Column("case_id", String(36), ForeignKey("hoimsystem_ai_research_cohort_case.case_id"), nullable=False),
        Column("scope_id", String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False),
        Column("schema_version", String(48), nullable=False),
        Column("lease_token", String(36), nullable=False),
        Column("accepted_at", utc6(), nullable=False),
        Column("result_json", original_json(), nullable=False),
        Column("result_bytes", Integer, nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("source_binding_hash", String(64), nullable=False),
        Column("instructions_digest", String(64), nullable=False),
        Column("accept_audit_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False),
        CheckConstraint(f"HEX(schema_version)=HEX('{RESULT_SCHEMA}')", name="ck_rcr_result_schema"),
        CheckConstraint(f"result_bytes>0 AND result_bytes<={SNAPSHOT_BYTES} AND accept_audit_event_id>0", name="ck_rcr_result_positive"),
        _json_constraint("result_json", SNAPSHOT_BYTES, "ck_rcr_result_body"),
        CheckConstraint(column("result_bytes") == _bytes("result_json"), name="ck_rcr_result_exact_bytes"),
        *(_hash_constraint(field, "ck_rcr_result_" + field) for field in ("content_hash", "source_binding_hash", "instructions_digest")),
        UniqueConstraint("accept_audit_event_id", name="uq_rcr_accept_audit"),
    )
    op.create_index("idx_rcr_artifact_case_actor", "hoimsystem_ai_research_cohort_run_artifact", ["case_id", "requested_by", "recorded_at"])
    op.create_index("idx_rcr_result_case", "hoimsystem_ai_research_cohort_run_result", ["case_id", "accepted_at"])


def downgrade():
    op.drop_table("hoimsystem_ai_research_cohort_run_result")
    op.drop_table("hoimsystem_ai_research_cohort_run_artifact")
