"""Source-bound, manually reviewed feedback versions; no automated claim of anonymization."""

import datetime
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import and_, case, func, or_

from app.ai.context import minimize_identifiers
from app.ai.governance import audit, digest, ensure_revision, flush_or_conflict
from app.ai.models import AIReviewExcerpt, utcnow
from app.models import Department, Doctor, MedicalRecord, Patient, Registration, Review


def review_department():
    return case((MedicalRecord.registration_uuid.is_not(None), Registration.department_id), else_=Doctor.department_id)


def verified_review_query(db, departments=None, start=None, end=None):
    query = (
        db.query(Review)
        .join(MedicalRecord, MedicalRecord.medical_record_id == Review.visit_id)
        .join(Doctor, Doctor.doctor_id == MedicalRecord.doctor_id)
        .join(Patient, Patient.patient_id == Review.patient_id)
        .outerjoin(Registration, Registration.registration_uuid == MedicalRecord.registration_uuid)
        .filter(
            Review.patient_id == MedicalRecord.patient_id,
            Review.doctor_id == MedicalRecord.doctor_id,
            or_(MedicalRecord.registration_uuid.is_(None), and_(Registration.patient_id == MedicalRecord.patient_id, Registration.doctor_id == MedicalRecord.doctor_id)),
        )
    )
    if departments is not None:
        query = query.filter(review_department().in_(departments))
    if start is not None:
        query = query.filter(Review.review_time >= datetime.datetime.combine(start, datetime.time.min))
    if end is not None:
        query = query.filter(Review.review_time < datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min))
    return query


@dataclass
class ReviewSource:
    review: Review
    visit: MedicalRecord
    doctor: Doctor
    patient: Patient
    registration: Registration | None

    @property
    def department_id(self):
        return self.registration.department_id if self.visit.registration_uuid is not None else self.doctor.department_id

    @property
    def fingerprint(self):
        return digest(
            {
                "review": {name: getattr(self.review, name) for name in ("review_id", "patient_id", "doctor_id", "visit_id", "score", "comment", "review_time")},
                "visit": {name: getattr(self.visit, name) for name in ("medical_record_id", "patient_id", "doctor_id", "registration_uuid")},
                "registration": {name: getattr(self.registration, name) for name in ("registration_uuid", "patient_id", "doctor_id", "department_id")} if self.registration else None,
                "department_id": self.department_id,
                "patient_identifiers": [self.patient.name, self.patient.identity, self.patient.phone, self.patient.address],
                "doctor_identifiers": [self.doctor.name, self.doctor.phone],
            }
        )

    def redact(self, value):
        text = minimize_identifiers(value or "", self.patient)
        for identifier in (self.doctor.name, self.doctor.phone):
            if identifier and len(identifier) >= 2:
                text = text.replace(identifier, "[已隐藏医务人员标识]")
        return text


def load_review_source(db, review_id):
    row = verified_review_query(db).filter(Review.review_id == review_id).with_entities(Review, MedicalRecord, Doctor, Patient, Registration).populate_existing().first()
    if row is None:
        raise HTTPException(409, "评价不存在，或其患者、医生、就诊关联已无法核实")
    source = ReviewSource(*row)
    if source.department_id is None or db.get(Department, source.department_id) is None:
        raise HTTPException(409, "原评价未取得可核实科室，不能发布脱敏摘录")
    return source


def describe_excerpt(item, *, include_text=False):
    result = {
        name: getattr(item, name)
        for name in (
            "excerpt_id",
            "review_id",
            "version",
            "department_id",
            "status",
            "revision",
            "create_time",
            "created_by",
            "reviewed_by",
            "reviewed_at",
            "retired_by",
            "retired_at",
        )
    }
    if include_text:
        result.update({name: getattr(item, name) for name in ("source_hash", "redacted_text", "text_hash", "change_note", "review_note", "privacy_checked", "faithfulness_checked")})
    return result


def source_state(db, item):
    try:
        source = load_review_source(db, item.review_id)
    except HTTPException:
        return "unavailable"
    return "current" if source.fingerprint == item.source_hash and source.department_id == item.department_id else "stale"


def create_excerpt(db, user, req):
    # All version writers lock the same original row before allocating or publishing.
    review = db.query(Review).filter_by(review_id=req.review_id).with_for_update().populate_existing().first()
    if review is None:
        raise HTTPException(404, "原评价不存在")
    source = load_review_source(db, req.review_id)
    if source.fingerprint != req.expected_source_hash:
        raise HTTPException(409, "原评价或关联已变化，请重新读取后整理脱敏稿")
    if not (source.review.comment or "").strip():
        raise HTTPException(409, "原评价没有评论文本，不能为其编写摘录")
    if source.redact(req.redacted_text) != req.redacted_text:
        raise HTTPException(422, "脱敏稿仍包含已知直接标识，请移除后重新保存")
    version = (db.query(func.max(AIReviewExcerpt.version)).filter_by(review_id=req.review_id).scalar() or 0) + 1
    item = AIReviewExcerpt(
        review_id=req.review_id,
        version=version,
        source_hash=source.fingerprint,
        department_id=source.department_id,
        redacted_text=req.redacted_text,
        text_hash=digest(req.redacted_text),
        change_note=req.change_note,
        created_by=user.user_id,
    )
    db.add(item)
    flush_or_conflict(db)
    audit(db, user.user_id, "review_excerpt.create", item.excerpt_id, {"review_id": req.review_id, "version": version, "source_hash": item.source_hash, "text_hash": item.text_hash})
    return item


def review_excerpt(db, user, excerpt_id, req):
    item = db.get(AIReviewExcerpt, excerpt_id)
    if item is None:
        raise HTTPException(404, "脱敏稿版本不存在")
    db.query(Review).filter_by(review_id=item.review_id).with_for_update().populate_existing().first()
    item = db.query(AIReviewExcerpt).filter_by(excerpt_id=excerpt_id).with_for_update().populate_existing().one()
    ensure_revision(item.revision, req.expected_revision)
    allowed = {"draft": {"published", "rejected", "retired"}, "published": {"retired"}}
    if req.status not in allowed.get(item.status, set()):
        raise HTTPException(409, "该审核状态不能迁移；修改文本请另存新版本")
    retired = []
    if req.status == "published":
        if not req.privacy_checked or not req.faithfulness_checked:
            raise HTTPException(422, "发布前须明确确认已检查脱敏和原意保留")
        source = load_review_source(db, item.review_id)
        if source.fingerprint != item.source_hash or source.department_id != item.department_id:
            raise HTTPException(409, "原评价或科室关联已变化，此稿不能发布，请创建新版本")
        if digest(item.redacted_text) != item.text_hash or source.redact(item.redacted_text) != item.redacted_text:
            raise HTTPException(409, "稿件文本或标识检查已失效，请创建新版本")
        for previous in db.query(AIReviewExcerpt).filter(AIReviewExcerpt.review_id == item.review_id, AIReviewExcerpt.status == "published").all():
            previous.status = "retired"
            previous.revision += 1
            previous.retired_by, previous.retired_at = user.user_id, utcnow()
            retired.append(previous.excerpt_id)
        item.privacy_checked, item.faithfulness_checked = 1, 1
        item.reviewed_by, item.reviewed_at = user.user_id, utcnow()
    elif req.status == "retired":
        item.retired_by, item.retired_at = user.user_id, utcnow()
    else:
        item.reviewed_by, item.reviewed_at = user.user_id, utcnow()
    item.status, item.review_note = req.status, req.review_note
    item.revision += 1
    audit(db, user.user_id, "review_excerpt.review", item.excerpt_id, {"status": item.status, "revision": item.revision, "text_hash": item.text_hash, "retired_versions": retired})
    flush_or_conflict(db)
    return item
