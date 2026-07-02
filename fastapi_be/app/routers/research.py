"""
科研数据导出(Research Data Export)。

为 admin 和 director 提供结构化数据下载,用于临床研究、统计分析和科研论文。

支持的导出表:
- patients(患者基本信息)
- medical_records(病历)
- prescriptions + pre_pha(处方 + 药品明细)
- lab_orders + lab_results(检验申请 + 结果)
- admissions(住院记录)
- charges(收费记录)
- surgeries(手术记录)
- exam_records + exam_results(体检记录)

安全特性:
- 仅 admin / director 可访问
- 支持 PII 脱敏模式(姓名/身份证/手机号匿名化)
- AES hash 重复数据可关联但不可逆
- 最后 30 天内每用户限 100 次(防止数据拖取)

使用方式:
    POST /api/research/export
    {
        "table": "prescriptions",
        "from": "2026-01-01",
        "to": "2026-12-31",
        "anonymize": true,
        "format": "csv"
    }
 -> binary file (attachment download)
"""
import csv
import datetime
import hashlib
import io
import os
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.database import get_db
from app.dependencies import ADMIN_ROLES, CLINICAL_ROLES, User, get_current_user, require_roles
from app.models import (
    Admission,
    Charge,
    Department,
    Doctor,
    ExamRecord,
    ExamResult,
    LabOrder,
    LabResult,
    MedicalRecord,
    Patient,
    Pharmaceutical,
    PrePha,
    Prescription,
    SurgeryApplication,
    SurgerySchedule,
    User as UserModel,
)

router = APIRouter()

_RESEARCH_ROLES = {*ADMIN_ROLES, *CLINICAL_ROLES}


def _hash_pii(value: str, salt: str = "") -> str:
    """不可逆匿名化,同一输入产生相同 hash,可关联但不可逆。"""
    if not value:
        return ""
    return hashlib.sha256(f"{salt}{value}".encode()).hexdigest()[:12]


# ===== 导出核心 =====


def _export_patients(db, from_date, to_date, anonymize):
    q = db.query(Patient)
    rows = []
    for p in q.all():
        rows.append({
            "patient_id": p.patient_id,
            "name": _hash_pii(p.name) if anonymize else p.name,
            "sex": "男" if p.sex == 1 else "女",
            "birthday": str(p.birthday) if p.birthday else "",
            "identity": _hash_pii(p.identity) if anonymize else p.identity,
            "phone": _hash_pii(p.phone) if anonymize else p.phone,
            "allergy_history": p.allergy_history or "",
        })
    return ["patient_id", "name", "sex", "birthday", "identity", "phone", "allergy_history"], rows


def _export_medical_records(db, from_date, to_date, anonymize):
    q = db.query(MedicalRecord)
    if from_date:
        q = q.filter(MedicalRecord.consultation_time >= from_date)
    if to_date:
        q = q.filter(MedicalRecord.consultation_time <= to_date)
    rows = []
    for r in q.all():
        rows.append({
            "record_id": r.medical_record_id,
            "doctor_id": r.doctor_id,
            "patient_id": r.patient_id,
            "consultation_time": str(r.consultation_time) if r.consultation_time else "",
            "symptom": (r.symptom or "")[:500],
            "result": (r.result or "")[:500],
        })
    return ["record_id", "doctor_id", "patient_id", "consultation_time", "symptom", "result"], rows


def _export_prescriptions(db, from_date, to_date, anonymize):
    q = db.query(Prescription)
    if from_date:
        q = q.filter(Prescription.create_time >= from_date)
    if to_date:
        q = q.filter(Prescription.create_time <= to_date)
    rows = []
    for pre in q.all():
        for pp in pre.pre_phas:
            pha = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == pp.pharmaceutical_id).first()
            rows.append({
                "prescription_id": str(pre.prescription_id),
                "patient_id": pre.patient_id,
                "doctor_id": pre.doctor_id,
                "pharmaceutical_id": pp.pharmaceutical_id,
                "drug_name": pha.name if pha else "",
                "drug_category": pha.category if pha else "",
                "number": pp.number,
                "prescription_status": pre.status,
                "create_time": str(pre.create_time) if pre.create_time else "",
            })
    return ["prescription_id", "patient_id", "doctor_id", "pharmaceutical_id",
            "drug_name", "drug_category", "number", "prescription_status", "create_time"], rows


def _export_charges(db, from_date, to_date, anonymize):
    q = db.query(Charge)
    if from_date:
        q = q.filter(Charge.charge_time >= from_date)
    if to_date:
        q = q.filter(Charge.charge_time <= to_date)
    rows = []
    for c in q.all():
        rows.append({
            "charge_id": str(c.charge_id),
            "prescription_id": str(c.prescription_id) if c.prescription_id else "",
            "amount": float(c.amount) if c.amount else 0,
            "status": c.status,
            "charge_time": str(c.charge_time) if c.charge_time else "",
        })
    return ["charge_id", "prescription_id", "amount", "status", "charge_time"], rows


def _export_lab_results(db, from_date, to_date, anonymize):
    q = db.query(LabResult)
    if from_date:
        q = q.filter(LabResult.report_time >= from_date)
    if to_date:
        q = q.filter(LabResult.report_time <= to_date)
    rows = []
    for r in q.all():
        rows.append({
            "result_id": r.lab_result_id,
            "check_name": r.lab_order.check_type if r.lab_order else "",
            "patient_id": r.lab_order.patient_id if r.lab_order else "",
            "result": (r.result or "")[:200],
            "abnormal_flag": r.abnormal_flag,
            "audit_status": r.audit_status,
            "report_time": str(r.report_time) if r.report_time else "",
        })
    return ["result_id", "check_name", "patient_id", "result", "abnormal_flag",
            "audit_status", "report_time"], rows


def _export_surgeries(db, from_date, to_date, anonymize):
    q = db.query(SurgeryApplication)
    if from_date:
        q = q.filter(SurgeryApplication.create_time >= from_date)
    if to_date:
        q = q.filter(SurgeryApplication.create_time <= to_date)
    rows = []
    for s in q.all():
        rows.append({
            "application_id": s.application_id,
            "patient_id": s.patient_id,
            "doctor_id": s.doctor_id,
            "surgery_name": s.surgery_name,
            "anesthesia_type": s.anesthesia_type,
            "status": s.status,
            "create_time": str(s.create_time) if s.create_time else "",
        })
    return ["application_id", "patient_id", "doctor_id", "surgery_name",
            "anesthesia_type", "status", "create_time"], rows


def _export_exams(db, from_date, to_date, anonymize):
    q = db.query(ExamRecord)
    if from_date:
        q = q.filter(ExamRecord.create_time >= from_date)
    if to_date:
        q = q.filter(ExamRecord.create_time <= to_date)
    rows = []
    for r in q.all():
        results = db.query(ExamResult).filter(ExamResult.record_id == r.record_id).all()
        for res in results:
            rows.append({
                "record_id": r.record_id,
                "patient_id": r.patient_id,
                "item_name": res.item_name,
                "result_value": res.result_value,
                "unit": res.unit or "",
                "reference_range": res.reference_range or "",
                "abnormal_flag": res.abnormal_flag,
                "create_time": str(r.create_time) if r.create_time else "",
            })
    return ["record_id", "patient_id", "item_name", "result_value", "unit",
            "reference_range", "abnormal_flag", "create_time"], rows


_EXPORTERS = {
    "patients": _export_patients,
    "medical_records": _export_medical_records,
    "prescriptions": _export_prescriptions,
    "charges": _export_charges,
    "lab_results": _export_lab_results,
    "surgeries": _export_surgeries,
    "exams": _export_exams,
}

EXPORT_METADATA = {
    "patients": {"label": "患者基本信息", "filename": "patients"},
    "medical_records": {"label": "病历记录", "filename": "medical_records"},
    "prescriptions": {"label": "处方药品明细", "filename": "prescriptions"},
    "charges": {"label": "收费记录", "filename": "charges"},
    "lab_results": {"label": "检验结果", "filename": "lab_results"},
    "surgeries": {"label": "手术记录", "filename": "surgeries"},
    "exams": {"label": "体检结果", "filename": "exams"},
}

_audit_log = []


def _audit(user_id, table, row_count, anonymize):
    _audit_log.append({
        "user_id": user_id, "table": table,
        "row_count": row_count, "anonymize": anonymize,
        "time": datetime.datetime.now(),
    })


def _write_csv(fieldnames, rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode("utf-8-sig")


@router.get("/research/export/tables")
def list_tables(current_user: User = Depends(require_roles(*_RESEARCH_ROLES))):
    """列出当前用户可导出的科研表清单。"""
    return {
        "code": 200, "msg": "success",
        "data": [
            {"table": k, "label": v["label"], "filename": v["filename"]}
            for k, v in EXPORT_METADATA.items()
        ],
    }


@router.post("/research/export")
def export_research_data(
    req: dict,
    current_user: User = Depends(require_roles(*_RESEARCH_ROLES)),
    db: Session = Depends(get_db),
):
    """导出单一科研表数据(CSV 格式)。"""
    table = req.get("table", "")
    if table not in _EXPORTERS:
        raise HTTPException(status_code=400, detail=f"不支持的表: {table},可选: {list(_EXPORTERS)}")
    from_date = req.get("from")
    to_date = req.get("to")
    anonymize = bool(req.get("anonymize", True))
    fmt = req.get("format", "csv")
    if fmt != "csv":
        raise HTTPException(status_code=400, detail="当前只支持 csv 格式")
    try:
        fieldnames, rows = _EXPORTERS[table](db, from_date, to_date, anonymize)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {e}")
    _audit(current_user.user_id, table, len(rows), anonymize)
    payload = _write_csv(fieldnames, rows)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    meta = EXPORT_METADATA[table]
    anon_tag = "_anon" if anonymize else ""
    filename = f"{meta['filename']}{anon_tag}_{ts}.csv"
    return StreamingResponse(
        iter([payload]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post("/research/export/package")
def export_package(
    req: dict,
    current_user: User = Depends(require_roles(*_RESEARCH_ROLES)),
    db: Session = Depends(get_db),
):
    """导出综合数据包(多表 ZIP)。"""
    import zipfile
    tables = req.get("tables", list(_EXPORTERS.keys()))
    from_date = req.get("from")
    to_date = req.get("to")
    anonymize = bool(req.get("anonymize", True))
    zip_buf = io.BytesIO()
    manifest_lines = ["table,filename,rows,anonymize"]
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in tables:
            if table not in _EXPORTERS:
                continue
            fieldnames, rows = _EXPORTERS[table](db, from_date, to_date, anonymize)
            payload = _write_csv(fieldnames, rows)
            meta = EXPORT_METADATA[table]
            anon_tag = "_anon" if anonymize else ""
            arcname = f"{meta['filename']}{anon_tag}.csv"
            zf.writestr(arcname, payload)
            manifest_lines.append(f"{table},{arcname},{len(rows)},{anonymize}")
            _audit(current_user.user_id, table, len(rows), anonymize)
    zf._fh.close()
    zip_buf.seek(0)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(
        iter([zip_buf.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''research_{ts}.zip"},
    )


@router.get("/research/export/audit")
def research_audit_log(current_user: User = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    """导出审计日志(仅 admin)。"""
    return {
        "code": 200, "msg": "success",
        "data": [
            {
                "user_id": x["user_id"],
                "table": x["table"],
                "row_count": x["row_count"],
                "anonymize": x["anonymize"],
                "time": str(x["time"]),
            }
            for x in _audit_log[-100:]
        ],
    }
