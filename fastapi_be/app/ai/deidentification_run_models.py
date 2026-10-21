"""Split task artifacts; clinical bodies still require current research rights.

The Source row is an immutable task anchor by service contract. The Result row
is finalized only by the matching lease. SQL enforces storage/FK/tuple bounds;
it does not certify the source, a Prompt's content, an audit action or authority.
No credentials, clinical edits, manual Review or export permission are created.
"""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, UniqueConstraint, column, func

from app.ai.deidentification_models import BODY_BYTES, body, byte_length, hash_check, json_check, utc6
from app.database import Base

SOURCE_SCHEMA = "deidentification_run_source_v1"
RESULT_SCHEMA = "deidentification_run_result_v1"
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


def lease_constraint():
    remainder = "replace(accepted_lease,'-','')"
    for character in "0123456789abcdef":
        remainder = "replace(" + remainder + ",'" + character + "','')"
    return CheckConstraint(
        "accepted_lease IS NULL OR (length(accepted_lease)=36 AND "
        "substr(accepted_lease,9,1)='-' AND substr(accepted_lease,14,1)='-' AND "
        "substr(accepted_lease,19,1)='-' AND substr(accepted_lease,24,1)='-' AND "
        "length(replace(accepted_lease,'-',''))=32 AND length(" + remainder + ")=0)",
        name="ck_deid_run_result_lease",
    )


class AIDeidentificationRunSource(Base):
    __tablename__ = "hoimsystem_ai_deidentification_run_source"

    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    case_id = Column(String(36), ForeignKey("hoimsystem_ai_deidentification_case.case_id"), nullable=False)
    scope_id = Column(String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    provider_id = Column(Integer, ForeignKey("hoimsystem_ai_provider.provider_id"), nullable=False)
    prompt_version_id = Column(String(36), ForeignKey("hoimsystem_ai_prompt_version.prompt_id"), nullable=True)
    prompt_origin = Column(String(32), nullable=False)
    prompt_version = Column(Integer, nullable=False)
    catalog_version = Column(String(40), nullable=False)
    native_task_version = Column(String(80), nullable=False)
    schema_version = Column(String(48), nullable=False)
    created_at = Column(utc6(), nullable=False)
    source_json = Column(body(), nullable=False)
    source_hash = Column(String(64), nullable=False)
    source_bytes = Column(Integer, nullable=False)
    source_projection_hash = Column(String(64), nullable=False)
    source_content_hash = Column(String(64), nullable=False)
    source_governance_hash = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    metadata_hash = Column(String(64), nullable=False)
    prompt_hash = Column(String(64), nullable=False)
    context_digest = Column(String(64), nullable=False)
    source_binding_hash = Column(String(64), nullable=False)
    instructions_digest = Column(String(64), nullable=False)
    create_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    __table_args__ = (
        CheckConstraint("HEX(schema_version)=HEX('deidentification_run_source_v1')", name="ck_deid_run_source_schema"),
        CheckConstraint("patient_id>0 AND requested_by>0 AND provider_id>0 AND create_event_id>0", name="ck_deid_run_source_ids"),
        CheckConstraint(
            "(HEX(prompt_origin)=HEX('packaged_catalog') AND prompt_version_id IS NULL AND prompt_version=0) OR "
            "(HEX(prompt_origin)=HEX('database_version') AND prompt_version_id IS NOT NULL AND prompt_version>0)",
            name="ck_deid_run_source_prompt",
        ),
        CheckConstraint("length(catalog_version)>0 AND length(native_task_version)>0", name="ck_deid_run_source_versions"),
        json_check("source_json", BODY_BYTES, "ck_deid_run_source_json"),
        CheckConstraint((column("source_bytes") > 0) & (column("source_bytes") <= BODY_BYTES) & (column("source_bytes") == byte_length("source_json")), name="ck_deid_run_source_bytes"),
        *(hash_check(field, "ck_deid_run_" + field) for field in SOURCE_HASH_FIELDS),
        Index("idx_deid_run_source_case", "case_id", "created_at", "run_id"),
        Index("idx_deid_run_source_owner", "requested_by", "created_at", "run_id"),
    )


class AIDeidentificationRunResult(Base):
    __tablename__ = "hoimsystem_ai_deidentification_run_result"

    run_id = Column(String(36), ForeignKey("hoimsystem_ai_deidentification_run_source.run_id"), primary_key=True)
    schema_version = Column(String(48), nullable=False)
    created_at = Column(utc6(), nullable=False)
    claim_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id", name="fk_deid_claim_audit"), nullable=True)
    dispatch_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id", name="fk_deid_dispatch_audit"), nullable=True)
    usage_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)
    accept_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)
    result_json = Column(body(), nullable=True)
    result_hash = Column(String(64), nullable=True)
    result_bytes = Column(Integer, nullable=True)
    accepted_lease = Column(String(36), nullable=True)
    accepted_at = Column(utc6(), nullable=True)
    __table_args__ = (
        CheckConstraint("HEX(schema_version)=HEX('deidentification_run_result_v1')", name="ck_deid_run_result_schema"),
        CheckConstraint("claim_event_id IS NULL OR (claim_event_id>0 AND (usage_event_id IS NULL OR claim_event_id<>usage_event_id) AND (accept_event_id IS NULL OR claim_event_id<>accept_event_id))", name="ck_deid_result_claim"),
        CheckConstraint("dispatch_event_id IS NULL OR (dispatch_event_id>0 AND claim_event_id IS NOT NULL AND dispatch_event_id<>claim_event_id AND (usage_event_id IS NULL OR dispatch_event_id<>usage_event_id) AND (accept_event_id IS NULL OR dispatch_event_id<>accept_event_id))", name="ck_deid_result_dispatch"),
        UniqueConstraint("claim_event_id", name="uq_deid_claim_audit"),
        UniqueConstraint("dispatch_event_id", name="uq_deid_dispatch_audit"),
        CheckConstraint("(usage_event_id IS NULL OR usage_event_id>0) AND (accept_event_id IS NULL OR accept_event_id>0)", name="ck_deid_run_result_audit_ids"),
        CheckConstraint("accept_event_id IS NULL OR (usage_event_id IS NOT NULL AND accept_event_id<>usage_event_id)", name="ck_deid_run_result_audit_distinct"),
        CheckConstraint(
            "(result_json IS NULL AND result_hash IS NULL AND result_bytes IS NULL AND accepted_lease IS NULL AND accepted_at IS NULL AND accept_event_id IS NULL) OR "
            "(result_json IS NOT NULL AND result_hash IS NOT NULL AND result_bytes IS NOT NULL AND accepted_lease IS NOT NULL AND accepted_at IS NOT NULL AND accept_event_id IS NOT NULL AND usage_event_id IS NOT NULL)",
            name="ck_deid_run_result_acceptance",
        ),
        CheckConstraint(
            column("result_json").is_(None) | ((byte_length("result_json") > 0) & (byte_length("result_json") <= BODY_BYTES) & (func.json_valid(column("result_json")) == 1)),
            name="ck_deid_run_result_json",
        ),
        CheckConstraint(
            column("result_bytes").is_(None) | ((column("result_bytes") > 0) & (column("result_bytes") <= BODY_BYTES) & (column("result_bytes") == byte_length("result_json"))),
            name="ck_deid_run_result_bytes",
        ),
        # SQL NULL is permitted only in the complete pending/usage-only tuple.
        hash_check("result_hash", "ck_deid_run_result_hash"),
        lease_constraint(),
        CheckConstraint("accepted_at IS NULL OR accepted_at>=created_at", name="ck_deid_run_result_clock"),
    )


DEIDENTIFICATION_RUN_MODELS = (AIDeidentificationRunSource, AIDeidentificationRunResult)
