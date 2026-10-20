"""Controlled surgery resource identities and immutable, independently reviewed facts.

These tables do not reserve resources, alter legacy surgery execution, or establish
professional competence merely because an administrator published a registration.
"""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import declared_attr

from app.database import Base

FACT_BYTES = 8 * 1024 * 1024
REGISTRY_BYTES = 262144
PARENT_BYTES = 262144
REVIEW_BYTES = 4000
SOURCE_KINDS = (
    "case_requirements",
    "duration_observation",
    "case_duration_estimate",
    "operating_room_identity_capability",
    "person_identity_qualification",
    "resource_availability_busy",
    "resource_occupation_policy",
)


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def complete_json():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def governance_constraints(prefix, maximum=REGISTRY_BYTES):
    return (
        CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '' "
            "AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status IN ('published','rejected') AND revision = 2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '' "
            "AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR "
            "(status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '' AND "
            "((revision = 2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '') OR "
            "(revision = 3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '')))",
            name=f"ck_surgery_{prefix}_governance",
        ),
        CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name=f"ck_surgery_{prefix}_clocks",
        ),
        CheckConstraint(
            f"length(payload_json) > 0 AND length(payload_json) <= {maximum} AND length(parent_binding_json) > 0 "
            f"AND length(parent_binding_json) <= {PARENT_BYTES} AND length(review_basis_note) <= {REVIEW_BYTES}",
            name=f"ck_surgery_{prefix}_bounds",
        ),
    )


class ImmutableAnchor:
    """Permanent technical identity; administrative claims live in separate originals."""

    schema_version = Column(String(48), nullable=False)
    payload_json = Column(complete_json(), nullable=False)
    parent_binding_json = Column(complete_json(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    recorded_at = Column(utc6(), nullable=False)

    @declared_attr
    def created_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)


class GovernedOriginal(ImmutableAnchor):
    """Only explicit CAS governance fields can change after creation."""

    status = Column(String(16), nullable=False, default="draft")
    revision = Column(Integer, nullable=False, default=1)
    reviewed_at = Column(utc6(), nullable=True)
    review_basis_note = Column(Text, nullable=False, default="")
    revoked_at = Column(utc6(), nullable=True)
    revoke_reason = Column(String(1000), nullable=False, default="")

    @declared_attr
    def reviewed_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)

    @declared_attr
    def revoked_by(cls):  # noqa: N805
        return Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)


class AISurgeryWriteGate(Base):
    """A local surgery write protocol; unrelated platform writes do not use it."""

    __tablename__ = "hoimsystem_ai_surgery_write_gate"
    __table_args__ = (CheckConstraint("gate_id = 1 AND revision >= 1", name="ck_surgery_write_gate_singleton"),)
    gate_id = Column(Integer, primary_key=True)
    revision = Column(Integer, nullable=False)


class AISurgeryPool(GovernedOriginal, Base):
    __tablename__ = "hoimsystem_ai_surgery_pool"
    __table_args__ = governance_constraints("pool") + (Index("idx_surgery_pool_scope", "department_id", "status"),)
    pool_id = Column(String(36), primary_key=True)
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"), nullable=False)


class AISurgeryResource(ImmutableAnchor, Base):
    """One reviewed physical identity; equipment/CSSD identities have real parents."""

    __tablename__ = "hoimsystem_ai_surgery_resource"
    __table_args__ = (
        UniqueConstraint("resource_id", "resource_kind", name="uq_surgery_resource_kind"),
        UniqueConstraint("equipment_id", name="uq_surgery_physical_equipment"),
        UniqueConstraint("cssd_instrument_id", name="uq_surgery_physical_cssd"),
        CheckConstraint(
            "(resource_kind IN ('room','person') AND equipment_id IS NULL AND cssd_instrument_id IS NULL) OR "
            "(resource_kind = 'equipment' AND ((equipment_id IS NOT NULL AND cssd_instrument_id IS NULL) OR "
            "(equipment_id IS NULL AND cssd_instrument_id IS NOT NULL)))",
            name="ck_surgery_resource_parent",
        ),
        CheckConstraint(
            f"length(payload_json) > 0 AND length(payload_json) <= {REGISTRY_BYTES} AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= {PARENT_BYTES}",
            name="ck_surgery_resource_bounds",
        ),
    )
    resource_id = Column(String(36), primary_key=True)
    resource_kind = Column(String(16), nullable=False)
    equipment_id = Column(Integer, ForeignKey("hoimsystem_equipment.equipment_id"), nullable=True)
    cssd_instrument_id = Column(Integer, ForeignKey("hoimsystem_cssd_instrument.instrument_id"), nullable=True)


class AISurgeryPersonAccount(ImmutableAnchor, Base):
    """A permanent User mapping unifies every real Doctor alias of that account."""

    __tablename__ = "hoimsystem_ai_surgery_person_account"
    __table_args__ = (
        ForeignKeyConstraint(
            ["resource_id", "resource_kind"],
            ["hoimsystem_ai_surgery_resource.resource_id", "hoimsystem_ai_surgery_resource.resource_kind"],
            name="fk_surgery_account_person",
        ),
        UniqueConstraint("user_id", name="uq_surgery_permanent_person_user"),
        CheckConstraint("resource_kind = 'person'", name="ck_surgery_account_person"),
        CheckConstraint(
            f"length(payload_json) > 0 AND length(payload_json) <= {REGISTRY_BYTES} AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= {PARENT_BYTES}",
            name="ck_surgery_account_bounds",
        ),
    )
    binding_id = Column(String(36), primary_key=True)
    resource_id = Column(String(36), nullable=False)
    resource_kind = Column(String(16), nullable=False, default="person")
    user_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)


class AISurgeryRoomAlias(GovernedOriginal, Base):
    """Explicit scoped text or per-legacy-schedule mapping; never a text guess."""

    __tablename__ = "hoimsystem_ai_surgery_room_alias"
    __table_args__ = governance_constraints("room_alias") + (
        ForeignKeyConstraint(
            ["resource_id", "resource_kind"],
            ["hoimsystem_ai_surgery_resource.resource_id", "hoimsystem_ai_surgery_resource.resource_kind"],
            name="fk_surgery_alias_room",
        ),
        UniqueConstraint("active_alias_key", name="uq_surgery_active_room_alias"),
        CheckConstraint("resource_kind = 'room'", name="ck_surgery_alias_room"),
        CheckConstraint(
            "(alias_scope = 'namespace' AND alias_namespace IS NOT NULL AND length(alias_namespace) > 0 AND legacy_schedule_id IS NULL) OR "
            "(alias_scope = 'legacy_schedule' AND alias_namespace IS NULL AND legacy_schedule_id IS NOT NULL)",
            name="ck_surgery_alias_scope",
        ),
        CheckConstraint(
            "(status = 'published' AND active_alias_key IS NOT NULL AND active_alias_key = alias_key) OR (status <> 'published' AND active_alias_key IS NULL)",
            name="ck_surgery_alias_active",
        ),
        Index("idx_surgery_alias_legacy", "legacy_schedule_id", "status"),
    )
    alias_id = Column(String(36), primary_key=True)
    resource_id = Column(String(36), nullable=False)
    resource_kind = Column(String(16), nullable=False, default="room")
    alias_scope = Column(String(24), nullable=False)
    alias_namespace = Column(String(80), nullable=True)
    legacy_schedule_id = Column(String(36), ForeignKey("hoimsystem_surgery_schedule.schedule_id"), nullable=True)
    raw_text_hash = Column(String(64), nullable=False)
    alias_key = Column(String(64), nullable=False)
    active_alias_key = Column(String(64), nullable=True)


class AISurgeryPoolMembership(GovernedOriginal, Base):
    __tablename__ = "hoimsystem_ai_surgery_pool_membership"
    __table_args__ = governance_constraints("membership") + (
        UniqueConstraint("active_pair_key", name="uq_surgery_active_pool_member"),
        CheckConstraint(
            "(status = 'published' AND active_pair_key IS NOT NULL AND active_pair_key = pair_key) OR (status <> 'published' AND active_pair_key IS NULL)",
            name="ck_surgery_member_active",
        ),
        Index("idx_surgery_member_pool", "pool_id", "status", "membership_id"),
        Index("idx_surgery_member_resource", "resource_id", "status"),
    )
    membership_id = Column(String(36), primary_key=True)
    pool_id = Column(String(36), ForeignKey("hoimsystem_ai_surgery_pool.pool_id"), nullable=False)
    resource_id = Column(String(36), ForeignKey("hoimsystem_ai_surgery_resource.resource_id"), nullable=False)
    pair_key = Column(String(64), nullable=False)
    active_pair_key = Column(String(64), nullable=True)


class AISurgerySource(GovernedOriginal, Base):
    """Seven original fact kinds, with a distinct clinical signer where applicable."""

    __tablename__ = "hoimsystem_ai_surgery_source"
    __table_args__ = governance_constraints("source", FACT_BYTES) + (
        UniqueConstraint("source_record_id", "source_kind", name="uq_surgery_source_kind"),
        CheckConstraint("source_kind IN (" + ",".join(repr(kind) for kind in SOURCE_KINDS) + ")", name="ck_surgery_source_kind"),
        CheckConstraint(
            "(source_kind IN ('case_requirements','duration_observation','case_duration_estimate') "
            "AND application_id IS NOT NULL AND patient_id IS NOT NULL AND resource_id IS NULL) OR "
            "(source_kind IN ('operating_room_identity_capability','person_identity_qualification','resource_availability_busy','resource_occupation_policy') "
            "AND application_id IS NULL AND patient_id IS NULL AND admission_id IS NULL AND resource_id IS NOT NULL)",
            name="ck_surgery_source_subject",
        ),
        CheckConstraint(
            "(professional_status = 'unknown' AND signed_by_doctor_id IS NULL AND signed_by_user_id IS NULL AND signed_at IS NULL) OR "
            "(professional_status = 'confirmed' AND source_kind IN ('case_requirements','duration_observation','case_duration_estimate') "
            "AND signed_by_doctor_id IS NOT NULL AND signed_by_user_id IS NOT NULL AND signed_at IS NOT NULL AND signed_at = recorded_at)",
            name="ck_surgery_source_signature",
        ),
        Index("idx_surgery_source_pool", "pool_id", "source_kind", "recorded_at", "source_record_id"),
        Index("idx_surgery_source_case", "application_id", "status"),
        Index("idx_surgery_source_resource", "resource_id", "status"),
    )
    source_record_id = Column(String(36), primary_key=True)
    source_kind = Column(String(48), nullable=False)
    pool_id = Column(String(36), ForeignKey("hoimsystem_ai_surgery_pool.pool_id"), nullable=False)
    resource_id = Column(String(36), ForeignKey("hoimsystem_ai_surgery_resource.resource_id"), nullable=True)
    application_id = Column(String(36), ForeignKey("hoimsystem_surgery_application.application_id"), nullable=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=True)
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"), nullable=True)
    professional_status = Column(String(16), nullable=False, default="unknown")
    signed_by_doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"), nullable=True)
    signed_by_user_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    signed_at = Column(utc6(), nullable=True)


class AISurgeryProtectedWitness(Base):
    """Server-only foreign busy proof. Never part of an ordinary readable snapshot."""

    __tablename__ = "hoimsystem_ai_surgery_protected_witness"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_record_id", "source_kind"],
            ["hoimsystem_ai_surgery_source.source_record_id", "hoimsystem_ai_surgery_source.source_kind"],
            name="fk_surgery_witness_busy_source",
        ),
        CheckConstraint("source_kind = 'resource_availability_busy'", name="ck_surgery_witness_busy"),
        CheckConstraint(f"length(witness_json) > 0 AND length(witness_json) <= {FACT_BYTES}", name="ck_surgery_witness_bounds"),
    )
    source_record_id = Column(String(36), primary_key=True)
    source_kind = Column(String(48), nullable=False, default="resource_availability_busy")
    witness_json = Column(complete_json(), nullable=False)
    content_hash = Column(String(64), nullable=False)
    recorded_at = Column(utc6(), nullable=False)
    created_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False)


REGISTRY_MODELS = (AISurgeryPool, AISurgeryResource, AISurgeryPersonAccount, AISurgeryRoomAlias, AISurgeryPoolMembership)
SURGERY_MODELS = (AISurgeryWriteGate, *REGISTRY_MODELS, AISurgerySource, AISurgeryProtectedWitness)
