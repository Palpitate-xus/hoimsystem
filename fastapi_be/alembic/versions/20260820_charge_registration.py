"""charge 表增加挂号费关联列

Charge 模型原仅绑定处方（prescription_id）。为落地挂号费计费与
急诊等非处方费用，新增 registration_uuid / charge_type 两列：
- registration_uuid: 挂号费关联的挂号单（无 FK，与 prescription_id 并列）
- charge_type: 费用类型（prescription=处方费 registration=挂号费）

Revision ID: 20260820_charge_registration
Revises: 20260819_research_audit
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260820_charge_registration"
down_revision: str | None = "20260819_research_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("hoimsystem_charge") as batch_op:
        batch_op.add_column(sa.Column("registration_uuid", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("charge_type", sa.String(20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("hoimsystem_charge") as batch_op:
        batch_op.drop_column("charge_type")
        batch_op.drop_column("registration_uuid")
