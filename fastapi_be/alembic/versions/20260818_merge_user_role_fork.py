"""merge pre-existing forked heads

20260608_user_role 与 20260806_operation_log 均以 1f24ea8140a3 为父节点，
形成双头。此合并 revision 将两条链归一，alembic upgrade head 可正常执行，
不重写任何已应用数据库的历史。
"""

from collections.abc import Sequence

revision: str = "20260818_merge_user_role_fork"
down_revision: str | Sequence[str] | None = ("20260608_user_role", "20260818_token_revocation")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
