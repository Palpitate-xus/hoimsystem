"""Complete reviewed surgery scenarios and lease-bound native result blobs."""

from sqlalchemy import CheckConstraint, Column, ForeignKey, Index, Integer, String, Text

from app.ai.surgery_models import complete_json, utc6
from app.database import Base

SCENARIO_BYTES = 8 * 1024 * 1024
RESULT_BYTES = 8 * 1024 * 1024


class AISurgeryScenario(Base):
    """A frozen declared problem; publishing it does not book or start a surgery."""

    __tablename__ = "hoimsystem_ai_surgery_scenario"
    __table_args__ = (
        CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' "
            "AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND projection_json IS NULL AND projection_hash IS NULL) OR "
            "(status = 'published' AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' "
            "AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND projection_json IS NOT NULL AND projection_hash IS NOT NULL) OR "
            "(status = 'rejected' AND revision = 2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' "
            "AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason = '' AND projection_json IS NULL AND projection_hash IS NULL) OR "
            "(status = 'revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason <> '' AND "
            "((revision = 2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note = '' AND projection_json IS NULL AND projection_hash IS NULL) OR "
            "(revision = 3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note <> '' AND projection_json IS NOT NULL AND projection_hash IS NOT NULL)))",
            name="ck_surgery_scenario_governance",
        ),
        CheckConstraint(
            "as_of <= created_at AND (reviewed_at IS NULL OR reviewed_at >= created_at) AND (revoked_at IS NULL OR revoked_at >= created_at) "
            "AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_surgery_scenario_clocks",
        ),
        CheckConstraint(
            f"length(snapshot_json) > 0 AND length(snapshot_json) <= {SCENARIO_BYTES} "
            f"AND (projection_json IS NULL OR (length(projection_json) > 0 AND length(projection_json) <= {SCENARIO_BYTES})) AND length(review_basis_note) <= 4000",
            name="ck_surgery_scenario_bounds",
        ),
        Index("idx_surgery_scenario_scope", "department_id", "pool_id", "created_at"),
        Index("idx_surgery_scenario_creator", "created_by", "status"),
    )

    scenario_id = Column(String(36), primary_key=True)
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"), nullable=False)
    pool_id = Column(String(36), ForeignKey("hoimsystem_ai_surgery_pool.pool_id"), nullable=False)
    schema_version = Column(String(48), nullable=False, default="surgery_scenario_private_v1")
    as_of = Column(utc6(), nullable=False)
    created_at = Column(utc6(), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)
    snapshot_json = Column(complete_json(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    collection_digest = Column(String(64), nullable=False)
    projection_json = Column(complete_json(), nullable=True)
    projection_hash = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, default="draft")
    revision = Column(Integer, nullable=False, default=1)
    reviewed_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis_note = Column(Text, nullable=False, default="")
    revoked_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False, default="")


class AISurgeryRunResult(Base):
    __tablename__ = "hoimsystem_ai_surgery_run_result"
    __table_args__ = (
        CheckConstraint(f"result_bytes > 0 AND result_bytes <= {RESULT_BYTES} AND length(result_json) > 0 AND length(result_json) <= {RESULT_BYTES}", name="ck_surgery_result_bounds"),
        Index("idx_surgery_result_scenario", "scenario_id", "created_at"),
    )

    run_id = Column(String(36), ForeignKey("hoimsystem_ai_run.run_id"), primary_key=True)
    scenario_id = Column(String(36), ForeignKey("hoimsystem_ai_surgery_scenario.scenario_id"), nullable=False)
    lease_token = Column(String(36), nullable=False)
    schema_version = Column(String(48), nullable=False)
    source_binding_hash = Column(String(64), nullable=False)
    content_hash = Column(String(64), nullable=False)
    result_json = Column(complete_json(), nullable=False)
    result_bytes = Column(Integer, nullable=False)
    created_at = Column(utc6(), nullable=False)
