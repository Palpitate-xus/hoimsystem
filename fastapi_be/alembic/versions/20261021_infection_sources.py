"""Add independent purpose grants and finite infection-report source governance."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op
from app.sql_constraints import PortableCheckConstraint

revision = "20261021_infection_sources"
down_revision = "20261021_native_expanded_merge"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hoimsystem_ai_infection_write_gate",
        sa.Column("gate_id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        PortableCheckConstraint("gate_id=1 AND revision=1", name="ck_inf_gate_singleton"),
        sa.PrimaryKeyConstraint("gate_id"),
    )
    op.create_table(
        "hoimsystem_ai_infection_purpose_grant",
        sa.Column("grant_id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("valid_from", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("valid_to", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("payload_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("review_basis", sa.Text(), nullable=False),
        sa.Column("privacy_review", sa.String(length=20), nullable=False),
        sa.Column("faithfulness_review", sa.String(length=20), nullable=False),
        sa.Column("revoked_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("revoke_basis", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("create_event_id", sa.Integer(), nullable=False),
        sa.Column("review_event_id", sa.Integer(), nullable=True),
        sa.Column("revoke_event_id", sa.Integer(), nullable=True),
        PortableCheckConstraint(
            "(status='draft' AND revision=1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_event_id IS NULL AND review_basis='' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_event_id IS NULL AND revoke_basis='') OR (status IN ('published','rejected') AND revision=2 AND reviewed_by IS NOT NULL AND reviewed_by<>created_by AND reviewed_at IS NOT NULL AND review_event_id IS NOT NULL AND review_basis<>'' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_event_id IS NULL AND revoke_basis='') OR (status='revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_event_id IS NOT NULL AND revoke_basis<>'' AND ((revision=2 AND reviewed_by IS NULL AND review_event_id IS NULL) OR (revision=3 AND reviewed_by IS NOT NULL AND review_event_id IS NOT NULL)))",
            name="ck_inf_grant_governance",
        ),
        PortableCheckConstraint(
            "privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND ((reviewed_by IS NULL AND privacy_review='unknown' AND faithfulness_review='unknown') OR (reviewed_by IS NOT NULL AND privacy_review<>'unknown' AND faithfulness_review<>'unknown')) AND (status<>'published' OR (privacy_review='confirmed' AND faithfulness_review='confirmed')) AND (status<>'rejected' OR privacy_review='not_confirmed' OR faithfulness_review='not_confirmed')",
            name="ck_inf_grant_review_flags",
        ),
        PortableCheckConstraint("purpose IN ('infection_surveillance_processing','external_model_transfer') AND valid_to>valid_from", name="ck_inf_grant_purpose"),
        PortableCheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at>=recorded_at) AND (revoked_at IS NULL OR revoked_at>=recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_inf_grant_clock",
        ),
        PortableCheckConstraint(sa.func.length(sa.cast(sa.column("payload_json"), sa.LargeBinary())) <= 8388608, name="ck_inf_grant_utf8"),
        PortableCheckConstraint(
            "length(payload_json)>0 AND length(payload_json)<=8388608 AND length(content_hash)=64 AND length(review_basis)<=4000 AND length(revoke_basis)<=4000", name="ck_inf_grant_bounds"
        ),
        sa.ForeignKeyConstraint(
            ["create_event_id"],
            ["hoimsystem_ai_audit_event.event_id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["hoimsystem_users.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["hoimsystem_patient.patient_id"],
        ),
        sa.ForeignKeyConstraint(
            ["review_event_id"],
            ["hoimsystem_ai_audit_event.event_id"],
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["hoimsystem_users.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["revoke_event_id"],
            ["hoimsystem_ai_audit_event.event_id"],
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["hoimsystem_users.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["hoimsystem_users.user_id"],
        ),
        sa.PrimaryKeyConstraint("grant_id"),
    )
    op.create_index("idx_inf_grant_subject", "hoimsystem_ai_infection_purpose_grant", ["patient_id", "user_id", "purpose", "grant_id"], unique=False)
    op.create_table(
        "hoimsystem_ai_infection_definition",
        sa.Column("definition_id", sa.String(length=36), nullable=False),
        sa.Column("payload_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("review_basis", sa.Text(), nullable=False),
        sa.Column("privacy_review", sa.String(length=20), nullable=False),
        sa.Column("faithfulness_review", sa.String(length=20), nullable=False),
        sa.Column("revoked_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("revoke_basis", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("create_event_id", sa.Integer(), nullable=False),
        sa.Column("review_event_id", sa.Integer(), nullable=True),
        sa.Column("revoke_event_id", sa.Integer(), nullable=True),
        PortableCheckConstraint(
            "(status='draft' AND revision=1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_event_id IS NULL AND review_basis='' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_event_id IS NULL AND revoke_basis='') OR (status IN ('published','rejected') AND revision=2 AND reviewed_by IS NOT NULL AND reviewed_by<>created_by AND reviewed_at IS NOT NULL AND review_event_id IS NOT NULL AND review_basis<>'' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_event_id IS NULL AND revoke_basis='') OR (status='revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_event_id IS NOT NULL AND revoke_basis<>'' AND ((revision=2 AND reviewed_by IS NULL AND review_event_id IS NULL) OR (revision=3 AND reviewed_by IS NOT NULL AND review_event_id IS NOT NULL)))",
            name="ck_inf_definition_governance",
        ),
        PortableCheckConstraint(
            "privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND ((reviewed_by IS NULL AND privacy_review='unknown' AND faithfulness_review='unknown') OR (reviewed_by IS NOT NULL AND privacy_review<>'unknown' AND faithfulness_review<>'unknown')) AND (status<>'published' OR (privacy_review='confirmed' AND faithfulness_review='confirmed')) AND (status<>'rejected' OR privacy_review='not_confirmed' OR faithfulness_review='not_confirmed')",
            name="ck_inf_definition_review_flags",
        ),
        PortableCheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at>=recorded_at) AND (revoked_at IS NULL OR revoked_at>=recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_inf_definition_clock",
        ),
        PortableCheckConstraint(sa.func.length(sa.cast(sa.column("payload_json"), sa.LargeBinary())) <= 8388608, name="ck_inf_definition_utf8"),
        PortableCheckConstraint(
            "length(payload_json)>0 AND length(payload_json)<=8388608 AND length(content_hash)=64 AND length(review_basis)<=4000 AND length(revoke_basis)<=4000", name="ck_inf_definition_bounds"
        ),
        sa.ForeignKeyConstraint(
            ["create_event_id"],
            ["hoimsystem_ai_audit_event.event_id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["hoimsystem_users.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["review_event_id"],
            ["hoimsystem_ai_audit_event.event_id"],
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["hoimsystem_users.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["revoke_event_id"],
            ["hoimsystem_ai_audit_event.event_id"],
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["hoimsystem_users.user_id"],
        ),
        sa.PrimaryKeyConstraint("definition_id"),
    )
    op.create_table(
        "hoimsystem_ai_infection_case_review",
        sa.Column("review_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.String(length=36), nullable=False),
        sa.Column("patient_id", sa.Integer(), nullable=False),
        sa.Column("definition_id", sa.String(length=36), nullable=False),
        sa.Column("original_content_hash", sa.String(length=64), nullable=False),
        sa.Column("definition_content_hash", sa.String(length=64), nullable=False),
        sa.Column("definition_governance_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("reviewed_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("review_basis", sa.Text(), nullable=False),
        sa.Column("privacy_review", sa.String(length=20), nullable=False),
        sa.Column("faithfulness_review", sa.String(length=20), nullable=False),
        sa.Column("revoked_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=True),
        sa.Column("revoke_basis", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("create_event_id", sa.Integer(), nullable=False),
        sa.Column("review_event_id", sa.Integer(), nullable=True),
        sa.Column("revoke_event_id", sa.Integer(), nullable=True),
        PortableCheckConstraint(
            "(status='draft' AND revision=1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_event_id IS NULL AND review_basis='' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_event_id IS NULL AND revoke_basis='') OR (status IN ('published','rejected') AND revision=2 AND reviewed_by IS NOT NULL AND reviewed_by<>created_by AND reviewed_at IS NOT NULL AND review_event_id IS NOT NULL AND review_basis<>'' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_event_id IS NULL AND revoke_basis='') OR (status='revoked' AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_event_id IS NOT NULL AND revoke_basis<>'' AND ((revision=2 AND reviewed_by IS NULL AND review_event_id IS NULL) OR (revision=3 AND reviewed_by IS NOT NULL AND review_event_id IS NOT NULL)))",
            name="ck_inf_review_governance",
        ),
        PortableCheckConstraint(
            "privacy_review IN ('unknown','confirmed','not_confirmed') AND faithfulness_review IN ('unknown','confirmed','not_confirmed') AND ((reviewed_by IS NULL AND privacy_review='unknown' AND faithfulness_review='unknown') OR (reviewed_by IS NOT NULL AND privacy_review<>'unknown' AND faithfulness_review<>'unknown')) AND (status<>'published' OR (privacy_review='confirmed' AND faithfulness_review='confirmed')) AND (status<>'rejected' OR privacy_review='not_confirmed' OR faithfulness_review='not_confirmed')",
            name="ck_inf_review_review_flags",
        ),
        PortableCheckConstraint(
            "(reviewed_at IS NULL OR reviewed_at>=recorded_at) AND (revoked_at IS NULL OR revoked_at>=recorded_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_inf_review_clock",
        ),
        PortableCheckConstraint(sa.func.length(sa.cast(sa.column("payload_json"), sa.LargeBinary())) <= 8388608, name="ck_inf_review_utf8"),
        PortableCheckConstraint(
            "length(payload_json)>0 AND length(payload_json)<=8388608 AND length(content_hash)=64 AND length(review_basis)<=4000 AND length(revoke_basis)<=4000", name="ck_inf_review_bounds"
        ),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["hoimsystem_infection_case.case_id"],
        ),
        sa.ForeignKeyConstraint(
            ["create_event_id"],
            ["hoimsystem_ai_audit_event.event_id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["hoimsystem_users.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["hoimsystem_ai_infection_definition.definition_id"],
        ),
        sa.ForeignKeyConstraint(
            ["patient_id"],
            ["hoimsystem_patient.patient_id"],
        ),
        sa.ForeignKeyConstraint(
            ["review_event_id"],
            ["hoimsystem_ai_audit_event.event_id"],
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["hoimsystem_users.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["revoke_event_id"],
            ["hoimsystem_ai_audit_event.event_id"],
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by"],
            ["hoimsystem_users.user_id"],
        ),
        sa.PrimaryKeyConstraint("review_id"),
        sa.UniqueConstraint("case_id", "original_content_hash", "definition_content_hash", "definition_governance_hash", name="uq_inf_review_exact_root"),
    )
    op.create_index("idx_inf_review_definition", "hoimsystem_ai_infection_case_review", ["definition_id", "case_id"], unique=False)
    op.create_table(
        "hoimsystem_ai_infection_snapshot",
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("definition_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("create_event_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=40), nullable=False),
        sa.Column("captured_at", sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("scope_json", sa.Text(), nullable=False),
        sa.Column("private_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("private_hash", sa.String(length=64), nullable=False),
        sa.Column("public_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("public_hash", sa.String(length=64), nullable=False),
        sa.Column("witness_json", sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql"), nullable=False),
        sa.Column("witness_hash", sa.String(length=64), nullable=False),
        sa.Column("mapping_key", sa.LargeBinary(length=32), nullable=False),
        PortableCheckConstraint(
            "schema_version='infection_cluster_snapshot_v1' AND length(private_json)>0 AND length(private_json)<=8388608 AND length(public_json)>0 AND length(public_json)<=8388608 AND length(witness_json)>0 AND length(witness_json)<=8388608 AND length(mapping_key)=32",
            name="ck_inf_snapshot_storage",
        ),
        PortableCheckConstraint(sa.func.length(sa.cast(sa.column("private_json"), sa.LargeBinary())) <= 8388608, name="ck_inf_snapshot_private_json_utf8"),
        PortableCheckConstraint(sa.func.length(sa.cast(sa.column("public_json"), sa.LargeBinary())) <= 8388608, name="ck_inf_snapshot_public_json_utf8"),
        PortableCheckConstraint(sa.func.length(sa.cast(sa.column("witness_json"), sa.LargeBinary())) <= 8388608, name="ck_inf_snapshot_witness_json_utf8"),
        PortableCheckConstraint("length(private_hash)=64 AND length(public_hash)=64 AND length(witness_hash)=64", name="ck_inf_snapshot_hashes"),
        sa.ForeignKeyConstraint(
            ["create_event_id"],
            ["hoimsystem_ai_audit_event.event_id"],
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["hoimsystem_users.user_id"],
        ),
        sa.ForeignKeyConstraint(
            ["definition_id"],
            ["hoimsystem_ai_infection_definition.definition_id"],
        ),
        sa.PrimaryKeyConstraint("snapshot_id"),
    )
    op.create_index("idx_inf_snapshot_created", "hoimsystem_ai_infection_snapshot", ["created_by", "captured_at", "snapshot_id"], unique=False)


def downgrade():
    op.drop_table("hoimsystem_ai_infection_snapshot")
    op.drop_table("hoimsystem_ai_infection_case_review")
    op.drop_table("hoimsystem_ai_infection_definition")
    op.drop_table("hoimsystem_ai_infection_purpose_grant")
    op.drop_table("hoimsystem_ai_infection_write_gate")
