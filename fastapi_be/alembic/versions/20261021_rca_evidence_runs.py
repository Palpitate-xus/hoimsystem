"""Add split RCA tasks with exact initial claim/dispatch/usage audit foreign keys.

No existing table or legacy clock is altered. Each Source and result is a
complete MEDIUMTEXT object with its exact UTF8 byte anchor; Run keeps short refs.
"""

from itertools import combinations
from types import SimpleNamespace

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_rca_evidence_runs"
down_revision = "20261021_rca_evidence"
branch_labels = None
depends_on = None


def utc6():
    return sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def whole_json():
    return sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


ARTIFACT_SCHEMA = "rca_evidence_run_artifact_v1"

RESULT_SCHEMA = "rca_evidence_run_result_v1"

ANCHOR_FIELDS = ("input_hash", "evidence_hash", "metadata_hash", "prompt_hash", "context_digest", "instructions_digest", "source_hash", "binding_hash")

AUDIT_FIELDS = ("create_event_id", "claim_event_id", "dispatch_event_id", "usage_event_id")


def hex_sql(name, size=64):
    remaining = name
    for char in "0123456789abcdef":
        remaining = f"replace({remaining},'{char}','')"
    return f"length({name})={size} AND length({remaining})=0"


def uuid_sql(name):
    positions = " AND ".join(f"substr({name},{number},1)='-'" for number in (9, 14, 19, 24))
    return f"""length({name})=36 AND {positions} AND {hex_sql(f"replace({name},'-','')", 32)}"""


def artifact_constraints(columns):
    return (
        sa.CheckConstraint(
            f"HEX(schema_version)=HEX('{ARTIFACT_SCHEMA}') AND requested_by>0 AND event_id>0 AND (patient_id_at_capture IS NULL OR patient_id_at_capture>0)", name="ck_rca_task_scope_schema"
        ),
        sa.CheckConstraint(uuid_sql("run_id") + " AND " + uuid_sql("case_id"), name="ck_rca_task_uuids"),
        *(sa.CheckConstraint(hex_sql(name), name="ck_rca_task_" + name) for name in ANCHOR_FIELDS),
        sa.CheckConstraint(
            (columns.source_bytes >= 1) & (columns.source_bytes <= 8388608) & (sa.func.length(sa.cast(columns.source_json, sa.LargeBinary)) == columns.source_bytes), name="ck_rca_task_source_bytes"
        ),
        sa.CheckConstraint(
            (columns.binding_bytes >= 1) & (columns.binding_bytes <= 65535) & (sa.func.length(sa.cast(columns.binding_json, sa.LargeBinary)) == columns.binding_bytes), name="ck_rca_task_binding_bytes"
        ),
        sa.CheckConstraint(" AND ".join(f"({name} IS NULL OR {name}>0)" for name in AUDIT_FIELDS), name="ck_rca_task_audit_ids"),
        sa.CheckConstraint(" AND ".join((f"({a} IS NULL OR {b} IS NULL OR {a}<>{b})" for a, b in combinations(AUDIT_FIELDS, 2))), name="ck_rca_task_distinct_audits"),
        sa.CheckConstraint(
            "(claim_event_id IS NULL AND claim_lease IS NULL AND claimed_at IS NULL) OR (claim_event_id IS NOT NULL AND claim_lease IS NOT NULL AND claimed_at IS NOT NULL AND claimed_at>=recorded_at)",
            name="ck_rca_task_claim_tuple",
        ),
        sa.CheckConstraint("claim_lease IS NULL OR (" + uuid_sql("claim_lease") + ")", name="ck_rca_task_claim_lease"),
        sa.CheckConstraint(
            "(dispatch_event_id IS NULL AND dispatched_at IS NULL) OR (dispatch_event_id IS NOT NULL AND dispatched_at IS NOT NULL AND claim_event_id IS NOT NULL AND dispatched_at>=claimed_at)",
            name="ck_rca_task_dispatch_tuple",
        ),
        sa.UniqueConstraint("run_id", "claim_lease", name="uq_rca_task_claim_identity"),
        sa.UniqueConstraint("run_id", "source_hash", "instructions_digest", name="uq_rca_task_source_identity"),
    )


def result_constraints(columns):
    return (
        sa.CheckConstraint(f"HEX(schema_version)=HEX('{RESULT_SCHEMA}')", name="ck_rca_result_schema"),
        sa.CheckConstraint(uuid_sql("run_id") + " AND " + uuid_sql("accepted_lease"), name="ck_rca_result_uuids"),
        *(sa.CheckConstraint(hex_sql(name), name="ck_rca_result_" + name) for name in ("source_hash", "instructions_digest", "result_hash")),
        sa.CheckConstraint(
            (columns.result_bytes >= 1) & (columns.result_bytes <= 8388608) & (sa.func.length(sa.cast(columns.result_json, sa.LargeBinary)) == columns.result_bytes), name="ck_rca_result_exact_bytes"
        ),
        sa.CheckConstraint("accept_audit_event_id>0", name="ck_rca_result_audit_id"),
    )


def upgrade():

    columns = SimpleNamespace(**{name: sa.column(name) for name in ("source_json", "source_bytes", "binding_json", "binding_bytes")})

    op.create_table(
        "hoimsystem_ai_rca_evidence_run_artifact",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_rca_evidence_case.case_id"), nullable=False),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("hoimsystem_adverse_event.event_id"), nullable=False),
        sa.Column("patient_id_at_capture", sa.Integer, sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=True),
        sa.Column("requested_by", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id"), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("recorded_at", utc6(), nullable=False),
        sa.Column("source_json", whole_json(), nullable=False),
        sa.Column("source_bytes", sa.Integer, nullable=False),
        sa.Column("binding_json", sa.Text, nullable=False),
        sa.Column("binding_bytes", sa.Integer, nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("metadata_hash", sa.String(64), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("context_digest", sa.String(64), nullable=False),
        sa.Column("instructions_digest", sa.String(64), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("binding_hash", sa.String(64), nullable=False),
        sa.Column("create_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
        sa.Column("claim_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        sa.Column("claim_lease", sa.String(36), nullable=True, unique=True),
        sa.Column("claimed_at", utc6(), nullable=True),
        sa.Column("dispatch_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        sa.Column("dispatched_at", utc6(), nullable=True),
        sa.Column("usage_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True),
        *artifact_constraints(columns),
    )

    columns = SimpleNamespace(**{name: sa.column(name) for name in ("result_json", "result_bytes")})

    op.create_table(
        "hoimsystem_ai_rca_evidence_run_result",
        sa.Column("run_id", sa.String(36), sa.ForeignKey("hoimsystem_ai_rca_evidence_run_artifact.run_id"), primary_key=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("instructions_digest", sa.String(64), nullable=False),
        sa.Column("accepted_lease", sa.String(36), nullable=False),
        sa.Column("accepted_at", utc6(), nullable=False),
        sa.Column("result_json", whole_json(), nullable=False),
        sa.Column("result_bytes", sa.Integer, nullable=False),
        sa.Column("result_hash", sa.String(64), nullable=False),
        sa.Column("accept_audit_event_id", sa.Integer, sa.ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
        sa.ForeignKeyConstraint(
            ["run_id", "accepted_lease"], ["hoimsystem_ai_rca_evidence_run_artifact.run_id", "hoimsystem_ai_rca_evidence_run_artifact.claim_lease"], name="fk_rca_result_actual_claim"
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "source_hash", "instructions_digest"],
            ["hoimsystem_ai_rca_evidence_run_artifact.run_id", "hoimsystem_ai_rca_evidence_run_artifact.source_hash", "hoimsystem_ai_rca_evidence_run_artifact.instructions_digest"],
            name="fk_rca_result_actual_source",
        ),
        *result_constraints(columns),
    )


def downgrade():
    # InnoDB can use a table's own unique index to support its FK. Drop the
    # dependent table first rather than attempting DROP INDEX on those keys.
    op.drop_table("hoimsystem_ai_rca_evidence_run_result")
    op.drop_table("hoimsystem_ai_rca_evidence_run_artifact")
