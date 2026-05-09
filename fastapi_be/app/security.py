import bcrypt


_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, stored: str) -> bool:
    if not stored:
        return False
    if is_bcrypt_hash(stored):
        try:
            return bcrypt.checkpw(plain.encode("utf-8"), stored.encode("utf-8"))
        except ValueError:
            return False
    # legacy plaintext fallback — caller is expected to upgrade on success
    return plain == stored


def is_bcrypt_hash(value: str) -> bool:
    return isinstance(value, str) and value.startswith(_BCRYPT_PREFIXES) and len(value) >= 59
