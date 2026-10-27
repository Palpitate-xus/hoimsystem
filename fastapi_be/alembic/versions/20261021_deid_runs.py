"""Split bounded deidentification task artifacts; existing tables unchanged.

Revision ID: 20261021_deid_runs
Revises: 20261021_deidentification

DDL is frozen here and does not import live application models or helpers.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text, cast, column, func
from sqlalchemy.dialects import mysql

from alembic import op
from app.sql_constraints import PortableCheckConstraint as CheckConstraint

revision = "20261021_deid_runs"
down_revision = "20261021_deidentification"
branch_labels = None
depends_on = None
BODY_BYTES = 8 * 1024 * 1024

SOURCE_HASH_FIELDS = (
    "source_hash",
    "source_projection_hash",
    "source_content_hash",
    "source_governance_hash",
    "input_hash",
    "evidence_hash",
    "metadata_hash",
    "prompt_hash",
    "context_digest",
    "source_binding_hash",
    "instructions_digest",
)


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def body():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def byte_length(name):
    return func.length(cast(column(name), LargeBinary))


def json_check(name, maximum, label):
    return CheckConstraint((byte_length(name) > 0) & (byte_length(name) <= maximum) & (func.json_valid(column(name)) == 1), name=label)


def hash_check(name, label):
    remaining = name
    for character in "0123456789abcdef":
        remaining = "replace(" + remaining + ",'" + character + "','')"
    return CheckConstraint("length(" + name + ")=64 AND length(" + remaining + ")=0", name=label)


def lease_constraint():
    remainder = "replace(accepted_lease,'-','')"
    for character in "0123456789abcdef":
        remainder = "replace(" + remainder + ",'" + character + "','')"
    return CheckConstraint(
        "accepted_lease IS NULL OR (length(accepted_lease)=36 AND substr(accepted_lease,9,1)='-' AND substr(accepted_lease,14,1)='-' AND substr(accepted_lease,19,1)='-' AND substr(accepted_lease,24,1)='-' AND length(replace(accepted_lease,'-',''))=32 AND length("
        + remainder
        + ")=0)",
        name="ck_deid_run_result_lease",
    )


def upgrade():
    op.create_table(
        "hoimsystem_ai_deidentification_run_source",
        Column("run_id", String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        Column("case_id", String(36), ForeignKey("hoimsystem_ai_deidentification_case.case_id"), nullable=False),
        Column("scope_id", String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False),
        Column("patient_id", Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        Column("requested_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("provider_id", Integer, ForeignKey("hoimsystem_ai_provider.provider_id"), nullable=False),
        Column("prompt_version_id", String(36), ForeignKey("hoimsystem_ai_prompt_version.prompt_id"), nullable=True),
        Column("prompt_origin", String(32), nullable=False),
        Column("prompt_version", Integer, nullable=False),
        Column("catalog_version", String(40), nullable=False),
        Column("native_task_version", String(80), nullable=False),
        Column("schema_version", String(48), nullable=False),
        Column("created_at", utc6(), nullable=False),
        Column("source_json", body(), nullable=False),
        Column("source_hash", String(64), nullable=False),
        Column("source_bytes", Integer, nullable=False),
        Column("source_projection_hash", String(64), nullable=False),
        Column("source_content_hash", String(64), nullable=False),
        Column("source_governance_hash", String(64), nullable=False),
        Column("input_hash", String(64), nullable=False),
        Column("evidence_hash", String(64), nullable=False),
        Column("metadata_hash", String(64), nullable=False),
        Column("prompt_hash", String(64), nullable=False),
        Column("context_digest", String(64), nullable=False),
        Column("source_binding_hash", String(64), nullable=False),
        Column("instructions_digest", String(64), nullable=False),
        Column("create_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False),
        CheckConstraint("HEX(schema_version)=HEX('deidentification_run_source_v1')", name="ck_deid_run_source_schema"),
        CheckConstraint("patient_id>0 AND requested_by>0 AND provider_id>0 AND create_event_id>0", name="ck_deid_run_source_ids"),
        CheckConstraint(
            "(HEX(prompt_origin)=HEX('packaged_catalog') AND prompt_version_id IS NULL AND prompt_version=0) OR (HEX(prompt_origin)=HEX('database_version') AND prompt_version_id IS NOT NULL AND prompt_version>0)",
            name="ck_deid_run_source_prompt",
        ),
        CheckConstraint("length(catalog_version)>0 AND length(native_task_version)>0", name="ck_deid_run_source_versions"),
        json_check("source_json", BODY_BYTES, "ck_deid_run_source_json"),
        CheckConstraint((column("source_bytes") > 0) & (column("source_bytes") <= BODY_BYTES) & (column("source_bytes") == byte_length("source_json")), name="ck_deid_run_source_bytes"),
        *(hash_check(field, "ck_deid_run_" + field) for field in SOURCE_HASH_FIELDS),
    )
    op.create_index("idx_deid_run_source_case", "hoimsystem_ai_deidentification_run_source", ["case_id", "created_at", "run_id"])
    op.create_index("idx_deid_run_source_owner", "hoimsystem_ai_deidentification_run_source", ["requested_by", "created_at", "run_id"])
    op.create_table(
        "hoimsystem_ai_deidentification_run_result",
        Column("run_id", String(36), ForeignKey("hoimsystem_ai_deidentification_run_source.run_id"), primary_key=True),
        Column("schema_version", String(48), nullable=False),
        Column("created_at", utc6(), nullable=False),
        Column("usage_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True),
        Column("accept_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True),
        Column("result_json", body(), nullable=True),
        Column("result_hash", String(64), nullable=True),
        Column("result_bytes", Integer, nullable=True),
        Column("accepted_lease", String(36), nullable=True),
        Column("accepted_at", utc6(), nullable=True),
        CheckConstraint("HEX(schema_version)=HEX('deidentification_run_result_v1')", name="ck_deid_run_result_schema"),
        CheckConstraint("(usage_event_id IS NULL OR usage_event_id>0) AND (accept_event_id IS NULL OR accept_event_id>0)", name="ck_deid_run_result_audit_ids"),
        CheckConstraint("accept_event_id IS NULL OR (usage_event_id IS NOT NULL AND accept_event_id<>usage_event_id)", name="ck_deid_run_result_audit_distinct"),
        CheckConstraint(
            "(result_json IS NULL AND result_hash IS NULL AND result_bytes IS NULL AND accepted_lease IS NULL AND accepted_at IS NULL AND accept_event_id IS NULL) OR (result_json IS NOT NULL AND result_hash IS NOT NULL AND result_bytes IS NOT NULL AND accepted_lease IS NOT NULL AND accepted_at IS NOT NULL AND accept_event_id IS NOT NULL AND usage_event_id IS NOT NULL)",
            name="ck_deid_run_result_acceptance",
        ),
        CheckConstraint(
            column("result_json").is_(None) | (byte_length("result_json") > 0) & (byte_length("result_json") <= BODY_BYTES) & (func.json_valid(column("result_json")) == 1),
            name="ck_deid_run_result_json",
        ),
        CheckConstraint(
            column("result_bytes").is_(None) | (column("result_bytes") > 0) & (column("result_bytes") <= BODY_BYTES) & (column("result_bytes") == byte_length("result_json")),
            name="ck_deid_run_result_bytes",
        ),
        hash_check("result_hash", "ck_deid_run_result_hash"),
        lease_constraint(),
        CheckConstraint("accepted_at IS NULL OR accepted_at>=created_at", name="ck_deid_run_result_clock"),
    )


def downgrade():
    op.drop_table("hoimsystem_ai_deidentification_run_result")
    op.drop_table("hoimsystem_ai_deidentification_run_source")
