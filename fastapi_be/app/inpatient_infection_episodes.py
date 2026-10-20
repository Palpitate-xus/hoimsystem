"""Current doctor assertions about explicit infection episodes, not sepsis diagnosis."""

import json
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, field_validator, model_validator

from app.inpatient_infection_models import InpatientInfectionEpisodeSource
from app.inpatient_laboratory import hash_content
from app.inpatient_observations import explicit_utc
from app.inpatient_support_common import CanonicalId, HashText, SourceDefinition, StrictInput, UtcText


class EvidenceReference(StrictInput):
    kind: Literal["lab_source", "diagnosis_review"]
    source_id: CanonicalId
    expected_content_hash: HashText


class InfectionEpisodePayload(StrictInput):
    infection_status: Literal["suspected", "documented", "not_suspected", "unknown"]
    clinical_scope_start_at: UtcText
    clinical_scope_end_at: UtcText | None
    first_suspected_at: UtcText | None
    onset_at: UtcText | None
    onset_time_basis: Literal["explicit_clinician_verified_utc", "unknown"]
    onset_basis_note: str = Field(min_length=20, max_length=1000)
    infection_basis_note: str = Field(min_length=20, max_length=1000)
    evidence_refs: list[EvidenceReference] = Field(max_length=16)
    note: str = Field(max_length=1000)

    @field_validator("onset_basis_note", "infection_basis_note")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 20:
            raise ValueError("感染范围与发作时间依据须分别提供至少20字有效内容")
        return value

    @model_validator(mode="after")
    def actual_known_scope(self):
        if self.clinical_scope_end_at is not None and explicit_utc(self.clinical_scope_end_at) <= explicit_utc(self.clinical_scope_start_at):
            raise ValueError("明确临床范围终点须晚于起点；未知终点保留null")
        if (self.onset_at is not None) != (self.onset_time_basis == "explicit_clinician_verified_utc"):
            raise ValueError("未知发作时间须为null，明确时间须有对应时基核实")
        if len({(item.kind, item.source_id) for item in self.evidence_refs}) != len(self.evidence_refs):
            raise ValueError("同一原证据不能重复选择")
        return self


def diagnosis_evidence(db, patient_id, admission_id, identifier):
    from app.ai.governance import digest, encode_json
    from app.diagnosis_review import is_signed, source_facts
    from app.models import ClinicalDiagnosisReview, StructuredMedicalRecord

    review = db.query(ClinicalDiagnosisReview).filter_by(review_id=identifier).populate_existing().one_or_none()
    if review is None or review.source_kind != "structured" or review.patient_id != patient_id or review.encounter_ref != admission_id:
        raise HTTPException(409, "感染证据须为同患者原住院的明确已签诊断复核原件")
    original = db.query(StructuredMedicalRecord).filter_by(record_id=review.source_id, patient_id=patient_id, admission_id=admission_id).populate_existing().one_or_none()
    latest = db.query(ClinicalDiagnosisReview).filter_by(source_kind=review.source_kind, source_id=review.source_id).order_by(ClinicalDiagnosisReview.revision.desc()).populate_existing().first()
    if original is None or latest is None or latest.review_id != review.review_id or not is_signed(original) or digest(source_facts(original)) != review.source_hash:
        raise HTTPException(409, "原诊断病历、签名或最新复核已变化，不能继续作为当前感染证据")
    facts = json.loads(
        encode_json(
            {
                "review": {column.name: getattr(review, column.name) for column in review.__table__.columns},
                "original": {column.name: getattr(original, column.name) for column in original.__table__.columns},
            }
        )
    )
    frozen = {
        "review_id": review.review_id,
        "patient_id": patient_id,
        "admission_id": admission_id,
        "schema_version": "diagnosis_review_evidence_v1",
        "time_basis": "legacy_naive_unknown_not_historical_availability",
        "facts": facts,
    }
    content_hash = hash_content(frozen)
    return {**frozen, "content_hash": content_hash, "source_id": f"diagnosis_review:{review.review_id}:{content_hash[:12]}"}


def evidence_current(db, patient_id, admission_id, reference):
    from app.inpatient_laboratory import source_current
    from app.models import InpatientLabSource

    if reference["kind"] == "lab_source":
        row = db.query(InpatientLabSource).filter_by(lab_source_id=reference["source_id"]).populate_existing().one_or_none()
        source = source_current(db, row)
        if source["patient_id"] != patient_id or source["admission_id"] != admission_id or source.get("status") != "active" or source.get("eligible") is False:
            raise HTTPException(409, "感染证据须为当前有效的同患者原住院检验原件")
    else:
        source = diagnosis_evidence(db, patient_id, admission_id, reference["source_id"])
    if source["content_hash"] != reference["expected_content_hash"]:
        raise HTTPException(409, "所选感染证据原件摘要已变化")
    return source


def prepare_episode(db, patient_id, admission_id, payload, recorded_at):
    typed = InfectionEpisodePayload.model_validate(payload)
    for field in ("clinical_scope_start_at", "clinical_scope_end_at", "first_suspected_at", "onset_at"):
        value = getattr(typed, field)
        if value is not None and explicit_utc(value) > recorded_at:
            raise HTTPException(422, "已核实临床范围及发作/疑似时刻不能延伸到本次系统登记以后")
    evidence = [evidence_current(db, patient_id, admission_id, item.model_dump(mode="json")) for item in typed.evidence_refs]
    for source in evidence:
        if source.get("schema_version") != "diagnosis_review_evidence_v1" and any(explicit_utc(source[key]) > recorded_at for key in ("collected_at_utc", "registered_at", "available_at")):
            raise HTTPException(409, "原感染声明不能引用晚于其系统登记时刻才观察或可用的检验原件")
    return explicit_utc(typed.onset_at) if typed.onset_at is not None else None, {"evidence": evidence}


def evidence_candidates(db, patient_id, admission_id, kind, page=1, page_size=20):
    from app.inpatient_laboratory import source_current
    from app.models import ClinicalDiagnosisReview, InpatientLabSource

    if kind == "lab_source":
        query = (
            db.query(InpatientLabSource)
            .filter_by(patient_id=patient_id, admission_id=admission_id, status="active")
            .order_by(InpatientLabSource.registered_at.desc(), InpatientLabSource.lab_source_id)
        )
    else:
        query = db.query(ClinicalDiagnosisReview).filter_by(patient_id=patient_id, encounter_ref=admission_id, source_kind="structured").order_by(ClinicalDiagnosisReview.review_id)
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for row in rows:
        identifier = row.lab_source_id if kind == "lab_source" else row.review_id
        try:
            source = source_current(db, row) if kind == "lab_source" else diagnosis_evidence(db, patient_id, admission_id, identifier)
            item = {"kind": kind, "source_id": identifier, "expected_content_hash": source["content_hash"], "source_snapshot": source, "eligible": True, "exclusion_reasons": []}
        except HTTPException:
            item = {"kind": kind, "source_id": identifier, "expected_content_hash": None, "source_snapshot": None, "eligible": False, "exclusion_reasons": ["original_not_current"]}
        items.append(item)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


DEFINITIONS = [SourceDefinition("infection_episode", "infection_episode_v1", "infection_episode", InpatientInfectionEpisodeSource, InfectionEpisodePayload, True, prepare_episode)]
