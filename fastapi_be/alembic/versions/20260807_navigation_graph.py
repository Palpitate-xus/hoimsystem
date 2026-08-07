"""add configurable indoor navigation graph"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260807_navigation_graph"
down_revision: str | Sequence[str] | None = "20260807_insurance_integration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    node_table = "hoimsystem_navigation_node"
    edge_table = "hoimsystem_navigation_edge"
    if not inspector.has_table(node_table):
        op.create_table(
            node_table,
            sa.Column("node_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(length=40), nullable=False),
            sa.Column("name", sa.String(length=80), nullable=False),
            sa.Column("node_type", sa.String(length=20), nullable=False, server_default="waypoint"),
            sa.Column("floor", sa.String(length=20), nullable=False, server_default=""),
            sa.Column("location", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("campus_id", sa.Integer(), sa.ForeignKey("hoimsystem_hospital_campus.campus_id"), nullable=True),
            sa.Column("department_id", sa.Integer(), sa.ForeignKey("hoimsystem_department.department_id"), nullable=True),
            sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("update_time", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("code", name="uq_navigation_node_code"),
        )
    if not inspector.has_table(edge_table):
        op.create_table(
            edge_table,
            sa.Column("edge_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("from_node_id", sa.Integer(), sa.ForeignKey(f"{node_table}.node_id"), nullable=False),
            sa.Column("to_node_id", sa.Integer(), sa.ForeignKey(f"{node_table}.node_id"), nullable=False),
            sa.Column("distance", sa.Float(), nullable=False, server_default="1"),
            sa.Column("instruction", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("bidirectional", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("create_time", sa.DateTime(), nullable=False),
            sa.Column("update_time", sa.DateTime(), nullable=False),
        )
    inspector = sa.inspect(bind)
    if inspector.has_table(node_table) and "idx_navigation_node_campus" not in {index["name"] for index in inspector.get_indexes(node_table)}:
        op.create_index("idx_navigation_node_campus", node_table, ["campus_id"], unique=False)
    if inspector.has_table(edge_table) and "idx_navigation_edge_nodes" not in {index["name"] for index in inspector.get_indexes(edge_table)}:
        op.create_index("idx_navigation_edge_nodes", edge_table, ["from_node_id", "to_node_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("hoimsystem_navigation_edge"):
        if "idx_navigation_edge_nodes" in {index["name"] for index in inspector.get_indexes("hoimsystem_navigation_edge")}:
            op.drop_index("idx_navigation_edge_nodes", table_name="hoimsystem_navigation_edge")
        op.drop_table("hoimsystem_navigation_edge")
    if inspector.has_table("hoimsystem_navigation_node"):
        if "idx_navigation_node_campus" in {index["name"] for index in inspector.get_indexes("hoimsystem_navigation_node")}:
            op.drop_index("idx_navigation_node_campus", table_name="hoimsystem_navigation_node")
        op.drop_table("hoimsystem_navigation_node")
