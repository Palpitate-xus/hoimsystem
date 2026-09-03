import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Patient, User


def test_username_uniqueness_is_enforced_by_database(db_session):
    db_session.add(User(username="unique-user", password="hash", user_role="nurse"))
    db_session.commit()
    db_session.add(User(username="unique-user", password="another", user_role="doctor"))

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_patient_identity_uniqueness_is_enforced_by_database(db_session):
    db_session.add(Patient(name="甲", identity="110101199001010011", sex=1))
    db_session.commit()
    db_session.add(Patient(name="乙", identity="110101199001010011", sex=0))

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
