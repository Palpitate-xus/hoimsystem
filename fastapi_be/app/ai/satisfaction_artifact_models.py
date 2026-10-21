"""One durable task anchor and optional complete, audited satisfaction result."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, LargeBinary, String, cast, func

from app.ai.satisfaction_models import MAX_BYTES, original_json, utc6
from app.database import Base

ANCHOR_FIELDS = ("input_hash", "evidence_hash", "metadata_hash", "prompt_hash", "context_digest", "source_binding_hash")


def lower_hex_sql(name, size=64):
    remaining = name
    for character in "0123456789abcdef":
        remaining = "replace(" + remaining + ",'" + character + "','')"
    return "length(" + name + ")=" + str(size) + " AND length(" + remaining + ")=0"


def lease_sql():
    positions = " AND ".join("substr(accepted_lease," + str(position) + ",1)='-'" for position in (9, 14, 19, 24))
    return "accepted_lease IS NULL OR (length(accepted_lease)=36 AND " + positions + " AND " + lower_hex_sql("replace(accepted_lease,'-','')", 32) + ")"


class AISatisfactionRunArtifact(Base):
    __tablename__ = "hoimsystem_ai_satisfaction_run_artifact"
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    case_id = Column(String(36), ForeignKey("hoimsystem_ai_satisfaction_case.case_id"), nullable=False)
    requested_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    schema_version = Column(String(48), nullable=False)
    created_at = Column(utc6(), nullable=False)
    input_hash = Column(String(64), nullable=False)
    evidence_hash = Column(String(64), nullable=False)
    metadata_hash = Column(String(64), nullable=False)
    prompt_hash = Column(String(64), nullable=False)
    context_digest = Column(String(64), nullable=False)
    source_binding_hash = Column(String(64), nullable=False)
    result_json = Column(original_json(), nullable=True)
    result_hash = Column(String(64), nullable=True)
    result_bytes = Column(Integer, nullable=True)
    receipt_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True, unique=True)
    accepted_lease = Column(String(36), nullable=True)
    accepted_at = Column(utc6(), nullable=True)
    __table_args__ = (
        CheckConstraint("HEX(schema_version)=HEX('satisfaction_run_artifact_v1') AND requested_by>0", name="ck_satisfaction_artifact_schema"),
        *(CheckConstraint(lower_hex_sql(name), name="ck_satisfaction_artifact_" + name) for name in ANCHOR_FIELDS),
        CheckConstraint("result_hash IS NULL OR (" + lower_hex_sql("result_hash") + ")", name="ck_satisfaction_artifact_result_hash"),
        CheckConstraint(
            "(result_json IS NULL AND result_hash IS NULL AND result_bytes IS NULL AND receipt_event_id IS NULL AND accepted_lease IS NULL AND accepted_at IS NULL) OR (result_json IS NOT NULL AND result_hash IS NOT NULL AND result_bytes IS NOT NULL AND receipt_event_id IS NOT NULL AND accepted_lease IS NOT NULL AND accepted_at IS NOT NULL)",
            name="ck_satisfaction_artifact_complete_result",
        ),
        CheckConstraint(
            result_json.is_(None) | ((result_bytes >= 1) & (result_bytes <= MAX_BYTES) & (func.length(cast(result_json, LargeBinary)) == result_bytes)),
            name="ck_satisfaction_artifact_exact_bytes",
        ),
        CheckConstraint("receipt_event_id IS NULL OR receipt_event_id>0", name="ck_satisfaction_artifact_receipt"),
        CheckConstraint(lease_sql(), name="ck_satisfaction_artifact_lease"),
        CheckConstraint("accepted_at IS NULL OR accepted_at>=created_at", name="ck_satisfaction_artifact_clock"),
    )
