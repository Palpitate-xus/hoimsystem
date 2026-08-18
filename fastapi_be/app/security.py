import base64
import os
import tempfile
import time

import bcrypt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")

# RSA 只用于短密码的传输保护；密码落库仍使用 bcrypt。
#
# 密钥来源（按优先级）：
# 1. TRANSPORT_RSA_PRIVATE_KEY_PEM 环境变量（多 worker 生产部署必须使用，
#    否则每个 gunicorn worker 各自生成一把密钥，登录时约 3/4 概率解密失败）
# 2. 共享密钥文件（TRANSPORT_RSA_KEY_FILE，默认 /tmp/hoimsystem_transport_key.pem，
#    通过 O_CREAT|O_EXCL 原子创建，多 worker 竞争时先到者生成、其余复用同一把）
# 3. 单进程开发模式：直接进程内生成


def _load_or_create_private_key() -> rsa.RSAPrivateKey:
    pem_text = os.environ.get("TRANSPORT_RSA_PRIVATE_KEY_PEM", "").strip()
    if pem_text:
        key = serialization.load_pem_private_key(pem_text.encode("ascii"), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("TRANSPORT_RSA_PRIVATE_KEY_PEM 必须是 RSA 私钥")
        return key

    key_file = os.environ.get("TRANSPORT_RSA_KEY_FILE", "/tmp/hoimsystem_transport_key.pem")
    deadline = time.monotonic() + 10.0  # 最多等待 10 秒让创建者写入完成
    while time.monotonic() < deadline:
        try:
            fd = os.open(key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                with open(key_file, "rb") as f:
                    data = f.read()
                if data:
                    key = serialization.load_pem_private_key(data, password=None)
                    if isinstance(key, rsa.RSAPrivateKey):
                        return key
                # 文件为空：创建者尚未写入，短暂等待后重读
                time.sleep(0.05)
                continue
            except Exception:
                # 文件损坏等异常：删除后重新生成（仅在确实是本机临时文件时）
                try:
                    if os.path.realpath(key_file).startswith(tempfile.gettempdir()):
                        os.unlink(key_file)
                except OSError:
                    pass
                continue
        # 抢到创建权：生成并写入
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        try:
            os.write(fd, pem)
        finally:
            os.close(fd)
        return key
    # 兜底：进程内独立生成（仅开发模式可接受）
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


_RSA_PRIVATE_KEY = _load_or_create_private_key()
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
