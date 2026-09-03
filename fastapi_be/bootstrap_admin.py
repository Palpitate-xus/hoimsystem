#!/usr/bin/env python3
"""Create the first production administrator without shipping a default password."""

import argparse
import getpass

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.dependencies import ADMIN_ROLES, ROLE_ADMIN, ROLE_SUPER_ADMIN
from app.models import User
from app.security import hash_password

MIN_PASSWORD_LENGTH = 12
DISALLOWED_PASSWORDS = {"admin123", "password", "123456", "12345678", "changeme"}


def bootstrap_admin(db, username: str, password: str, role: str = ROLE_SUPER_ADMIN) -> User:
    username = username.strip()
    if not 3 <= len(username) <= 20:
        raise ValueError("管理员用户名长度必须为 3 至 20 个字符")
    if role not in ADMIN_ROLES:
        raise ValueError("首个管理员角色只能是 admin 或 super_admin")
    if len(password) < MIN_PASSWORD_LENGTH or password.lower() in DISALLOWED_PASSWORDS:
        raise ValueError(f"管理员密码至少 {MIN_PASSWORD_LENGTH} 位且不能使用常见弱口令")
    if username.lower() in password.lower():
        raise ValueError("管理员密码不能包含用户名")

    # Serialize the check-and-create sequence on PostgreSQL. This prevents two
    # simultaneous bootstrap shells from both creating a privileged account.
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(hashtext('hoimsystem.bootstrap_admin'))"))

    if db.query(User.user_id).filter(User.user_role.in_(ADMIN_ROLES)).first():
        raise RuntimeError("系统已存在管理员；请登录后通过权限管理创建或调整账号")
    if db.query(User.user_id).filter(User.username == username).first():
        raise RuntimeError("用户名已存在")

    user = User(username=username, password=hash_password(password), user_role=role)
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise RuntimeError("管理员初始化发生并发冲突，请检查现有账号") from exc
    db.refresh(user)
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first HOIM administrator")
    parser.add_argument("--username", required=True, help="3-20 character administrator username")
    parser.add_argument("--role", choices=(ROLE_ADMIN, ROLE_SUPER_ADMIN), default=ROLE_SUPER_ADMIN)
    args = parser.parse_args()
    password = getpass.getpass("New administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")

    with SessionLocal() as db:
        user = bootstrap_admin(db, args.username, password, args.role)
    print(f"[OK] Created initial {user.user_role} account: {user.username}")


if __name__ == "__main__":
    main()
