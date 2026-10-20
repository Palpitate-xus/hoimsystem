"""Add surgery identities and immutable sources; do not alter legacy execution."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_surgery_sources"
down_revision = "20261020_bed_series"
branch_labels = None
depends_on = None


def upgrade():
    clock = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")
    original = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
    op.create_table(
        "hoimsystem_ai_surgery_write_gate",
        sa.Column("gate_id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("gate_id = 1 AND revision >= 1", name="ck_surgery_write_gate_singleton"),
    )
    op.create_table(
        "hoimsystem_ai_surgery_pool",
        sa.Column("pool_id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("department_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", clock, nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("payload_json", original, nullable=False),
        sa.Column("parent_binding_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(payload_json) > 0 AND length(payload_json) <= 262144 AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= 262144 AND length(review_basis_note) <= 4000",
            name="ck_surgery_pool_bounds",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_surgery_pool_clocks",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status IN ('published','rejected') AND revision = 2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '') OR (revision = 3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '')))",
            name="ck_surgery_pool_governance",
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["department_id"], ["hoimsystem_department.department_id"], name=None),
        sa.ForeignKeyConstraint(["revoked_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["created_by"], ["hoimsystem_users.user_id"], name=None),
    )
    op.create_index("idx_surgery_pool_scope", "hoimsystem_ai_surgery_pool", ["department_id", "status"])
    op.create_table(
        "hoimsystem_ai_surgery_resource",
        sa.Column("resource_id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("resource_kind", sa.String(16), nullable=False),
        sa.Column("equipment_id", sa.Integer(), nullable=True),
        sa.Column("cssd_instrument_id", sa.Integer(), nullable=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("payload_json", original, nullable=False),
        sa.Column("parent_binding_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(payload_json) > 0 AND length(payload_json) <= 262144 AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= 262144", name="ck_surgery_resource_bounds"
        ),
        sa.CheckConstraint(
            "(resource_kind IN ('room','person') AND equipment_id IS NULL AND cssd_instrument_id IS NULL) OR (resource_kind = 'equipment' AND ((equipment_id IS NOT NULL AND cssd_instrument_id IS NULL) OR (equipment_id IS NULL AND cssd_instrument_id IS NOT NULL)))",
            name="ck_surgery_resource_parent",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["equipment_id"], ["hoimsystem_equipment.equipment_id"], name=None),
        sa.ForeignKeyConstraint(["cssd_instrument_id"], ["hoimsystem_cssd_instrument.instrument_id"], name=None),
        sa.UniqueConstraint("cssd_instrument_id", name="uq_surgery_physical_cssd"),
        sa.UniqueConstraint("equipment_id", name="uq_surgery_physical_equipment"),
        sa.UniqueConstraint("resource_id", "resource_kind", name="uq_surgery_resource_kind"),
    )
    op.create_table(
        "hoimsystem_ai_surgery_person_account",
        sa.Column("binding_id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("resource_kind", sa.String(16), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("payload_json", original, nullable=False),
        sa.Column("parent_binding_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(payload_json) > 0 AND length(payload_json) <= 262144 AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= 262144", name="ck_surgery_account_bounds"
        ),
        sa.CheckConstraint("resource_kind = 'person'", name="ck_surgery_account_person"),
        sa.ForeignKeyConstraint(["user_id"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["created_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["resource_id", "resource_kind"], ["hoimsystem_ai_surgery_resource.resource_id", "hoimsystem_ai_surgery_resource.resource_kind"], name="fk_surgery_account_person"),
        sa.UniqueConstraint("user_id", name="uq_surgery_permanent_person_user"),
    )
    op.create_table(
        "hoimsystem_ai_surgery_room_alias",
        sa.Column("alias_id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("resource_kind", sa.String(16), nullable=False),
        sa.Column("alias_scope", sa.String(24), nullable=False),
        sa.Column("alias_namespace", sa.String(80), nullable=True),
        sa.Column("legacy_schedule_id", sa.String(36), nullable=True),
        sa.Column("raw_text_hash", sa.String(64), nullable=False),
        sa.Column("alias_key", sa.String(64), nullable=False),
        sa.Column("active_alias_key", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", clock, nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("payload_json", original, nullable=False),
        sa.Column("parent_binding_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(status = 'published' AND active_alias_key IS NOT NULL AND active_alias_key = alias_key) OR (status <> 'published' AND active_alias_key IS NULL)", name="ck_surgery_alias_active"
        ),
        sa.CheckConstraint("resource_kind = 'room'", name="ck_surgery_alias_room"),
        sa.CheckConstraint(
            "(alias_scope = 'namespace' AND alias_namespace IS NOT NULL AND length(alias_namespace) > 0 AND legacy_schedule_id IS NULL) OR (alias_scope = 'legacy_schedule' AND alias_namespace IS NULL AND legacy_schedule_id IS NOT NULL)",
            name="ck_surgery_alias_scope",
        ),
        sa.CheckConstraint(
            "length(payload_json) > 0 AND length(payload_json) <= 262144 AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= 262144 AND length(review_basis_note) <= 4000",
            name="ck_surgery_room_alias_bounds",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_surgery_room_alias_clocks",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status IN ('published','rejected') AND revision = 2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '') OR (revision = 3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '')))",
            name="ck_surgery_room_alias_governance",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["legacy_schedule_id"], ["hoimsystem_surgery_schedule.schedule_id"], name=None),
        sa.ForeignKeyConstraint(["reviewed_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["revoked_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["resource_id", "resource_kind"], ["hoimsystem_ai_surgery_resource.resource_id", "hoimsystem_ai_surgery_resource.resource_kind"], name="fk_surgery_alias_room"),
        sa.UniqueConstraint("active_alias_key", name="uq_surgery_active_room_alias"),
    )
    op.create_index("idx_surgery_alias_legacy", "hoimsystem_ai_surgery_room_alias", ["legacy_schedule_id", "status"])
    op.create_table(
        "hoimsystem_ai_surgery_pool_membership",
        sa.Column("membership_id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("pool_id", sa.String(36), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=False),
        sa.Column("pair_key", sa.String(64), nullable=False),
        sa.Column("active_pair_key", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", clock, nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("payload_json", original, nullable=False),
        sa.Column("parent_binding_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "(status = 'published' AND active_pair_key IS NOT NULL AND active_pair_key = pair_key) OR (status <> 'published' AND active_pair_key IS NULL)", name="ck_surgery_member_active"
        ),
        sa.CheckConstraint(
            "length(payload_json) > 0 AND length(payload_json) <= 262144 AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= 262144 AND length(review_basis_note) <= 4000",
            name="ck_surgery_membership_bounds",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_surgery_membership_clocks",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status IN ('published','rejected') AND revision = 2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '') OR (revision = 3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '')))",
            name="ck_surgery_membership_governance",
        ),
        sa.ForeignKeyConstraint(["revoked_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["resource_id"], ["hoimsystem_ai_surgery_resource.resource_id"], name=None),
        sa.ForeignKeyConstraint(["created_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["pool_id"], ["hoimsystem_ai_surgery_pool.pool_id"], name=None),
        sa.ForeignKeyConstraint(["reviewed_by"], ["hoimsystem_users.user_id"], name=None),
        sa.UniqueConstraint("active_pair_key", name="uq_surgery_active_pool_member"),
    )
    op.create_index("idx_surgery_member_pool", "hoimsystem_ai_surgery_pool_membership", ["pool_id", "status", "membership_id"])
    op.create_index("idx_surgery_member_resource", "hoimsystem_ai_surgery_pool_membership", ["resource_id", "status"])
    op.create_table(
        "hoimsystem_ai_surgery_source",
        sa.Column("source_record_id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("source_kind", sa.String(48), nullable=False),
        sa.Column("pool_id", sa.String(36), nullable=False),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("application_id", sa.String(36), nullable=True),
        sa.Column("patient_id", sa.Integer(), nullable=True),
        sa.Column("admission_id", sa.String(36), nullable=True),
        sa.Column("professional_status", sa.String(16), nullable=False),
        sa.Column("signed_by_doctor_id", sa.Integer(), nullable=True),
        sa.Column("signed_by_user_id", sa.Integer(), nullable=True),
        sa.Column("signed_at", clock, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewed_at", clock, nullable=True),
        sa.Column("review_basis_note", sa.Text(), nullable=False),
        sa.Column("revoked_at", clock, nullable=True),
        sa.Column("revoke_reason", sa.String(1000), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("schema_version", sa.String(48), nullable=False),
        sa.Column("payload_json", original, nullable=False),
        sa.Column("parent_binding_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "length(payload_json) > 0 AND length(payload_json) <= 8388608 AND length(parent_binding_json) > 0 AND length(parent_binding_json) <= 262144 AND length(review_basis_note) <= 4000",
            name="ck_surgery_source_bounds",
        ),
        sa.CheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at >= recorded_at) AND (revoked_at IS NULL OR revoked_at >= recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at >= reviewed_at)",
            name="ck_surgery_source_clocks",
        ),
        sa.CheckConstraint(
            "(status = 'draft' AND revision = 1 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status IN ('published','rejected') AND revision = 2 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '' AND revoked_at IS NULL AND revoked_by IS NULL AND revoke_reason = '') OR (status = 'revoked' AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND revoke_reason <> '' AND ((revision = 2 AND reviewed_at IS NULL AND reviewed_by IS NULL AND review_basis_note = '') OR (revision = 3 AND reviewed_at IS NOT NULL AND reviewed_by IS NOT NULL AND review_basis_note <> '')))",
            name="ck_surgery_source_governance",
        ),
        sa.CheckConstraint(
            "source_kind IN ('case_requirements','duration_observation','case_duration_estimate','operating_room_identity_capability','person_identity_qualification','resource_availability_busy','resource_occupation_policy')",
            name="ck_surgery_source_kind",
        ),
        sa.CheckConstraint(
            "(professional_status = 'unknown' AND signed_by_doctor_id IS NULL AND signed_by_user_id IS NULL AND signed_at IS NULL) OR (professional_status = 'confirmed' AND source_kind IN ('case_requirements','duration_observation','case_duration_estimate') AND signed_by_doctor_id IS NOT NULL AND signed_by_user_id IS NOT NULL AND signed_at IS NOT NULL AND signed_at = recorded_at)",
            name="ck_surgery_source_signature",
        ),
        sa.CheckConstraint(
            "(source_kind IN ('case_requirements','duration_observation','case_duration_estimate') AND application_id IS NOT NULL AND patient_id IS NOT NULL AND resource_id IS NULL) OR (source_kind IN ('operating_room_identity_capability','person_identity_qualification','resource_availability_busy','resource_occupation_policy') AND application_id IS NULL AND patient_id IS NULL AND admission_id IS NULL AND resource_id IS NOT NULL)",
            name="ck_surgery_source_subject",
        ),
        sa.ForeignKeyConstraint(["pool_id"], ["hoimsystem_ai_surgery_pool.pool_id"], name=None),
        sa.ForeignKeyConstraint(["resource_id"], ["hoimsystem_ai_surgery_resource.resource_id"], name=None),
        sa.ForeignKeyConstraint(["revoked_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["signed_by_user_id"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["admission_id"], ["hoimsystem_admission.admission_id"], name=None),
        sa.ForeignKeyConstraint(["application_id"], ["hoimsystem_surgery_application.application_id"], name=None),
        sa.ForeignKeyConstraint(["reviewed_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["patient_id"], ["hoimsystem_patient.patient_id"], name=None),
        sa.ForeignKeyConstraint(["created_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(["signed_by_doctor_id"], ["hoimsystem_doctor.doctor_id"], name=None),
        sa.UniqueConstraint("source_record_id", "source_kind", name="uq_surgery_source_kind"),
    )
    op.create_index("idx_surgery_source_case", "hoimsystem_ai_surgery_source", ["application_id", "status"])
    op.create_index("idx_surgery_source_pool", "hoimsystem_ai_surgery_source", ["pool_id", "source_kind", "recorded_at", "source_record_id"])
    op.create_index("idx_surgery_source_resource", "hoimsystem_ai_surgery_source", ["resource_id", "status"])
    op.create_table(
        "hoimsystem_ai_surgery_protected_witness",
        sa.Column("source_record_id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("source_kind", sa.String(48), nullable=False),
        sa.Column("witness_json", original, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("recorded_at", clock, nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.CheckConstraint("length(witness_json) > 0 AND length(witness_json) <= 8388608", name="ck_surgery_witness_bounds"),
        sa.CheckConstraint("source_kind = 'resource_availability_busy'", name="ck_surgery_witness_busy"),
        sa.ForeignKeyConstraint(["created_by"], ["hoimsystem_users.user_id"], name=None),
        sa.ForeignKeyConstraint(
            ["source_record_id", "source_kind"], ["hoimsystem_ai_surgery_source.source_record_id", "hoimsystem_ai_surgery_source.source_kind"], name="fk_surgery_witness_busy_source"
        ),
    )
    op.execute(sa.text("INSERT INTO hoimsystem_ai_surgery_write_gate(gate_id,revision) VALUES (1,1)"))


def downgrade():
    op.drop_table("hoimsystem_ai_surgery_protected_witness")
    op.drop_table("hoimsystem_ai_surgery_source")
    op.drop_table("hoimsystem_ai_surgery_pool_membership")
    op.drop_table("hoimsystem_ai_surgery_room_alias")
    op.drop_table("hoimsystem_ai_surgery_person_account")
    op.drop_table("hoimsystem_ai_surgery_resource")
    op.drop_table("hoimsystem_ai_surgery_pool")
    op.drop_table("hoimsystem_ai_surgery_write_gate")
