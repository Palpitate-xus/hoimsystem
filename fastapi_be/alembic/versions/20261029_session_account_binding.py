"""Bind sessions to immutable account identities, including recreated usernames."""

import uuid

import sqlalchemy as sa

from alembic import op

revision = "20261029_session_binding"
down_revision = "20261029_fine_permissions"
branch_labels = None
depends_on = None

TABLE = "hoimsystem_users"
INDEX = "uq_users_auth_subject"


def upgrade():
    connection = op.get_bind()
    columns = {column["name"]: column for column in sa.inspect(connection).get_columns(TABLE)}
    if "auth_subject" not in columns:
        op.add_column(TABLE, sa.Column("auth_subject", sa.String(32), nullable=True))
    users = sa.table(TABLE, sa.column("user_id", sa.Integer()), sa.column("auth_subject", sa.String(32)))
    statement = users.update().where(users.c.user_id == sa.bindparam("bound_user_id")).values(auth_subject=sa.bindparam("bound_subject"))
    while True:
        identifiers = connection.execute(sa.select(users.c.user_id).where(users.c.auth_subject.is_(None)).limit(1000)).scalars().all()
        if not identifiers:
            break
        connection.execute(statement, [{"bound_user_id": identifier, "bound_subject": uuid.uuid4().hex} for identifier in identifiers])
    current = {column["name"]: column for column in sa.inspect(connection).get_columns(TABLE)}
    if current["auth_subject"]["nullable"]:
        with op.batch_alter_table(TABLE) as batch:
            batch.alter_column("auth_subject", existing_type=sa.String(32), nullable=False)
    if INDEX not in {index["name"] for index in sa.inspect(connection).get_indexes(TABLE)}:
        op.create_index(INDEX, TABLE, ["auth_subject"], unique=True)


def downgrade():
    connection = op.get_bind()
    if INDEX in {index["name"] for index in sa.inspect(connection).get_indexes(TABLE)}:
        op.drop_index(INDEX, table_name=TABLE)
    if "auth_subject" in {column["name"] for column in sa.inspect(connection).get_columns(TABLE)}:
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column("auth_subject")
