import hashlib
import hmac
import re

from fastapi import APIRouter, Depends

from app.dependencies import get_current_user

router = APIRouter()


@router.post("/digitalSignature/sign")
def digital_sign(req: dict, current_user=Depends(get_current_user)):
    """模拟CA数字签名"""
    import time

    content = str(req.get("content", ""))
    if not content.strip():
        return {"code": 500, "msg": "签名内容不能为空"}
    timestamp = str(int(time.time()))
    sign_data = hashlib.sha256(f"{content}{current_user.username}{timestamp}".encode()).hexdigest()
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "signer": current_user.username,
            "sign_time": timestamp,
            "sign_hash": sign_data[:32].upper(),
            "cert_sn": "CN=HOIM-CA-" + current_user.username.upper(),
        },
    }


@router.post("/digitalSignature/verify")
def verify_sign(req: dict, current_user=Depends(get_current_user)):
    """模拟验签"""
    content = str(req.get("content", ""))
    signer = str(req.get("signer", ""))
    sign_time = str(req.get("sign_time", ""))
    sign_hash = str(req.get("sign_hash", "")).upper()
    cert_sn = str(req.get("cert_sn", ""))
    cert_match = re.fullmatch(r"CN=HOIM-CA-(.+)", cert_sn)
    valid = bool(content.strip() and signer and sign_time.isdigit() and sign_hash and cert_match and cert_match.group(1) == signer.upper())
    if valid:
        expected = hashlib.sha256(f"{content}{signer}{sign_time}".encode()).hexdigest()[:32].upper()
        valid = hmac.compare_digest(expected, sign_hash)
    return {"code": 200, "msg": "success", "data": {"valid": valid}}
