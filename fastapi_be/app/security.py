import base64

import bcrypt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")

# RSA 只用于短密码的传输保护，私钥仅保存在当前后端进程内；密码落库仍使用 bcrypt。
_RSA_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_RSA_PUBLIC_KEY_DER = _RSA_PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.DER,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
)


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


def public_key_base64() -> str:
    """Return the DER SubjectPublicKeyInfo public key for browser RSA encryption."""
    return base64.b64encode(_RSA_PUBLIC_KEY_DER).decode("ascii")


def decrypt_transport_password(value: str | None) -> str | None:
    """Decrypt an RSA1 transport value while keeping plaintext clients backward compatible."""
    if not isinstance(value, str):
        return None
    if not value.startswith("RSA1:"):
        return value
    try:
        ciphertext = base64.b64decode(value[5:], validate=True)
        return _RSA_PRIVATE_KEY.decrypt(ciphertext, padding.PKCS1v15()).decode("utf-8")
    except (ValueError, TypeError, UnicodeDecodeError):
        return None
