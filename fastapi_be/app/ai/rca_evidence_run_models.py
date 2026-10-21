"""Durable split RCA artifacts with exact initial claim/dispatch/receipt FKs.

One attempt only: a committed dispatch is never implicitly replayed. Usage is
independent of accepted result content, so paid rejected/cancelled attempts and
interrupted unknown receipts do not acquire a successful result by implication.
"""

from itertools import combinations

from sqlalchemy import CheckConstraint, Column, ForeignKey, ForeignKeyConstraint, Integer, LargeBinary, String, Text, UniqueConstraint, cast, func

from app.ai.rca_evidence_models import utc6, whole_json
from app.database import Base

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
    return f"length({name})=36 AND {positions} AND {hex_sql(f"replace({name},'-','')", 32)}"


def artifact_constraints(columns):
    return (
        CheckConstraint(
            f"HEX(schema_version)=HEX('{ARTIFACT_SCHEMA}') AND requested_by>0 AND event_id>0 AND (patient_id_at_capture IS NULL OR patient_id_at_capture>0)", name="ck_rca_task_scope_schema"
        ),
        CheckConstraint(uuid_sql("run_id") + " AND " + uuid_sql("case_id") + " AND " + uuid_sql("event_grant_id"), name="ck_rca_task_uuids"),
        CheckConstraint("patient_grant_id IS NULL OR (" + uuid_sql("patient_grant_id") + ")", name="ck_rca_task_patient_grant_uuid"),
        CheckConstraint(
            "(patient_id_at_capture IS NULL AND patient_grant_id IS NULL) OR (patient_id_at_capture IS NOT NULL AND patient_grant_id IS NOT NULL AND patient_grant_id<>event_grant_id)",
            name="ck_rca_task_independent_purposes",
        ),
        ForeignKeyConstraint(
            ["event_grant_id", "event_id", "requested_by"],
            ["hoimsystem_ai_rca_purpose_grant.grant_id", "hoimsystem_ai_rca_purpose_grant.event_id", "hoimsystem_ai_rca_purpose_grant.grantee_id"],
            name="fk_rca_task_event_grantee",
        ),
        ForeignKeyConstraint(
            ["patient_grant_id", "event_id", "requested_by"],
            ["hoimsystem_ai_rca_purpose_grant.grant_id", "hoimsystem_ai_rca_purpose_grant.event_id", "hoimsystem_ai_rca_purpose_grant.grantee_id"],
            name="fk_rca_task_patient_grantee",
        ),
        *(CheckConstraint(hex_sql(name), name="ck_rca_task_" + name) for name in ANCHOR_FIELDS),
        CheckConstraint(
            (columns.source_bytes >= 1) & (columns.source_bytes <= 8388608) & (func.length(cast(columns.source_json, LargeBinary)) == columns.source_bytes), name="ck_rca_task_source_bytes"
        ),
        CheckConstraint(
            (columns.binding_bytes >= 1) & (columns.binding_bytes <= 65535) & (func.length(cast(columns.binding_json, LargeBinary)) == columns.binding_bytes), name="ck_rca_task_binding_bytes"
        ),
        CheckConstraint(" AND ".join(f"({name} IS NULL OR {name}>0)" for name in AUDIT_FIELDS), name="ck_rca_task_audit_ids"),
        CheckConstraint(" AND ".join(f"({a} IS NULL OR {b} IS NULL OR {a}<>{b})" for a, b in combinations(AUDIT_FIELDS, 2)), name="ck_rca_task_distinct_audits"),
        CheckConstraint(
            "(claim_event_id IS NULL AND claim_lease IS NULL AND claimed_at IS NULL) OR "
            "(claim_event_id IS NOT NULL AND claim_lease IS NOT NULL AND claimed_at IS NOT NULL AND claimed_at>=recorded_at)",
            name="ck_rca_task_claim_tuple",
        ),
        CheckConstraint("actor_token_invalid_before IS NULL OR actor_token_invalid_before<=recorded_at", name="ck_rca_task_original_epoch"),
        CheckConstraint("claim_lease IS NULL OR (" + uuid_sql("claim_lease") + ")", name="ck_rca_task_claim_lease"),
        CheckConstraint(
            "(dispatch_event_id IS NULL AND dispatched_at IS NULL) OR (dispatch_event_id IS NOT NULL AND dispatched_at IS NOT NULL AND claim_event_id IS NOT NULL AND dispatched_at>=claimed_at)",
            name="ck_rca_task_dispatch_tuple",
        ),
        UniqueConstraint("run_id", "claim_lease", name="uq_rca_task_claim_identity"),
        UniqueConstraint("run_id", "source_hash", "instructions_digest", name="uq_rca_task_source_identity"),
    )


def result_constraints(columns):
    return (
        CheckConstraint(f"HEX(schema_version)=HEX('{RESULT_SCHEMA}')", name="ck_rca_result_schema"),
        CheckConstraint(uuid_sql("run_id") + " AND " + uuid_sql("accepted_lease"), name="ck_rca_result_uuids"),
        *(CheckConstraint(hex_sql(name), name="ck_rca_result_" + name) for name in ("source_hash", "instructions_digest", "result_hash")),
        CheckConstraint(
            (columns.result_bytes >= 1) & (columns.result_bytes <= 8388608) & (func.length(cast(columns.result_json, LargeBinary)) == columns.result_bytes), name="ck_rca_result_exact_bytes"
        ),
        CheckConstraint("accept_audit_event_id>0", name="ck_rca_result_audit_id"),
    )


class AIRcaEvidenceRunArtifact(Base):
    __tablename__ = "hoimsystem_ai_rca_evidence_run_artifact"
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    case_id = Column(String(36), ForeignKey("hoimsystem_ai_rca_evidence_case.case_id"), nullable=False)
    event_id = Column(Integer, ForeignKey("hoimsystem_adverse_event.event_id"), nullable=False)
    patient_id_at_capture = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=True)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    event_grant_id = Column(String(36), ForeignKey("hoimsystem_ai_rca_purpose_grant.grant_id"), nullable=False)
    patient_grant_id = Column(String(36), ForeignKey("hoimsystem_ai_rca_purpose_grant.grant_id"), nullable=True)
    schema_version = Column(String(48), nullable=False)
    recorded_at = Column(utc6(), nullable=False)
    actor_token_invalid_before = Column(utc6(), nullable=True)
    source_json = Column(whole_json(), nullable=False)
    source_bytes = Column(Integer, nullable=False)
    binding_json = Column(Text, nullable=False)
    binding_bytes = Column(Integer, nullable=False)
    input_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    metadata_hash = Column(String(64), nullable=False)
    prompt_hash = Column(String(64), nullable=False)
    context_digest = Column(String(64), nullable=False)
    instructions_digest = Column(String(64), nullable=False)
    source_hash = Column(String(64), nullable=False)
    binding_hash = Column(String(64), nullable=False)
    create_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    claim_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    claim_lease = Column(String(36), nullable=True, unique=True)
    claimed_at = Column(utc6(), nullable=True)
    dispatch_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    dispatched_at = Column(utc6(), nullable=True)
    usage_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)


for _constraint in artifact_constraints(AIRcaEvidenceRunArtifact.__table__.c):
    AIRcaEvidenceRunArtifact.__table__.append_constraint(_constraint)


class AIRcaEvidenceRunResult(Base):
    __tablename__ = "hoimsystem_ai_rca_evidence_run_result"
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_rca_evidence_run_artifact.run_id"), primary_key=True)
    schema_version = Column(String(48), nullable=False)
    source_hash = Column(String(64), nullable=False)
    instructions_digest = Column(String(64), nullable=False)
    accepted_lease = Column(String(36), nullable=False)
    accepted_at = Column(utc6(), nullable=False)
    result_json = Column(whole_json(), nullable=False)
    result_bytes = Column(Integer, nullable=False)
    result_hash = Column(String(64), nullable=False)
    accept_audit_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False, unique=True)
    __table_args__ = (
        ForeignKeyConstraint(
            ["run_id", "accepted_lease"], ["hoimsystem_ai_rca_evidence_run_artifact.run_id", "hoimsystem_ai_rca_evidence_run_artifact.claim_lease"], name="fk_rca_result_actual_claim"
        ),
        ForeignKeyConstraint(
            ["run_id", "source_hash", "instructions_digest"],
            ["hoimsystem_ai_rca_evidence_run_artifact.run_id", "hoimsystem_ai_rca_evidence_run_artifact.source_hash", "hoimsystem_ai_rca_evidence_run_artifact.instructions_digest"],
            name="fk_rca_result_actual_source",
        ),
    )


for _constraint in result_constraints(AIRcaEvidenceRunResult.__table__.c):
    AIRcaEvidenceRunResult.__table__.append_constraint(_constraint)

RCA_EVIDENCE_RUN_MODELS = (AIRcaEvidenceRunArtifact, AIRcaEvidenceRunResult)
