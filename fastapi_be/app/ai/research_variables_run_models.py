"""Split76 task storage; technical original IDs grant no research permission.

The immutable Source Batch retains private Scope data. This artifact stores its
public projection and a separate <=256KiB explicit permission binding, never a
second private Batch copy. Five audit phases exist from the first migration.
"""

from itertools import combinations

from sqlalchemy import Column, DateTime, ForeignKey, ForeignKeyConstraint, Integer, LargeBinary, String, Table, Text, UniqueConstraint, cast, column, func
from sqlalchemy.dialects import mysql

from app.database import Base
from app.sql_constraints import PortableCheckConstraint as CheckConstraint

ARTIFACT_SCHEMA = "research_variable_run_artifact_v1"
RESULT_SCHEMA = "research_variable_run_result_v1"
ANCHOR_FIELDS = ("input_hash", "evidence_hash", "metadata_hash", "prompt_hash", "context_digest", "instructions_digest", "source_hash", "binding_hash")
AUTH_HASH_FIELDS = ("batch_content_hash", "scope_content_hash", "scope_governance_hash", "request_authorization_hash")
AUDIT_FIELDS = ("create_event_id", "claim_event_id", "dispatch_event_id", "usage_event_id")


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def whole_json():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def hex_sql(name, size=64):
    remaining = name
    for char in "0123456789abcdef":
        remaining = f"replace({remaining},'{char}','')"
    return f"length({name})={size} AND length({remaining})=0"


def uuid_sql(name):
    positions = " AND ".join(f"substr({name},{number},1)='-'" for number in (9, 14, 19, 24))
    return f"length({name})=36 AND {positions} AND {hex_sql(f"replace({name},'-','')", 32)}"


def json_check(name, byte_name, tag, maximum):
    actual = func.length(cast(column(name), LargeBinary))
    return CheckConstraint((actual >= 1) & (actual <= maximum) & (actual == column(byte_name)) & (func.json_valid(column(name)) == 1), name="ck_rvt_" + tag)


def artifact_columns():
    return [
        Column("run_id", String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True),
        Column("batch_id", String(36), ForeignKey("hoimsystem_ai_research_variable_batch.batch_id"), nullable=False),
        Column("scope_id", String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False),
        Column("requested_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("task_acl_id", String(36), ForeignKey("hoimsystem_ai_research_project_acl.acl_id"), nullable=False),
        Column("actor_role", String(32), nullable=False),
        Column("actor_token_invalid_before", utc6()),
        Column("schema_version", String(48), nullable=False),
        Column("recorded_at", utc6(), nullable=False),
        Column("source_json", whole_json(), nullable=False),
        Column("source_bytes", Integer, nullable=False),
        Column("binding_json", whole_json(), nullable=False),
        Column("binding_bytes", Integer, nullable=False),
        *(Column(name, String(64), nullable=False) for name in (*ANCHOR_FIELDS, *AUTH_HASH_FIELDS)),
        Column("create_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
        Column("claim_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), unique=True),
        Column("claim_lease", String(36), unique=True),
        Column("claimed_at", utc6()),
        Column("dispatch_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), unique=True),
        Column("dispatched_at", utc6()),
        Column("usage_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), unique=True),
    ]


def artifact_constraints():
    roles = ",".join(f"HEX('{role}')" for role in ("super_admin", "admin", "director", "doctor", "pharmacist"))
    return [
        CheckConstraint(f"HEX(schema_version)=HEX('{ARTIFACT_SCHEMA}') AND requested_by>0 AND HEX(actor_role) IN ({roles})", name="ck_rvt_identity"),
        *(CheckConstraint(uuid_sql(name), name="ck_rvt_uuid_" + name) for name in ("run_id", "batch_id", "scope_id", "task_acl_id")),
        *(CheckConstraint(hex_sql(name), name="ck_rvt_" + name) for name in (*ANCHOR_FIELDS, *AUTH_HASH_FIELDS)),
        json_check("source_json", "source_bytes", "source_bytes", 8388608),
        json_check("binding_json", "binding_bytes", "binding_bytes", 262144),
        CheckConstraint("actor_token_invalid_before IS NULL OR actor_token_invalid_before<=recorded_at", name="ck_rvt_original_epoch"),
        CheckConstraint(" AND ".join(f"({name} IS NULL OR {name}>0)" for name in AUDIT_FIELDS), name="ck_rvt_audit_ids"),
        CheckConstraint(" AND ".join(f"({a} IS NULL OR {b} IS NULL OR {a}<>{b})" for a, b in combinations(AUDIT_FIELDS, 2)), name="ck_rvt_distinct_audits"),
        CheckConstraint(
            "(claim_event_id IS NULL AND claim_lease IS NULL AND claimed_at IS NULL) OR "
            "(claim_event_id IS NOT NULL AND claim_lease IS NOT NULL AND claimed_at IS NOT NULL AND claimed_at>=recorded_at)",
            name="ck_rvt_claim_tuple",
        ),
        CheckConstraint("claim_lease IS NULL OR (" + uuid_sql("claim_lease") + ")", name="ck_rvt_lease_uuid"),
        CheckConstraint(
            "(dispatch_event_id IS NULL AND dispatched_at IS NULL) OR (dispatch_event_id IS NOT NULL AND dispatched_at IS NOT NULL AND claim_event_id IS NOT NULL AND dispatched_at>=claimed_at)",
            name="ck_rvt_dispatch_tuple",
        ),
        UniqueConstraint("run_id", "claim_lease", name="uq_rvt_claim_identity"),
        UniqueConstraint("run_id", "source_hash", "instructions_digest", name="uq_rvt_source_identity"),
    ]


def result_columns():
    return [
        Column("run_id", String(36), ForeignKey("hoimsystem_ai_research_variable_run_artifact.run_id"), primary_key=True),
        Column("schema_version", String(48), nullable=False),
        Column("source_hash", String(64), nullable=False),
        Column("instructions_digest", String(64), nullable=False),
        Column("accepted_lease", String(36), nullable=False),
        Column("accepted_at", utc6(), nullable=False),
        Column("result_json", whole_json(), nullable=False),
        Column("result_bytes", Integer, nullable=False),
        Column("result_hash", String(64), nullable=False),
        Column("accept_audit_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True),
    ]


def result_constraints():
    return [
        CheckConstraint(f"HEX(schema_version)=HEX('{RESULT_SCHEMA}') AND accept_audit_event_id>0", name="ck_rvt_result_identity"),
        *(CheckConstraint(uuid_sql(name), name="ck_rvt_result_uuid_" + name) for name in ("run_id", "accepted_lease")),
        *(CheckConstraint(hex_sql(name), name="ck_rvt_result_" + name) for name in ("source_hash", "instructions_digest", "result_hash")),
        json_check("result_json", "result_bytes", "result_bytes", 8388608),
        ForeignKeyConstraint(
            ["run_id", "accepted_lease"], ["hoimsystem_ai_research_variable_run_artifact.run_id", "hoimsystem_ai_research_variable_run_artifact.claim_lease"], name="fk_rvt_result_actual_claim"
        ),
        ForeignKeyConstraint(
            ["run_id", "source_hash", "instructions_digest"],
            ["hoimsystem_ai_research_variable_run_artifact.run_id", "hoimsystem_ai_research_variable_run_artifact.source_hash", "hoimsystem_ai_research_variable_run_artifact.instructions_digest"],
            name="fk_rvt_result_actual_source",
        ),
    ]


class AIResearchVariableRunArtifact(Base):
    __tablename__ = "hoimsystem_ai_research_variable_run_artifact"
    __table__ = Table(__tablename__, Base.metadata, *artifact_columns(), *artifact_constraints())


class AIResearchVariableRunResult(Base):
    __tablename__ = "hoimsystem_ai_research_variable_run_result"
    __table__ = Table(__tablename__, Base.metadata, *result_columns(), *result_constraints())


RESEARCH_VARIABLE_RUN_MODELS = (AIResearchVariableRunArtifact, AIResearchVariableRunResult)
