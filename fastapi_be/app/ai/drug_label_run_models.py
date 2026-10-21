"""Private seed-bound leaflet task artifacts; no source or business mutation API."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, LargeBinary, String, cast, func

from app.ai.document_evidence_models import medium_text, utc6
from app.database import Base

ARTIFACT_SCHEMA = "drug_label_run_artifact_v1"
MAX_RESULT_BYTES = 8 * 1024 * 1024
HASH_FIELDS = ("input_hash", "evidence_hash", "metadata_hash", "prompt_hash", "context_digest", "source_binding_hash")


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


class AIDrugLabelRunArtifact(Base):
    __tablename__ = "hoimsystem_ai_drug_label_run_artifact"
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    source_binding_id = Column(String(36), ForeignKey("hoimsystem_ai_drug_label_source.source_binding_id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    created_at = Column(utc6(), nullable=False)
    mapping_seed = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    metadata_hash = Column(String(64), nullable=False)
    prompt_hash = Column(String(64), nullable=False)
    context_digest = Column(String(64), nullable=False)
    source_binding_hash = Column(String(64), nullable=False)
    create_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False)
    receipt_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)
    accept_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)
    result_json = Column(medium_text(), nullable=True)
    result_hash = Column(String(64), nullable=True)
    result_bytes = Column(Integer, nullable=True)
    accepted_lease = Column(String(36), nullable=True)
    accepted_at = Column(utc6(), nullable=True)


# Use the same expressions as the independently declared migration table.
for _constraint in artifact_constraints(AIDrugLabelRunArtifact.__table__.c):
    AIDrugLabelRunArtifact.__table__.append_constraint(_constraint)
DRUG_LABEL_RUN_MODELS = (AIDrugLabelRunArtifact,)
