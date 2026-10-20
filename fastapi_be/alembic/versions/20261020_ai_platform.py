"""Add versioned AI configuration, knowledge, tasks and governance tables."""

import sqlalchemy as sa

from alembic import op

revision = "20261020_ai_platform"
down_revision = "20260911_drg_rule_null_safe_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the frozen initial AI schema without changing existing business data."""
    op.create_table(
        "hoimsystem_ai_provider",
        sa.Column("provider_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("api_base", sa.String(length=1000), nullable=False, primary_key=False),
        sa.Column("model", sa.String(length=160), nullable=False, primary_key=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False, primary_key=False),
        sa.Column("api_key_env", sa.String(length=100), nullable=False, primary_key=False),
        sa.Column("enabled", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("allows_patient_data", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("temperature", sa.Numeric(precision=4, scale=3), nullable=False, primary_key=False),
        sa.Column("supported_features_json", sa.Text(), nullable=False, primary_key=False),
        sa.Column("validation_report", sa.Text(), nullable=False, primary_key=False),
        sa.Column("validated_at", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False, primary_key=False),
        sa.Column("create_time", sa.DateTime(), nullable=False, primary_key=False),
        sa.Column("update_time", sa.DateTime(), nullable=False, primary_key=False),
        sa.UniqueConstraint("name", name=None),
    )
    op.create_table(
        "hoimsystem_ai_prompt_version",
        sa.Column("prompt_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("feature_key", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("task_prompt", sa.Text(), nullable=False, primary_key=False),
        sa.Column("change_note", sa.String(length=1000), nullable=False, primary_key=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False, primary_key=False),
        sa.Column("create_time", sa.DateTime(), nullable=False, primary_key=False),
        sa.UniqueConstraint("feature_key", "version", name="uq_ai_prompt_feature_version"),
    )
    op.create_index("ix_hoimsystem_ai_prompt_version_feature_key", "hoimsystem_ai_prompt_version", ["feature_key"], unique=False)
    op.create_table(
        "hoimsystem_ai_feature_config",
        sa.Column("feature_key", sa.String(length=64), nullable=False, primary_key=True),
        sa.Column("enabled", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_provider.provider_id"), nullable=True, primary_key=False),
        sa.Column("allowed_roles_json", sa.Text(), nullable=False, primary_key=False),
        sa.Column("validation_status", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("validation_note", sa.Text(), nullable=False, primary_key=False),
        sa.Column("validated_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True, primary_key=False),
        sa.Column("validated_at", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("active_prompt_id", sa.String(length=36), sa.ForeignKey("hoimsystem_ai_prompt_version.prompt_id"), nullable=True, primary_key=False),
        sa.Column("daily_limit", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("revision", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False, primary_key=False),
        sa.Column("update_time", sa.DateTime(), nullable=False, primary_key=False),
    )
    op.create_table(
        "hoimsystem_ai_knowledge_document",
        sa.Column("document_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False, primary_key=False),
        sa.Column("version", sa.String(length=80), nullable=False, primary_key=False),
        sa.Column("source_uri", sa.String(length=2000), nullable=False, primary_key=False),
        sa.Column("category", sa.String(length=40), nullable=False, primary_key=False),
        sa.Column("content", sa.Text(), nullable=False, primary_key=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("feature_keys_json", sa.Text(), nullable=False, primary_key=False),
        sa.Column("department_id", sa.Integer(), sa.ForeignKey("hoimsystem_department.department_id"), nullable=True, primary_key=False),
        sa.Column("status", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("effective_from", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("effective_to", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=True, primary_key=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True, primary_key=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False, primary_key=False),
        sa.Column("create_time", sa.DateTime(), nullable=False, primary_key=False),
        sa.UniqueConstraint("title", "version", name="uq_ai_knowledge_title_version"),
    )
    op.create_index("idx_ai_knowledge_status_category", "hoimsystem_ai_knowledge_document", ["status", "category"], unique=False)
    op.create_table(
        "hoimsystem_ai_run",
        sa.Column("run_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("feature_key", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("hoimsystem_ai_provider.provider_id"), nullable=True, primary_key=False),
        sa.Column("provider_revision", sa.Integer(), nullable=True, primary_key=False),
        sa.Column("prompt_version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("context_digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=True, primary_key=False),
        sa.Column("encounter_ref", sa.String(length=64), nullable=True, primary_key=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("preview", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("input_json", sa.Text(), nullable=False, primary_key=False),
        sa.Column("result_json", sa.Text(), nullable=False, primary_key=False),
        sa.Column("evidence_json", sa.Text(), nullable=False, primary_key=False),
        sa.Column("context_metadata_json", sa.Text(), nullable=False, primary_key=False),
        sa.Column("error_code", sa.String(length=80), nullable=True, primary_key=False),
        sa.Column("error_message", sa.String(length=500), nullable=True, primary_key=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True, primary_key=False),
        sa.Column("create_time", sa.DateTime(), nullable=False, primary_key=False),
        sa.Column("finish_time", sa.DateTime(), nullable=True, primary_key=False),
    )
    op.create_index("idx_ai_run_feature_time", "hoimsystem_ai_run", ["feature_key", "create_time"], unique=False)
    op.create_index("idx_ai_run_requester_time", "hoimsystem_ai_run", ["requested_by", "create_time"], unique=False)
    op.create_table(
        "hoimsystem_ai_feedback",
        sa.Column("feedback_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("run_id", sa.String(length=36), sa.ForeignKey("hoimsystem_ai_run.run_id"), nullable=False, primary_key=False),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False, primary_key=False),
        sa.Column("outcome", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("comment", sa.String(length=2000), nullable=False, primary_key=False),
        sa.Column("create_time", sa.DateTime(), nullable=False, primary_key=False),
    )
    op.create_index("ix_hoimsystem_ai_feedback_run_id", "hoimsystem_ai_feedback", ["run_id"], unique=False)
    op.create_table(
        "hoimsystem_ai_patient_grant",
        sa.Column("grant_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False, primary_key=False),
        sa.Column("patient_id", sa.Integer(), sa.ForeignKey("hoimsystem_patient.patient_id"), nullable=False, primary_key=False),
        sa.Column("category", sa.String(length=40), nullable=False, primary_key=False),
        sa.Column("reason", sa.String(length=500), nullable=False, primary_key=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False, primary_key=False),
        sa.Column("revoked", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False, primary_key=False),
        sa.Column("create_time", sa.DateTime(), nullable=False, primary_key=False),
    )
    op.create_index("idx_ai_grant_user_patient", "hoimsystem_ai_patient_grant", ["user_id", "patient_id"], unique=False)
    op.create_table(
        "hoimsystem_ai_audit_event",
        sa.Column("event_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("hoimsystem_users.user_id"), nullable=False, primary_key=False),
        sa.Column("action", sa.String(length=80), nullable=False, primary_key=False),
        sa.Column("target", sa.String(length=120), nullable=False, primary_key=False),
        sa.Column("detail_json", sa.Text(), nullable=False, primary_key=False),
        sa.Column("create_time", sa.DateTime(), nullable=False, primary_key=False),
    )


def downgrade() -> None:
    """Remove only AI-owned tables in reverse dependency order."""
    op.drop_table("hoimsystem_ai_audit_event")
    op.drop_table("hoimsystem_ai_patient_grant")
    op.drop_table("hoimsystem_ai_feedback")
    op.drop_table("hoimsystem_ai_run")
    op.drop_table("hoimsystem_ai_knowledge_document")
    op.drop_table("hoimsystem_ai_feature_config")
    op.drop_table("hoimsystem_ai_prompt_version")
    op.drop_table("hoimsystem_ai_provider")
