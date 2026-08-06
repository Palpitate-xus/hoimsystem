#!/usr/bin/env python3
"""Create the documented default accounts for a fresh HOIM database.

The operation is idempotent: existing users are kept, while missing users and
the minimum doctor/patient profiles required by the frontend are created.
Use ``--reset-passwords`` only for a disposable development/test database.
"""

import argparse
import datetime

from sqlalchemy.orm import Session

from app.database import Base, engine
from app.models import Department, Doctor, Patient, User
from app.schema_compat import ensure_operation_log_schema
from app.security import hash_password, is_bcrypt_hash, verify_password


DEFAULT_ACCOUNTS = (
    ("admin", "admin123", "admin"),
    ("super01", "123456", "super_admin"),
    ("director01", "123456", "director"),
    ("doctor1", "doctor123", "doctor"),
    ("nurse01", "123456", "nurse"),
    ("cashier01", "123456", "cashier"),
    ("pharmacist01", "123456", "pharmacist"),
    ("guide01", "123456", "guide"),
    ("lab01", "123456", "lab_technician"),
    ("registrar01", "123456", "registrar"),
    ("patient1", "123456", "patient"),
)


def _ensure_user(db: Session, username: str, password: str, role: str, reset_passwords: bool) -> User:
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        user = User(username=username, password=hash_password(password), user_role=role)
        db.add(user)
        db.flush()
        return user

    if user.user_role != role:
        user.user_role = role
    if reset_passwords and (not is_bcrypt_hash(user.password) or not verify_password(password, user.password)):
        user.password = hash_password(password)
    db.add(user)
    db.flush()
    return user


def _ensure_profiles(db: Session, users: dict[str, User]) -> None:
    department = db.query(Department).filter(Department.name == "内科").first()
    if department is None:
        department = Department(name="内科", phone="01000000000", location="门诊楼", director=None)
        db.add(department)
        db.flush()

    for username, name, phone in (
        ("doctor1", "示例医生", "13900000001"),
        ("director01", "示例主任", "13900000002"),
    ):
        user = users[username]
        doctor = db.query(Doctor).filter(Doctor.user_id == user.user_id).first()
        if doctor is None:
            db.add(
                Doctor(
                    name=name,
                    sex=1,
                    department_id=department.department_id,
                    title="主治医师",
                    education="本科",
                    phone=phone,
                    permission="allow",
                    user_id=user.user_id,
                )
            )

    patient_user = users["patient1"]
    patient = db.query(Patient).filter(Patient.identity == patient_user.username).first()
    if patient is None:
        db.add(
            Patient(
                name="示例患者",
                sex=1,
                identity=patient_user.username,
                birthday=datetime.date(1990, 1, 1),
                phone="13800000001",
                address="",
                permission="allow",
                allergy_history="",
                prepaid_balance=0,
            )
        )


def seed_default_accounts(reset_passwords: bool = False) -> list[str]:
    """Seed documented accounts and return the usernames that were ensured."""
    Base.metadata.create_all(bind=engine)
    ensure_operation_log_schema(engine)
    with Session(engine) as db:
        users = {
            username: _ensure_user(db, username, password, role, reset_passwords)
            for username, password, role in DEFAULT_ACCOUNTS
        }
        _ensure_profiles(db, users)
        db.commit()
    return [username for username, _, _ in DEFAULT_ACCOUNTS]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed HOIM default development accounts")
    parser.add_argument(
        "--reset-passwords",
        action="store_true",
        help="reset seeded account passwords; use only for a disposable test database",
    )
    args = parser.parse_args()
    usernames = seed_default_accounts(reset_passwords=args.reset_passwords)
    print(f"[OK] Ensured {len(usernames)} default accounts: {', '.join(usernames)}")


if __name__ == "__main__":
    main()
