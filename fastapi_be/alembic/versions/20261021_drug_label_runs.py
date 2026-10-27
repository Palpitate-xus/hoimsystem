"""Retain private seed-bound complete leaflet task artifacts, additively."""

from types import SimpleNamespace

from sqlalchemy import Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text, cast, func
from sqlalchemy.dialects import mysql

from alembic import op
from app.sql_constraints import PortableCheckConstraint as CheckConstraint

revision = "20261021_drug_label_runs"
down_revision = "20261021_drug_label_sources"
branch_labels = None
depends_on = None
ARTIFACT_SCHEMA = "drug_label_run_artifact_v1"
MAX_RESULT_BYTES = 8 * 1024 * 1024
HASH_FIELDS = ("input_hash", "evidence_hash", "metadata_hash", "prompt_hash", "context_digest", "source_binding_hash")


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def medium_text():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def lower_hex_sql(name, size=64):
    remainder = name
    for character in "0123456789abcdef":
        remainder = f"replace({remainder},'{character}','')"
    return f"length({name})={size} AND length({remainder})=0"


def uuid_sql(name):
    hyphens = " AND ".join(f"substr({name},{position},1)='-'" for position in (9, 14, 19, 24))
    return f"length({name})=36 AND {hyphens} AND {lower_hex_sql(f"replace({name},'-','')", 32)}"


def artifact_constraints(columns):
    result = columns.result_json
    return (
        CheckConstraint(f"HEX(schema_version)=HEX('{ARTIFACT_SCHEMA}') AND requested_by>0", name="ck_label_task_schema_actor"),
        CheckConstraint(uuid_sql("run_id"), name="ck_label_task_run_uuid"),
        CheckConstraint(uuid_sql("source_binding_id"), name="ck_label_task_source_uuid"),
        *(CheckConstraint(lower_hex_sql(name), name="ck_label_task_" + name) for name in (*HASH_FIELDS, "mapping_seed")),
        CheckConstraint("create_event_id>0 AND (receipt_event_id IS NULL OR receipt_event_id>0) AND (accept_event_id IS NULL OR accept_event_id>0)", name="ck_label_task_audits"),
        CheckConstraint(
            "(receipt_event_id IS NULL OR receipt_event_id<>create_event_id) AND (accept_event_id IS NULL OR (accept_event_id<>create_event_id AND accept_event_id<>receipt_event_id))",
            name="ck_label_task_distinct_audits",
        ),
        CheckConstraint(
            "(result_json IS NULL AND result_hash IS NULL AND result_bytes IS NULL AND accepted_at IS NULL AND accepted_lease IS NULL AND accept_event_id IS NULL) OR "
            "(result_json IS NOT NULL AND result_hash IS NOT NULL AND result_bytes IS NOT NULL AND accepted_at IS NOT NULL AND accepted_lease IS NOT NULL AND accept_event_id IS NOT NULL AND receipt_event_id IS NOT NULL)",
            name="ck_label_task_accept_tuple",
        ),
        CheckConstraint("result_hash IS NULL OR (" + lower_hex_sql("result_hash") + ")", name="ck_label_task_result_hash"),
        CheckConstraint(
            (result.is_(None)) | ((columns.result_bytes >= 1) & (columns.result_bytes <= MAX_RESULT_BYTES) & (func.length(cast(result, LargeBinary)) == columns.result_bytes)),
            name="ck_label_task_exact_bytes",
        ),
        CheckConstraint("accepted_lease IS NULL OR (" + uuid_sql("accepted_lease") + ")", name="ck_label_task_lease"),
        CheckConstraint("accepted_at IS NULL OR accepted_at>=created_at", name="ck_label_task_clock"),
    )


def upgrade():
    columns = [
        Column("run_id", String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        Column("source_binding_id", String(36), ForeignKey("hoimsystem_ai_drug_label_source.source_binding_id"), nullable=False),
        Column("requested_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("schema_version", String(48), nullable=False),
        Column("created_at", utc6(), nullable=False),
        Column("mapping_seed", String(64), nullable=False),
        Column("input_hash", String(64), nullable=False),
        Column("evidence_hash", String(64), nullable=False),
        Column("metadata_hash", String(64), nullable=False),
        Column("prompt_hash", String(64), nullable=False),
        Column("context_digest", String(64), nullable=False),
        Column("source_binding_hash", String(64), nullable=False),
        Column("create_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False),
        Column("receipt_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True),
        Column("accept_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True),
        Column("result_json", medium_text(), nullable=True),
        Column("result_hash", String(64), nullable=True),
        Column("result_bytes", Integer, nullable=True),
        Column("accepted_lease", String(36), nullable=True),
        Column("accepted_at", utc6(), nullable=True),
    ]
    op.create_table("hoimsystem_ai_drug_label_run_artifact", *columns, *artifact_constraints(SimpleNamespace(**{column.name: column for column in columns})))


def downgrade():
    op.drop_table("hoimsystem_ai_drug_label_run_artifact")
