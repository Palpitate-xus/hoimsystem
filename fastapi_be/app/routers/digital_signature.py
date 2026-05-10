from fastapi import APIRouter, Depends
from app.dependencies import get_current_user

router = APIRouter()

@router.post("/digitalSignature/sign")
def digital_sign(req: dict, current_user=Depends(get_current_user)):
    """模拟CA数字签名"""
    import hashlib, time
    content = req.get("content", "")
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
        }
    }

@router.post("/digitalSignature/verify")
def verify_sign(req: dict):
    """模拟验签"""
    return {"code": 200, "msg": "success", "data": {"valid": True}}
