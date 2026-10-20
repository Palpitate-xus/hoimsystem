"""Keep unknown nursing assessments and the stated provenance of observation times."""

import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from alembic import op

revision = "20261020_ai_nursing_sources"
down_revision = "20261020_ai_image_assets"
branch_labels = None
depends_on = None

ASSESSMENT = "hoimsystem_nursing_assessment"
CRITICAL = "hoimsystem_critical_care_record"
ICU = "hoimsystem_icu_score"
ASSESSMENT_FIELDS = ("adl_score", "pressure_ulcer_risk", "fall_risk", "consciousness", "nutrition_risk")
PRECISE_TIME = sa.DateTime().with_variant(mysql.DATETIME(fsp=6), "mysql")


def upgrade():
    # Batch mode rebuilds SQLite tables when needed, and uses native ALTER on
    # MySQL. Existing integer values, scores, interpretations and times remain.
    with op.batch_alter_table(ASSESSMENT) as batch:
        for name in ASSESSMENT_FIELDS:
            batch.alter_column(name, existing_type=sa.Integer(), existing_nullable=False, nullable=True, server_default=None)
        batch.add_column(sa.Column("entry_version", sa.String(32), nullable=False, server_default="legacy_unverified"))
        batch.add_column(sa.Column("assessed_at", PRECISE_TIME, nullable=True))
    with op.batch_alter_table(CRITICAL) as batch:
        batch.alter_column("consciousness", existing_type=sa.Integer(), existing_nullable=False, nullable=True, server_default=None)
        batch.alter_column("record_time", existing_type=sa.DateTime(), existing_nullable=False, type_=PRECISE_TIME)
        batch.add_column(sa.Column("entry_version", sa.String(32), nullable=False, server_default="legacy_unverified"))
        batch.add_column(sa.Column("time_basis", sa.String(24), nullable=False, server_default="unspecified"))
    with op.batch_alter_table(ICU) as batch:
        batch.add_column(sa.Column("calculation_version", sa.String(40), nullable=False, server_default="legacy_unverified"))
        batch.add_column(sa.Column("assessed_at", PRECISE_TIME, nullable=True))


def _nonzero_microseconds(column, dialect_name):
    if dialect_name == "sqlite":
        # SQLite strftime('%f') rounds to milliseconds, so it misses a 1 us
        # value. Inspect all fractional digits of its exact datetime text.
        value = sa.cast(column, sa.String())
        dot = sa.func.instr(value, ".")
        return sa.and_(dot > 0, sa.func.trim(sa.func.substr(value, dot + 1), "0") != "")
    if dialect_name == "mysql":
        return sa.func.microsecond(column) != 0
    seconds = sa.extract("second", column)
    return seconds != sa.func.floor(seconds)


def downgrade():
    # Check every affected table before any DDL, including on SQLite where a
    # later failed ALTER cannot reliably roll back earlier schema changes.
    connection = op.get_bind()
    for table_name, names in ((ASSESSMENT, ASSESSMENT_FIELDS), (CRITICAL, ("consciousness",))):
        table = sa.table(table_name, *(sa.column(name, sa.Integer()) for name in names))
        if connection.scalar(sa.select(sa.literal(1)).select_from(table).where(sa.or_(*(table.c[name].is_(None) for name in names))).limit(1)):
            raise RuntimeError("Cannot downgrade nursing sources while unknown assessment values exist; null values must not be replaced with invented normal scores")
    for table_name, name in ((ASSESSMENT, "assessed_at"), (CRITICAL, "record_time"), (ICU, "assessed_at")):
        table = sa.table(table_name, sa.column(name, PRECISE_TIME))
        if connection.scalar(sa.select(sa.literal(1)).select_from(table).where(_nonzero_microseconds(table.c[name], connection.dialect.name)).limit(1)):
            raise RuntimeError("Cannot downgrade nursing sources while nonzero microsecond timestamps exist; source time precision must not be silently discarded")
    with op.batch_alter_table(ICU) as batch:
        batch.drop_column("assessed_at")
        batch.drop_column("calculation_version")
    with op.batch_alter_table(CRITICAL) as batch:
        batch.drop_column("time_basis")
        batch.drop_column("entry_version")
        batch.alter_column("consciousness", existing_type=sa.Integer(), existing_nullable=True, nullable=False, server_default="0")
        batch.alter_column("record_time", existing_type=PRECISE_TIME, existing_nullable=False, type_=sa.DateTime())
    with op.batch_alter_table(ASSESSMENT) as batch:
        batch.drop_column("assessed_at")
        batch.drop_column("entry_version")
        for name in ASSESSMENT_FIELDS:
            batch.alter_column(name, existing_type=sa.Integer(), existing_nullable=True, nullable=False, server_default=None if name == "adl_score" else "0")
