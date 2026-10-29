"""Persistent operation policies and immutable authorization-change history."""

import datetime

from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, Index, Integer, String, Text, event
from sqlalchemy.dialects.mysql import LONGTEXT

from app.database import Base


class AccessPolicyGuard(Base):
    """Serialize policy administration without locking normal business requests."""

    __tablename__ = "hoimsystem_access_policy_guard"
    id = Column(Integer, primary_key=True)


@event.listens_for(AccessPolicyGuard.__table__, "after_create")
def _initialize_guard(table, connection, **_kwargs):
    connection.execute(table.insert().values(id=1))


class AccessPolicy(Base):
    __tablename__ = "hoimsystem_access_policy"
    __table_args__ = (CheckConstraint("kind IN ('role', 'user')", name="ck_access_policy_kind"), CheckConstraint("version > 0", name="ck_access_policy_version"))
    kind = Column(String(8), primary_key=True)
    subject_key = Column(String(40), primary_key=True)
    version = Column(Integer, nullable=False, default=1)
    allowed_json = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=True)
    data_scope = Column(String(16), nullable=False, default="existing")
    disabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None))


class AccessPolicyAudit(Base):
    __tablename__ = "hoimsystem_access_policy_audit"
    __table_args__ = (Index("idx_access_audit_created", "created_at", "id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_id = Column(Integer, nullable=False)
    actor = Column(String(40), nullable=False)
    subject = Column(String(80), nullable=False)
    action = Column(String(40), nullable=False)
    detail = Column(Text().with_variant(LONGTEXT(), "mysql"), nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.datetime.now(datetime.UTC).replace(tzinfo=None))
