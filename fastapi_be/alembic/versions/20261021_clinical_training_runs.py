"""Add full training Task artifacts and claim-bound accepted feedback drafts."""

from alembic import op
from app.ai.clinical_training_run_models import TRAINING_RUN_MODELS

revision = "20261021_training_runs"
down_revision = "20261021_training_practice"
branch_labels = None
depends_on = None


def upgrade():
    for model in TRAINING_RUN_MODELS:
        model.__table__.create(op.get_bind(), checkfirst=False)


def downgrade():
    for model in reversed(TRAINING_RUN_MODELS):
        model.__table__.drop(op.get_bind(), checkfirst=False)
