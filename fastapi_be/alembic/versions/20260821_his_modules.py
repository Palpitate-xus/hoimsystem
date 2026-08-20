"""HIS 功能补齐第二期：11 张新表

审方规则 / 医保目录对照 / MDRO 隔离 / 不良事件 RCA / 传染病报告卡 /
HQMS 指标 / CSSD 器械包 / PIVAS 批次 / ICU-PACU 评分 / 临床路径入组 /
手卫生观察。数据全部由用户手工录入或 Excel 导入，无预置数据。

Revision ID: 20260821_his_modules
Revises: 20260820_charge_registration
Create Date: 2026-08-21
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260821_his_modules"
down_revision: str | None = "20260820_charge_registration"
branch_labels = None
depends_on = None

NEW_TABLES = [
    ("hoimsystem_rx_review_rule", [
        sa.Column("rule_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("rule_type", sa.String(30), nullable=False),
        sa.Column("drug_a", sa.String(100)),
        sa.Column("drug_b", sa.String(100)),
        sa.Column("min_dose", sa.Numeric(12, 2)),
        sa.Column("max_dose", sa.Numeric(12, 2)),
        sa.Column("max_daily_dose", sa.Numeric(12, 2)),
        sa.Column("severity", sa.Integer, nullable=False, server_default="1"),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("status", sa.Integer, nullable=False, server_default="1"),
        sa.Column("create_time", sa.DateTime, nullable=False),
    ]),
    ("hoimsystem_insurance_catalog_mapping", [
        sa.Column("mapping_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("local_item_type", sa.String(20), nullable=False),
        sa.Column("local_item_id", sa.Integer),
        sa.Column("local_item_name", sa.String(200), nullable=False),
        sa.Column("insurance_code", sa.String(50), nullable=False),
        sa.Column("insurance_name", sa.String(200), nullable=False),
        sa.Column("insurance_category", sa.String(30)),
        sa.Column("self_pay_ratio", sa.Numeric(5, 2), server_default="0"),
        sa.Column("unit_price_limit", sa.Numeric(12, 2)),
        sa.Column("status", sa.Integer, nullable=False, server_default="1"),
        sa.Column("create_time", sa.DateTime, nullable=False),
    ]),
    ("hoimsystem_mdro_isolation", [
        sa.Column("mdro_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("pathogen", sa.String(100), nullable=False),
        sa.Column("specimen", sa.String(50)),
        sa.Column("isolation_type", sa.String(30), nullable=False, server_default="接触隔离"),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date),
        sa.Column("bed_label", sa.Integer, server_default="1"),
        sa.Column("status", sa.Integer, nullable=False, server_default="1"),
        sa.Column("remark", sa.String(300)),
        sa.Column("reporter_id", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("create_time", sa.DateTime, nullable=False),
    ]),
    ("hoimsystem_adverse_event_rca", [
        sa.Column("rca_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.Integer, sa.ForeignKey("hoimsystem_adverse_event.event_id"), nullable=False),
        sa.Column("event_summary", sa.String(500), nullable=False),
        sa.Column("timeline", sa.Text),
        sa.Column("root_cause", sa.Text, nullable=False),
        sa.Column("corrective_actions", sa.Text, nullable=False),
        sa.Column("pdca_cycle", sa.String(10), server_default="P"),
        sa.Column("responsible_dept", sa.String(100)),
        sa.Column("due_date", sa.Date),
        sa.Column("completed_date", sa.Date),
        sa.Column("effect_evaluation", sa.Text),
        sa.Column("analyst_id", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("create_time", sa.DateTime, nullable=False),
        sa.Column("update_time", sa.DateTime),
    ]),
    ("hoimsystem_notifiable_disease_report", [
        sa.Column("report_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("disease_name", sa.String(100), nullable=False),
        sa.Column("disease_class", sa.String(10)),
        sa.Column("onset_date", sa.Date),
        sa.Column("diagnosis_date", sa.Date, nullable=False),
        sa.Column("death_date", sa.Date),
        sa.Column("case_classification", sa.String(30)),
        sa.Column("report_status", sa.Integer, nullable=False, server_default="0"),
        sa.Column("report_card_no", sa.String(30)),
        sa.Column("reporter_id", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("report_time", sa.DateTime, nullable=False),
        sa.Column("audit_time", sa.DateTime),
        sa.Column("auditor_id", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("remark", sa.String(300)),
        sa.Column("create_time", sa.DateTime, nullable=False),
    ]),
    ("hoimsystem_hqms_indicator", [
        sa.Column("indicator_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("period", sa.String(10), nullable=False),
        sa.Column("indicator_code", sa.String(50), nullable=False),
        sa.Column("indicator_name", sa.String(200), nullable=False),
        sa.Column("indicator_value", sa.Numeric(14, 4)),
        sa.Column("numerator", sa.Numeric(14, 4)),
        sa.Column("denominator", sa.Numeric(14, 4)),
        sa.Column("unit", sa.String(20)),
        sa.Column("department", sa.String(100)),
        sa.Column("report_status", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reporter_id", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("remark", sa.String(300)),
        sa.Column("create_time", sa.DateTime, nullable=False),
    ]),
    ("hoimsystem_cssd_instrument", [
        sa.Column("instrument_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("package_name", sa.String(100), nullable=False),
        sa.Column("package_code", sa.String(50), unique=True),
        sa.Column("contents", sa.String(500)),
        sa.Column("sterilize_method", sa.String(30), server_default="压力蒸汽"),
        sa.Column("status", sa.Integer, nullable=False, server_default="0"),
        sa.Column("expire_date", sa.Date),
        sa.Column("sterilize_date", sa.Date),
        sa.Column("bd_test", sa.Integer),
        sa.Column("biological_monitor", sa.Integer),
        sa.Column("current_location", sa.String(100)),
        sa.Column("create_time", sa.DateTime, nullable=False),
        sa.Column("update_time", sa.DateTime),
    ]),
    ("hoimsystem_pivas_batch", [
        sa.Column("batch_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("batch_no", sa.String(30), nullable=False),
        sa.Column("plan_date", sa.Date, nullable=False),
        sa.Column("ward_id", sa.Integer, sa.ForeignKey("hoimsystem_ward.ward_id")),
        sa.Column("status", sa.Integer, nullable=False, server_default="0"),
        sa.Column("label_count", sa.Integer, server_default="0"),
        sa.Column("cytotoxic", sa.Integer, server_default="0"),
        sa.Column("tpn", sa.Integer, server_default="0"),
        sa.Column("dispenser_id", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("checker_id", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("courier_id", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("receive_time", sa.DateTime),
        sa.Column("remark", sa.String(300)),
        sa.Column("create_time", sa.DateTime, nullable=False),
    ]),
    ("hoimsystem_icu_score", [
        sa.Column("score_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("admission_id", sa.String(36)),
        sa.Column("score_type", sa.String(20), nullable=False),
        sa.Column("scene", sa.String(10), server_default="icu"),
        sa.Column("total_score", sa.Integer, nullable=False),
        sa.Column("detail_json", sa.Text),
        sa.Column("interpretation", sa.String(200)),
        sa.Column("assessor_id", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("assess_time", sa.DateTime, nullable=False),
        sa.Column("create_time", sa.DateTime, nullable=False),
    ]),
    ("hoimsystem_pathway_enrollment", [
        sa.Column("enrollment_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("pathway_id", sa.Integer, sa.ForeignKey("hoimsystem_clinical_pathway.pathway_id"), nullable=False),
        sa.Column("patient_id", sa.Integer, sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False),
        sa.Column("admission_id", sa.String(36)),
        sa.Column("doctor_id", sa.Integer, sa.ForeignKey("hoimsystem_doctor.doctor_id")),
        sa.Column("status", sa.Integer, nullable=False, server_default="1"),
        sa.Column("enroll_date", sa.Date, nullable=False),
        sa.Column("exit_date", sa.Date),
        sa.Column("variation_reason", sa.String(300)),
        sa.Column("variation_type", sa.String(20)),
        sa.Column("exit_reason", sa.String(300)),
        sa.Column("completed_items", sa.Integer, server_default="0"),
        sa.Column("total_items", sa.Integer, server_default="0"),
        sa.Column("create_time", sa.DateTime, nullable=False),
        sa.Column("update_time", sa.DateTime),
    ]),
    ("hoimsystem_hand_hygiene_observation", [
        sa.Column("observation_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("observe_date", sa.Date, nullable=False),
        sa.Column("department", sa.String(100), nullable=False),
        sa.Column("moment", sa.String(50)),
        sa.Column("opportunities", sa.Integer, nullable=False, server_default="0"),
        sa.Column("actions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("observer_id", sa.Integer, sa.ForeignKey("hoimsystem_users.user_id")),
        sa.Column("remark", sa.String(300)),
        sa.Column("create_time", sa.DateTime, nullable=False),
    ]),
]


def upgrade() -> None:
    for name, columns in NEW_TABLES:
        op.create_table(name, *columns)


def downgrade() -> None:
    for name, _ in reversed(NEW_TABLES):
        op.drop_table(name)
