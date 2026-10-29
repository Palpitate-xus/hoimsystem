"""Persist bounded role/user operation policies and their change history."""

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT

from alembic import op

revision = "20261029_fine_permissions"
down_revision = "20261028_audit_covering"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("hoimsystem_access_policy_guard", sa.Column("id", sa.Integer(), primary_key=True))
    op.bulk_insert(sa.table("hoimsystem_access_policy_guard", sa.column("id", sa.Integer())), [{"id": 1}])
    text = sa.Text().with_variant(LONGTEXT(), "mysql")
    op.create_table(
        "hoimsystem_access_policy",
        sa.Column("kind", sa.String(8), primary_key=True),
        sa.Column("subject_key", sa.String(40), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("allowed_json", text, nullable=True),
        sa.Column("data_scope", sa.String(16), nullable=False),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("kind IN ('role', 'user')", name="ck_access_policy_kind"),
        sa.CheckConstraint("version > 0", name="ck_access_policy_version"),
    )
    op.create_table(
        "hoimsystem_access_policy_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(40), nullable=False),
        sa.Column("subject", sa.String(80), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("detail", text, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_access_audit_created", "hoimsystem_access_policy_audit", ["created_at", "id"])


def downgrade():
    op.drop_index("idx_access_audit_created", table_name="hoimsystem_access_policy_audit")
    op.drop_table("hoimsystem_access_policy_audit")
    op.drop_table("hoimsystem_access_policy")
    op.drop_table("hoimsystem_access_policy_guard")
