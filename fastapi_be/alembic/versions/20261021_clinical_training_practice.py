"""Add immutable server-scored training practice submissions."""

from alembic import op
from app.ai.clinical_training_practice_models import TRAINING_PRACTICE_MODELS

revision = "20261021_training_practice"
down_revision = "20261021_training_sources"
branch_labels = None
depends_on = None


def upgrade():
    for model in TRAINING_PRACTICE_MODELS:
        model.__table__.create(op.get_bind(), checkfirst=False)


def downgrade():
    for model in reversed(TRAINING_PRACTICE_MODELS):
        model.__table__.drop(op.get_bind(), checkfirst=False)
