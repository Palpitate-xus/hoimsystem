"""add high-growth workflow indexes

Revision ID: 20260904_query_indexes
Revises: 20260903_scheduler_state
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260904_query_indexes"
down_revision: str | Sequence[str] | None = "20260903_scheduler_state"
branch_labels = None
depends_on = None

INDEXES = {
    "hoimsystem_users": [("idx_users_username", ["username"])],
    "hoimsystem_registration": [
        ("idx_registration_patient_status_time", ["patient_id", "status", "time"]),
        ("idx_registration_doctor_status_time", ["doctor_id", "status", "time"]),
        ("idx_registration_department_time_status", ["department_id", "time", "status"]),
    ],
    "hoimsystem_appointment": [("idx_appointment_status_time", ["status", "time"])],
    "hoimsystem_charge": [
        ("idx_charge_status_time", ["status", "charge_time"]),
        ("idx_charge_prescription", ["prescription_id"]),
        ("idx_charge_registration", ["registration_uuid"]),
    ],
    "hoimsystem_prescription": [("idx_prescription_doctor_status_time", ["doctor_id", "status", "create_time"])],
    "hoimsystem_pre_pha": [("idx_pre_pha_prescription", ["prescription_id"])],
    "hoimsystem_medical_record": [
        ("idx_medical_record_doctor_time", ["doctor_id", "consultation_time"]),
        ("idx_medical_record_registration", ["registration_uuid"]),
    ],
    "hoimsystem_lab_order": [
        ("idx_lab_order_doctor_status_time", ["doctor_id", "status", "create_time"]),
        ("idx_lab_order_status_time", ["status", "create_time"]),
    ],
    "hoimsystem_lab_result": [
        ("idx_lab_result_critical_time", ["critical_status", "report_time"]),
        ("idx_lab_result_audit_time", ["audit_status", "report_time"]),
        ("idx_lab_result_order", ["lab_order_id"]),
    ],
    "hoimsystem_operation_log": [("idx_operation_log_result_time", ["result", "create_time"])],
    "hoimsystem_admission": [
        ("idx_admission_patient_status", ["patient_id", "status"]),
        ("idx_admission_department_status", ["department_id", "status"]),
        ("idx_admission_bed_status", ["bed_id", "status"]),
    ],
    "hoimsystem_inpatient_order": [
        ("idx_inpatient_order_admission_status_time", ["admission_id", "status", "create_time"]),
        ("idx_inpatient_order_patient_status", ["patient_id", "status"]),
    ],
    "hoimsystem_order_execution": [
        ("idx_order_execution_status_planned", ["status", "planned_time"]),
        ("idx_order_execution_order_status", ["order_id", "status"]),
    ],
    "hoimsystem_inpatient_charge": [
        ("idx_inpatient_charge_admission_status_date", ["admission_id", "status", "charge_date"]),
        ("idx_inpatient_charge_patient_status_date", ["patient_id", "status", "charge_date"]),
    ],
    "hoimsystem_imaging_order": [
        ("idx_imaging_order_patient_status_time", ["patient_id", "status", "create_time"]),
        ("idx_imaging_order_status_time", ["status", "create_time"]),
    ],
    "hoimsystem_insurance_settlement": [
        ("idx_insurance_settlement_patient_time", ["patient_id", "settlement_time"]),
        ("idx_insurance_settlement_status_time", ["status", "settlement_time"]),
    ],
    "hoimsystem_scheduler_job_state": [("idx_scheduler_job_status_finished", ["status", "last_finished_at"])],
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
