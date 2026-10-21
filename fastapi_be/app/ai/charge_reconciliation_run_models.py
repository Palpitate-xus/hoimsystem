"""Complete private AI task anchors and optional bounded result artifacts."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Integer, LargeBinary, String, cast, func

from app.ai.charge_reconciliation_models import original_json
from app.ai.supply_source_models import utc6
from app.database import Base

MAX_RESULT_BYTES = 8 * 1024 * 1024
SHA_FIELDS = ("input_hash", "evidence_hash", "metadata_hash", "prompt_hash", "context_digest", "source_binding_hash")


def lower_hex_check(name):
    # HEX avoids a case-insensitive MySQL collation accepting uppercase hashes.
    return CheckConstraint("HEX(" + name + ") REGEXP '^(3[0-9]|6[1-6]){64}$'", name="ck_charge_artifact_" + name)


class AIChargeRunArtifact(Base):
    __tablename__ = "hoimsystem_ai_charge_run_artifact"
    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    case_snapshot_id = Column(String(36), ForeignKey("hoimsystem_ai_charge_case_snapshot.case_snapshot_id"), nullable=False)
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
    receipt_event_id = Column(Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=True)
    accepted_lease = Column(String(36), nullable=True)
    __table_args__ = (
        CheckConstraint("HEX(schema_version)=HEX('charge_run_artifact_v1') AND requested_by>0", name="ck_charge_artifact_schema_actor"),
        *(lower_hex_check(name) for name in SHA_FIELDS),
        CheckConstraint("result_hash IS NULL OR HEX(result_hash) REGEXP '^(3[0-9]|6[1-6]){64}$'", name="ck_charge_artifact_result_hash"),
        CheckConstraint(
            "(result_json IS NULL AND result_hash IS NULL AND result_bytes IS NULL) OR (result_json IS NOT NULL AND result_hash IS NOT NULL AND result_bytes IS NOT NULL)",
            name="ck_charge_artifact_result_tuple",
        ),
        CheckConstraint(
            (result_json.is_(None)) | ((result_bytes >= 1) & (result_bytes <= MAX_RESULT_BYTES) & (func.length(cast(result_json, LargeBinary)) == result_bytes)),
            name="ck_charge_artifact_exact_bytes",
        ),
        CheckConstraint("receipt_event_id IS NULL OR receipt_event_id>0", name="ck_charge_artifact_receipt"),
        CheckConstraint(
            "accepted_lease IS NULL OR (accepted_lease REGEXP '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$' AND HEX(accepted_lease)=HEX(LOWER(accepted_lease)))",
            name="ck_charge_artifact_lease",
        ),
    )
