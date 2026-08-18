import hashlib
import hmac

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import DigitalSignatureRecord, User

router = APIRouter()


@router.post("/digitalSignature/sign")
def digital_sign(req: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """模拟CA数字签名（签名记录落库，可审计可验证）"""
    import datetime
    import time
    import uuid

    content = str(req.get("content", ""))
    if not content.strip():
        return {"code": 500, "msg": "签名内容不能为空"}
    doc_type = str(req.get("doc_type", "")).strip()
    reference_id = str(req.get("reference_id", "")).strip()
    timestamp = str(int(time.time()))
    sign_hash = hashlib.sha256(f"{content}{current_user.username}{timestamp}".encode()).hexdigest()
    record = DigitalSignatureRecord(
        signature_id=str(uuid.uuid4()),
        signer_id=current_user.user_id,
        doc_type=doc_type or "generic",
        reference_id=reference_id or None,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        sign_hash=sign_hash,
        sign_time=datetime.datetime.fromtimestamp(int(timestamp)),
    )
    db.add(record)
    db.commit()
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "signature_id": record.signature_id,
            "signer": current_user.username,
            "sign_time": timestamp,
            "sign_hash": sign_hash[:32].upper(),
            "cert_sn": "CN=HOIM-CA-" + current_user.username.upper(),
        },
    }


@router.post("/digitalSignature/verify")
def verify_sign(req: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """验签：以签名库中的记录为准，而非信任请求参数。"""
    signature_id = str(req.get("signature_id", "")).strip()
    if not signature_id:
        return {"code": 400, "msg": "缺少 signature_id"}
    record = db.query(DigitalSignatureRecord).filter(DigitalSignatureRecord.signature_id == signature_id).first()
    if not record:
        return {"code": 200, "msg": "success", "data": {"valid": False, "reason": "签名记录不存在"}}
    content = str(req.get("content", ""))
    if not content.strip():
        return {"code": 400, "msg": "content 不能为空（用于与签名时内容比对）"}
    content_hash = hashlib.sha256(content.encode()).hexdigest()
    valid = hmac.compare_digest(record.content_hash, content_hash)
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "valid": valid,
            "reason": "" if valid else "内容与签名时不一致",
            "signer": record.signer.username if record.signer else "",
            "sign_time": record.sign_time.strftime("%Y-%m-%d %H:%M:%S") if record.sign_time else "",
            "doc_type": record.doc_type,
            "reference_id": record.reference_id or "",
        },
    }
