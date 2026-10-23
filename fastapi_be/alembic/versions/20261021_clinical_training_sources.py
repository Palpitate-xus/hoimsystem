"""Add finite synthetic teaching lessons and independent publication reviews."""

from sqlalchemy import text

from alembic import op
from app.ai.clinical_training_models import TRAINING_SOURCE_MODELS

revision = "20261021_training_sources"
down_revision = "20261021_native_research_merge"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for model in TRAINING_SOURCE_MODELS:
        model.__table__.create(bind, checkfirst=False)
    bind.execute(text("INSERT INTO hoimsystem_ai_training_write_gate (gate_id, revision) VALUES (1, 1)"))


def downgrade():
    bind = op.get_bind()
    for model in reversed(TRAINING_SOURCE_MODELS):
        model.__table__.drop(bind, checkfirst=False)
