import pytest

from app.models import User
from app.security import verify_password
from bootstrap_admin import bootstrap_admin


def test_bootstrap_creates_one_hashed_super_admin(db_session):
    user = bootstrap_admin(db_session, "root_admin", "Unique-initial-passphrase-2026")

    stored = db_session.get(User, user.user_id)
    assert stored.username == "root_admin"
    assert stored.user_role == "super_admin"
    assert stored.password != "Unique-initial-passphrase-2026"
    assert verify_password("Unique-initial-passphrase-2026", stored.password)

    with pytest.raises(RuntimeError, match="已存在管理员"):
        bootstrap_admin(db_session, "second_admin", "Another-safe-passphrase-2026")


@pytest.mark.parametrize(
    ("username", "password", "message"),
    [
        ("ab", "Unique-initial-passphrase-2026", "用户名长度"),
        ("root_admin", "short", "至少 12 位"),
        ("root_admin", "root_admin-password-2026", "不能包含用户名"),
    ],
)
def test_bootstrap_rejects_unsafe_credentials_before_writing(db_session, username, password, message):
    before = db_session.query(User).count()
    with pytest.raises(ValueError, match=message):
        bootstrap_admin(db_session, username, password)
    assert db_session.query(User).count() == before
