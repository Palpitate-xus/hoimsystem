"""add indexes for high frequency HIS queries"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260807_query_indexes"
down_revision: str | Sequence[str] | None = "20260807_sample_tracking"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEXES = {
    "hoimsystem_users": [("idx_users_role", ["user_role"])],
    "hoimsystem_patient": [("idx_patient_identity", ["identity"]), ("idx_patient_phone", ["phone"])],
    "hoimsystem_appointment": [
        ("idx_appointment_patient_status", ["patient_id", "status"]),
        ("idx_appointment_doctor_date", ["doctor_id", "time"]),
    ],
    "hoimsystem_queue": [
        ("idx_queue_doctor_status", ["doctor_id", "status"]),
        ("idx_queue_patient_status", ["patient_id", "status"]),
    ],
    "hoimsystem_lab_order": [
        ("idx_lab_order_patient_status", ["patient_id", "status"]),
        ("idx_lab_order_sample_status", ["sample_status", "status"]),
    ],
    "hoimsystem_medical_record": [("idx_medical_record_patient_time", ["patient_id", "consultation_time"])],
    "hoimsystem_prescription": [("idx_prescription_patient_status", ["patient_id", "status"])],
    "hoimsystem_operation_log": [
        ("idx_operation_log_time", ["create_time"]),
        ("idx_operation_log_user_time", ["user_id", "create_time"]),
        ("idx_operation_log_path", ["path"]),
    ],
}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, indexes in INDEXES.items():
        if not inspector.has_table(table_name):
            continue
        existing = {item["name"] for item in inspector.get_indexes(table_name)}
        for index_name, columns in indexes:
            if index_name not in existing:
                op.create_index(index_name, table_name, columns, unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table_name, indexes in INDEXES.items():
        if not inspector.has_table(table_name):
            continue
        existing = {item["name"] for item in inspector.get_indexes(table_name)}
        for index_name, _ in indexes:
            if index_name in existing:
                op.drop_index(index_name, table_name=table_name)
