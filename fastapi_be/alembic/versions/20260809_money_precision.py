"""use fixed-point precision for core financial amounts"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_money_precision"
down_revision: str | Sequence[str] | None = "20260808_registration_counter"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MONEY = sa.Numeric(12, 2)
RATIO = sa.Numeric(5, 4)

FINANCIAL_COLUMNS = {
    "hoimsystem_patient": {"prepaid_balance": (MONEY, True)},
    "hoimsystem_prepaid_transaction": {"amount": (MONEY, False), "balance_after": (MONEY, False)},
    "hoimsystem_charge": {"amount": (MONEY, True)},
    "hoimsystem_charge_item": {"price": (MONEY, False)},
    "hoimsystem_pharmaceutical": {"price": (MONEY, True)},
    "hoimsystem_lab_package": {"price": (MONEY, False)},
    "hoimsystem_invoice": {"amount": (MONEY, True), "tax": (MONEY, True)},
    "hoimsystem_emergency_observation": {"fee_amount": (MONEY, False)},
    "hoimsystem_payment": {"amount": (MONEY, True)},
    "hoimsystem_consumable": {"price": (MONEY, True)},
    "hoimsystem_purchase_order": {"total_amount": (MONEY, True)},
    "hoimsystem_purchase_order_item": {"unit_price": (MONEY, True), "total_price": (MONEY, True)},
    "hoimsystem_exam_package": {"price": (MONEY, True)},
    "hoimsystem_exam_item": {"price": (MONEY, True)},
    "hoimsystem_equipment_maintenance": {"cost": (MONEY, False)},
    "hoimsystem_bed": {"price_per_day": (MONEY, True)},
    "hoimsystem_admission": {"deposit_amount": (MONEY, True)},
    "hoimsystem_inpatient_order_item": {"unit_price": (MONEY, True), "total_price": (MONEY, True)},
    "hoimsystem_inpatient_charge": {"unit_price": (MONEY, True), "total_amount": (MONEY, True)},
    "hoimsystem_medical_record_home": {"total_fee": (MONEY, False)},
    "hoimsystem_insurance_catalog": {"reimbursement_ratio": (RATIO, False)},
    "hoimsystem_insurance_settlement": {
        "total_amount": (MONEY, False),
        "covered_amount": (MONEY, False),
        "self_amount": (MONEY, False),
    },
    "hoimsystem_chronic_disease_registration": {"limit_amount": (MONEY, True)},
    "hoimsystem_drg_grouping": {
        "expected_amount": (MONEY, False),
        "actual_amount": (MONEY, False),
        "profit": (MONEY, False),
    },
}


def _alter_columns(to_type: bool) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table_name, columns in FINANCIAL_COLUMNS.items():
        if not inspector.has_table(table_name):
            continue
        existing_columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        with op.batch_alter_table(table_name) as batch_op:
            for column_name, (target_type, nullable) in columns.items():
                if column_name not in existing_columns:
                    continue
                current_type = existing_columns[column_name]["type"]
                batch_op.alter_column(
                    column_name,
                    existing_type=current_type,
                    type_=target_type if to_type else sa.Float(),
                    existing_nullable=nullable,
                )


def upgrade() -> None:
    _alter_columns(True)


def downgrade() -> None:
    _alter_columns(False)
