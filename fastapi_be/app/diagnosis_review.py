"""Explicit physician diagnosis verification with immutable source snapshots."""

import datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.governance import digest
from app.models import ClinicalDiagnosisReview, MedicalRecord, StructuredMedicalRecord, User


class DiagnosisReviewWrite(BaseModel):
    """Verify exactly the record version the physician inspected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_kind: Literal["outpatient", "structured"]
    source_id: str = Field(min_length=1, max_length=36)
    source_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    expected_revision: int = Field(ge=0)
    certainty: Literal["confirmed", "suspected", "excluded", "unknown"]
    reason: str = Field(min_length=5, max_length=1000)


def source_facts(record) -> dict:
    """Signing status and encounter identity participate in invalidation, alongside raw text."""
    outpatient = isinstance(record, MedicalRecord)
    return {
        "source_kind": "outpatient" if outpatient else "structured",
        "source_id": record.medical_record_id if outpatient else record.record_id,
        "patient_id": record.patient_id,
        "encounter_ref": record.registration_uuid if outpatient else record.admission_id,
        "diagnosis_text": record.result if outpatient else record.diagnosis,
        "status": record.status,
        "sign_time": record.sign_time,
    }


def is_signed(record) -> bool:
    return record.status == 1 if isinstance(record, MedicalRecord) else record.status in {1, 2} and record.sign_time is not None


def latest_reviews(db: Session, patient_id: int, source_ids: list[str] | None = None) -> dict:
    """Fetch the latest assertion for each source without discarding older audit versions."""
    query = db.query(ClinicalDiagnosisReview.source_kind, ClinicalDiagnosisReview.source_id, func.max(ClinicalDiagnosisReview.revision).label("revision")).filter_by(patient_id=patient_id)
    if source_ids is not None:
        if not source_ids:
            return {}
        query = query.filter(ClinicalDiagnosisReview.source_id.in_(source_ids))
    newest = query.group_by(ClinicalDiagnosisReview.source_kind, ClinicalDiagnosisReview.source_id).subquery()
    rows = (
        db.query(ClinicalDiagnosisReview)
        .join(newest, and_(ClinicalDiagnosisReview.source_kind == newest.c.source_kind, ClinicalDiagnosisReview.source_id == newest.c.source_id, ClinicalDiagnosisReview.revision == newest.c.revision))
        .all()
    )
    return {(row.source_kind, row.source_id): row for row in rows}


def review_state(record, reviews: dict) -> tuple[str, ClinicalDiagnosisReview | None]:
    """A signed narrative alone is never a physician confirmation of every diagnosis."""
    facts = source_facts(record)
    review = reviews.get((facts["source_kind"], facts["source_id"]))
    if review is None:
        return "unknown", None
    if not is_signed(record) or review.source_hash != digest(facts):
        return "stale", review
    return review.certainty, review


def load_review_source(db: Session, user: User, source_kind: str, source_id: str):
    """Only the record's responsible physician can assert its diagnostic certainty."""
    if source_kind not in {"outpatient", "structured"}:
        raise HTTPException(422, "不支持的诊断来源")
    model = MedicalRecord if source_kind == "outpatient" else StructuredMedicalRecord
    primary_key = model.medical_record_id if source_kind == "outpatient" else model.record_id
    record = db.query(model).filter(primary_key == source_id).with_for_update().first()
    if record is None:
        raise HTTPException(404, "诊断来源病历不存在")
    if not record.doctor or record.doctor.user_id != user.user_id or user.user_role not in {"doctor", "director"}:
        raise HTTPException(403, "只能由该病历责任医生复核诊断")
    return record


def describe_review_source(db: Session, record) -> dict:
    facts = source_facts(record)
    reviews = latest_reviews(db, record.patient_id, [facts["source_id"]])
    certainty, latest = review_state(record, reviews)
    return {
        **facts,
        "source_hash": digest(facts),
        "signed": is_signed(record),
        "certainty": certainty,
        "revision": latest.revision if latest else 0,
        "history": [
            {name: getattr(item, name) for name in ("review_id", "certainty", "reason", "revision", "reviewed_by", "reviewed_at")}
            for item in db.query(ClinicalDiagnosisReview).filter_by(source_kind=facts["source_kind"], source_id=facts["source_id"]).order_by(ClinicalDiagnosisReview.revision.desc()).limit(20).all()
        ],
    }


def record_diagnosis_review(db: Session, user: User, req: DiagnosisReviewWrite) -> ClinicalDiagnosisReview:
    record = load_review_source(db, user, req.source_kind, req.source_id)
    facts = source_facts(record)
    if not is_signed(record) or not facts["diagnosis_text"]:
        raise HTTPException(409, "诊断内容需已填写且病历完成签名后才能复核")
    if digest(facts) != req.source_hash:
        raise HTTPException(409, "病历内容或状态已经改变，请重新查看后复核")
    latest = latest_reviews(db, record.patient_id, [req.source_id]).get((req.source_kind, req.source_id))
    if req.expected_revision != (latest.revision if latest else 0):
        raise HTTPException(409, "诊断复核版本已改变，请刷新")
    review = ClinicalDiagnosisReview(
        source_kind=req.source_kind,
        source_id=req.source_id,
        patient_id=record.patient_id,
        encounter_ref=facts["encounter_ref"],
        diagnosis_text=facts["diagnosis_text"],
        source_hash=req.source_hash,
        certainty=req.certainty,
        reason=req.reason,
        revision=req.expected_revision + 1,
        reviewed_by=user.user_id,
        reviewed_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "诊断复核版本已改变，请刷新") from exc
    return review
