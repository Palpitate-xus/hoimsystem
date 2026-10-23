"""76 immutable dictionary/batch storage; these tables grant no research rights."""

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, LargeBinary, String, Text, cast, column, func
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261021_research_variables"
down_revision = "20261021_research_prompt_origin"
branch_labels = None
depends_on = None

MAX_BYTES = 8388608


def utc6():
    return DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def whole_json():
    return Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def byte_length(name):
    return func.length(cast(column(name), LargeBinary))


def hash_check(name, tag):
    stripped = name
    for char in "0123456789abcdef":
        stripped = f"replace({stripped},'{char}','')"
    return CheckConstraint(f"length({name})=64 AND length({stripped})=0", name="ck_rv_" + tag)


def json_check(name, tag, maximum=MAX_BYTES):
    size = byte_length(name)
    return CheckConstraint((size > 0) & (size <= maximum) & (func.json_valid(column(name)) == 1), name="ck_rv_" + tag)


def governance_columns():
    return [
        Column("created_by", Integer, ForeignKey("hoimsystem_users.user_id"), nullable=False),
        Column("created_at", utc6(), nullable=False),
        Column("created_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False),
        Column("last_event_id", Integer, ForeignKey("hoimsystem_ai_audit_event.event_id"), nullable=False),
        Column("status", String(16), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("reviewed_by", Integer, ForeignKey("hoimsystem_users.user_id")),
        Column("reviewed_at", utc6()),
        Column("review_basis_note", Text, nullable=False),
        Column("revoked_by", Integer, ForeignKey("hoimsystem_users.user_id")),
        Column("revoked_at", utc6()),
        Column("revoke_reason", Text, nullable=False),
    ]


def governance_checks(tag):
    return [
        CheckConstraint(
            "(HEX(status)=HEX('draft') AND revision=1 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note='' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason='') OR "
            "(HEX(status) IN (HEX('published'),HEX('rejected')) AND revision=2 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note<>'' AND revoked_by IS NULL AND revoked_at IS NULL AND revoke_reason='') OR "
            "(HEX(status)=HEX('revoked') AND revoked_by IS NOT NULL AND revoked_at IS NOT NULL AND revoke_reason<>'' AND ((revision=2 AND reviewed_by IS NULL AND reviewed_at IS NULL AND review_basis_note='') OR (revision=3 AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND review_basis_note<>'')))",
            name="ck_rv_" + tag + "_governance",
        ),
        CheckConstraint(
            "created_by>0 AND created_event_id>0 AND last_event_id>0 AND (reviewed_at IS NULL OR reviewed_at>=created_at) AND (revoked_at IS NULL OR revoked_at>=created_at) AND (reviewed_at IS NULL OR revoked_at IS NULL OR revoked_at>=reviewed_at)",
            name="ck_rv_" + tag + "_clocks",
        ),
        CheckConstraint((byte_length("review_basis_note") <= 4000) & (byte_length("revoke_reason") <= 4000), name="ck_rv_" + tag + "_basis_bytes"),
    ]


def dictionary_columns():
    return [
        Column("dictionary_id", String(36), primary_key=True),
        Column("scope_id", String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False),
        Column("dictionary_json", whole_json(), nullable=False),
        Column("parent_binding_json", whole_json(), nullable=False),
        Column("content_hash", String(64), nullable=False),
        Column("scope_content_hash", String(64), nullable=False),
        Column("scope_governance_hash", String(64), nullable=False),
        Column("definition_review_status", String(24), nullable=False),
        Column("definition_reviewed_by", Integer, ForeignKey("hoimsystem_users.user_id")),
        Column("definition_reviewed_at", utc6()),
        Column("definition_review_basis", Text, nullable=False),
        *governance_columns(),
    ]


def dictionary_checks():
    return [
        *governance_checks("dict"),
        json_check("dictionary_json", "dict_original"),
        json_check("parent_binding_json", "dict_parent", 262144),
        *(hash_check(name, "dict_" + name) for name in ("content_hash", "scope_content_hash", "scope_governance_hash")),
        CheckConstraint(
            "(HEX(definition_review_status)=HEX('unknown') AND definition_reviewed_by IS NULL AND definition_reviewed_at IS NULL AND definition_review_basis='') OR "
            "(HEX(definition_review_status) IN (HEX('recorded_reviewed'),HEX('not_confirmed')) AND definition_reviewed_by IS NOT NULL AND definition_reviewed_by<>created_by AND definition_reviewed_at IS NOT NULL AND definition_review_basis<>'')",
            name="ck_rv_dict_definition_review",
        ),
        CheckConstraint(
            "(definition_reviewed_at IS NULL OR definition_reviewed_at>=created_at) AND (reviewed_at IS NULL OR definition_reviewed_at IS NULL OR reviewed_at>=definition_reviewed_at)",
            name="ck_rv_dict_definition_clocks",
        ),
        CheckConstraint(byte_length("definition_review_basis") <= 4000, name="ck_rv_dict_definition_bytes"),
    ]


def batch_columns():
    return [
        Column("batch_id", String(36), primary_key=True),
        Column("scope_id", String(36), ForeignKey("hoimsystem_ai_research_study_scope.scope_id"), nullable=False),
        Column("dictionary_id", String(36), ForeignKey("hoimsystem_ai_research_variable_dictionary.dictionary_id"), nullable=False),
        Column("snapshot_json", whole_json(), nullable=False),
        Column("projection_json", whole_json(), nullable=False),
        Column("identity_key", LargeBinary(32), nullable=False),
        *(
            Column(name, String(64), nullable=False)
            for name in (
                "content_hash",
                "projection_hash",
                "collection_digest",
                "member_manifest_hash",
                "scope_content_hash",
                "scope_governance_hash",
                "dictionary_content_hash",
                "dictionary_governance_hash",
            )
        ),
        *governance_columns(),
    ]


def batch_checks():
    return [
        *governance_checks("batch"),
        json_check("snapshot_json", "batch_original"),
        json_check("projection_json", "batch_public"),
        CheckConstraint(byte_length("identity_key") == 32, name="ck_rv_batch_key"),
        *(
            hash_check(name, "batch_" + name)
            for name in (
                "content_hash",
                "projection_hash",
                "collection_digest",
                "member_manifest_hash",
                "scope_content_hash",
                "scope_governance_hash",
                "dictionary_content_hash",
                "dictionary_governance_hash",
            )
        ),
    ]


def upgrade():
    op.create_table("hoimsystem_ai_research_variable_dictionary", *dictionary_columns(), *dictionary_checks())
    op.create_index("ix_rv_dictionary_scope_state", "hoimsystem_ai_research_variable_dictionary", ["scope_id", "status", "created_at"])
    op.create_table("hoimsystem_ai_research_variable_batch", *batch_columns(), *batch_checks())
    op.create_index("ix_rv_batch_scope_dictionary", "hoimsystem_ai_research_variable_batch", ["scope_id", "dictionary_id", "created_at"])


def downgrade():
    op.drop_table("hoimsystem_ai_research_variable_batch")
    op.drop_table("hoimsystem_ai_research_variable_dictionary")
