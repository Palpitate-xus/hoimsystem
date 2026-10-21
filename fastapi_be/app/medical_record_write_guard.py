"""Current ownership and finite lock acquisition for two legacy note writers.

Only the actual original Doctor owner may write. Technical record locators use
current SHARE NOWAIT, then Patient X NOWAIT precedes clinical Record X. NOWAIT
is essential: a Source can hold Patient X before reading Record; no writer may
wait for Patient while retaining the reverse Record SHARE. No global Gate or
new patient/clinical access grant is introduced here.
"""

from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError

from app.dependencies import CLINICAL_ROLES
from app.models import Doctor, MedicalRecord, Patient, User

MYSQL_LOCK_CONFLICTS = frozenset({1205, 1213, 3572})


def current_rows(query, *, shared=False):
    return query.populate_existing().with_for_update(read=shared, nowait=True)


@contextmanager
def medical_record_transaction(db):
    try:
        yield
    except OperationalError as exc:
        db.rollback()
        code = exc.orig.args[0] if getattr(exc, "orig", None) is not None and exc.orig.args else None
        if code in MYSQL_LOCK_CONFLICTS:
            raise HTTPException(409, "病历或关联对象存在当前锁冲突，本次修改已回滚，请重新读取") from exc
        raise
    except Exception:
        db.rollback()
        raise


def current_owned_record(db, user, identifier, *, signing=False):
    """No clinical TEXT before current actor, Doctor and Patient are checked."""
    state = inspect(user, raiseerr=False)
    epoch = {key: state.dict[key] for key in ("user_role", "token_invalid_before") if key in state.dict} if state is not None else {}
    user_id = state.identity[0] if state is not None and state.identity is not None else getattr(user, "user_id", None)
    with db.no_autoflush:
        actor = current_rows(db.query(User).filter_by(user_id=user_id), shared=True).one_or_none()
        if actor is None or actor.user_role not in CLINICAL_ROLES or any(getattr(actor, key) != value for key, value in epoch.items()):
            raise HTTPException(403, "当前角色或登录授权已变化，未修改或签署病历")
        doctor = current_rows(db.query(Doctor.doctor_id).filter_by(user_id=user_id), shared=True).first()
        locator = current_rows(db.query(MedicalRecord.patient_id, MedicalRecord.doctor_id).filter_by(medical_record_id=identifier), shared=True).one_or_none()
        if locator is None:
            db.rollback()
            return None, {"code": 500, "msg": "病历不存在"}
        if doctor is None or locator.doctor_id != doctor.doctor_id:
            db.rollback()
            return None, {"code": 403, "msg": "无权签名他人病历" if signing else "无权修改他人病历"}
        if locator.patient_id is None:
            raise HTTPException(409, "原病历患者绑定未知，未猜测归属或写入")
        patient = current_rows(db.query(Patient.patient_id).filter_by(patient_id=locator.patient_id)).one_or_none()
        if patient is None:
            raise HTTPException(409, "原病历患者绑定已变化，未写入")
        record = current_rows(db.query(MedicalRecord).filter_by(medical_record_id=identifier, patient_id=locator.patient_id, doctor_id=doctor.doctor_id)).one_or_none()
        if record is None:
            raise HTTPException(409, "当前病历Doctor或Patient绑定已变化，未读取其他正文")
        if record.status != 0:
            db.rollback()
            return None, {"code": 500, "msg": "病历已签名"} if signing else {"code": 403, "msg": "已签名病历不可修改"}
        return record, None
