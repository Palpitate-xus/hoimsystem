import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    Admission,
    Department,
    Doctor,
    MedicalRecordQuality,
    MedicalRecordTemplate,
    Patient,
    ProgressNote,
    StructuredMedicalRecord,
    User,
    WardRound,
)
from app.schemas import (
    MedicalRecordQualityCheckRequest,
    MedicalRecordTemplateCreateRequest,
    MedicalRecordTemplateUpdateRequest,
    ProgressNoteCreateRequest,
    StructuredMedicalRecordCreateRequest,
    StructuredMedicalRecordUpdateRequest,
    WardRoundCreateRequest,
)

router = APIRouter()


@router.get("/emrTemplate/getList")
def get_template_list(category: str | None = None, department_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(MedicalRecordTemplate).filter(MedicalRecordTemplate.status == 0)
    if category:
        query = query.filter(MedicalRecordTemplate.category == category)
    if department_id:
        query = query.filter(MedicalRecordTemplate.department_id == department_id)
    templates = query.all()
    data = []
    for item in templates:
        data.append(
            {
                "template_id": item.template_id,
                "name": item.name,
                "category": item.category,
                "category_text": {"admission": "入院记录", "progress": "病程记录", "discharge": "出院记录"}.get(item.category, item.category),
                "department_id": item.department_id,
                "department_name": item.department.name if item.department else "通用",
                "is_default": item.is_default,
                "status": item.status,
                "create_time": str(item.create_time) if item.create_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/emrTemplate/create")
def create_template(req: MedicalRecordTemplateCreateRequest, db: Session = Depends(get_db)):
    template = MedicalRecordTemplate(
        name=req.name,
        category=req.category,
        content=req.content,
        department_id=req.department_id,
        is_default=req.is_default,
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(template)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/emrTemplate/update")
def update_template(req: MedicalRecordTemplateUpdateRequest, db: Session = Depends(get_db)):
    template = db.query(MedicalRecordTemplate).filter(MedicalRecordTemplate.template_id == req.template_id).first()
    if not template:
        return {"code": 500, "msg": "模板不存在"}
    if req.name is not None:
        template.name = req.name
    if req.category is not None:
        template.category = req.category
    if req.content is not None:
        template.content = req.content
    if req.department_id is not None:
        template.department_id = req.department_id
    if req.is_default is not None:
        template.is_default = req.is_default
    if req.status is not None:
        template.status = req.status
    db.add(template)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/emrTemplate/delete")
def delete_template(req: dict, db: Session = Depends(get_db)):
    template = db.query(MedicalRecordTemplate).filter(MedicalRecordTemplate.template_id == req.get("template_id")).first()
    if not template:
        return {"code": 500, "msg": "模板不存在"}
    template.status = 1
    db.add(template)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/emrTemplate/detail")
def get_template_detail(template_id: int, db: Session = Depends(get_db)):
    template = db.query(MedicalRecordTemplate).filter(MedicalRecordTemplate.template_id == template_id).first()
    if not template:
        return {"code": 500, "msg": "模板不存在"}
    return {"code": 200, "msg": "success", "data": {"template_id": template.template_id, "name": template.name, "category": template.category, "content": template.content or "", "department_id": template.department_id}}


@router.get("/structuredMedicalRecord/getList")
def get_structured_record_list(admission_id: str | None = None, patient_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(StructuredMedicalRecord).order_by(StructuredMedicalRecord.create_time.desc())
    if admission_id:
        query = query.filter(StructuredMedicalRecord.admission_id == admission_id)
    if patient_id:
        query = query.filter(StructuredMedicalRecord.patient_id == patient_id)
    records = query.all()
    type_map = ["入院记录", "首次病程", "日常病程", "出院记录"]
    status_map = ["草稿", "已完成", "已归档"]
    data = []
    for item in records:
        data.append(
            {
                "record_id": item.record_id,
                "admission_id": item.admission_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "doctor_id": item.doctor_id,
                "doctor_name": item.doctor.name if item.doctor else "",
                "record_type": item.record_type,
                "record_type_text": type_map[item.record_type] if item.record_type is not None and item.record_type < len(type_map) else "",
                "chief_complaint": item.chief_complaint or "",
                "diagnosis": item.diagnosis or "",
                "status": item.status,
                "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
                "sign_time": str(item.sign_time) if item.sign_time else "",
                "create_time": str(item.create_time) if item.create_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/structuredMedicalRecord/create")
def create_structured_record(req: StructuredMedicalRecordCreateRequest, db: Session = Depends(get_db)):
    record = StructuredMedicalRecord(
        admission_id=req.admission_id,
        patient_id=req.patient_id,
        doctor_id=req.doctor_id,
        record_type=req.record_type,
        chief_complaint=req.chief_complaint,
        present_illness=req.present_illness,
        past_history=req.past_history,
        personal_history=req.personal_history,
        family_history=req.family_history,
        physical_exam=req.physical_exam,
        auxiliary_exam=req.auxiliary_exam,
        diagnosis=req.diagnosis,
        treatment_plan=req.treatment_plan,
        status=0,
        create_time=datetime.datetime.now(),
    )
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success", "data": {"record_id": record.record_id}}


@router.get("/structuredMedicalRecord/detail")
def get_structured_record_detail(record_id: str, db: Session = Depends(get_db)):
    item = db.query(StructuredMedicalRecord).filter(StructuredMedicalRecord.record_id == record_id).first()
    if not item:
        return {"code": 500, "msg": "病历不存在"}
    type_map = ["入院记录", "首次病程", "日常病程", "出院记录"]
    status_map = ["草稿", "已完成", "已归档"]
    data = {
        "record_id": item.record_id,
        "admission_id": item.admission_id,
        "patient_id": item.patient_id,
        "patient_name": item.patient.name if item.patient else "",
        "doctor_id": item.doctor_id,
        "doctor_name": item.doctor.name if item.doctor else "",
        "record_type": item.record_type,
        "record_type_text": type_map[item.record_type] if item.record_type is not None and item.record_type < len(type_map) else "",
        "chief_complaint": item.chief_complaint or "",
        "present_illness": item.present_illness or "",
        "past_history": item.past_history or "",
        "personal_history": item.personal_history or "",
        "family_history": item.family_history or "",
        "physical_exam": item.physical_exam or "",
        "auxiliary_exam": item.auxiliary_exam or "",
        "diagnosis": item.diagnosis or "",
        "treatment_plan": item.treatment_plan or "",
        "status": item.status,
        "status_text": status_map[item.status] if item.status is not None and item.status < len(status_map) else "",
        "sign_time": str(item.sign_time) if item.sign_time else "",
        "create_time": str(item.create_time) if item.create_time else "",
        "update_time": str(item.update_time) if item.update_time else "",
    }
    return {"code": 200, "msg": "success", "data": data}


@router.post("/structuredMedicalRecord/update")
def update_structured_record(req: StructuredMedicalRecordUpdateRequest, db: Session = Depends(get_db)):
    record = db.query(StructuredMedicalRecord).filter(StructuredMedicalRecord.record_id == req.record_id).first()
    if not record:
        return {"code": 500, "msg": "病历不存在"}
    if req.chief_complaint is not None:
        record.chief_complaint = req.chief_complaint
    if req.present_illness is not None:
        record.present_illness = req.present_illness
    if req.past_history is not None:
        record.past_history = req.past_history
    if req.personal_history is not None:
        record.personal_history = req.personal_history
    if req.family_history is not None:
        record.family_history = req.family_history
    if req.physical_exam is not None:
        record.physical_exam = req.physical_exam
    if req.auxiliary_exam is not None:
        record.auxiliary_exam = req.auxiliary_exam
    if req.diagnosis is not None:
        record.diagnosis = req.diagnosis
    if req.treatment_plan is not None:
        record.treatment_plan = req.treatment_plan
    if req.status is not None:
        record.status = req.status
    record.update_time = datetime.datetime.now()
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/structuredMedicalRecord/sign")
def sign_medical_record(req: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    record = db.query(StructuredMedicalRecord).filter(StructuredMedicalRecord.record_id == req.get("record_id")).first()
    if not record:
        return {"code": 500, "msg": "病历不存在"}
    record.status = 1
    record.sign_time = datetime.datetime.now()
    db.add(record)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/structuredMedicalRecord/delete")
def delete_structured_record(req: dict, db: Session = Depends(get_db)):
    record = db.query(StructuredMedicalRecord).filter(StructuredMedicalRecord.record_id == req.get("record_id")).first()
    if not record:
        return {"code": 500, "msg": "病历不存在"}
    db.delete(record)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/progressNote/getList")
def get_progress_note_list(admission_id: str, db: Session = Depends(get_db)):
    notes = db.query(ProgressNote).filter(ProgressNote.admission_id == admission_id).order_by(ProgressNote.note_date.desc()).all()
    data = []
    for item in notes:
        data.append(
            {
                "note_id": item.note_id,
                "admission_id": item.admission_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "doctor_id": item.doctor_id,
                "doctor_name": item.doctor.name if item.doctor else "",
                "note_date": str(item.note_date) if item.note_date else "",
                "content": item.content,
                "record_time": str(item.record_time) if item.record_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/progressNote/create")
def create_progress_note(req: ProgressNoteCreateRequest, db: Session = Depends(get_db)):
    try:
        note_date = datetime.datetime.strptime(req.note_date, "%Y-%m-%d").date()
    except ValueError:
        note_date = datetime.datetime.now().date()
    note = ProgressNote(
        admission_id=req.admission_id,
        patient_id=req.patient_id,
        doctor_id=req.doctor_id,
        note_date=note_date,
        content=req.content,
        record_time=datetime.datetime.now(),
        create_time=datetime.datetime.now(),
    )
    db.add(note)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/progressNote/delete")
def delete_progress_note(req: dict, db: Session = Depends(get_db)):
    note = db.query(ProgressNote).filter(ProgressNote.note_id == req.get("note_id")).first()
    if not note:
        return {"code": 500, "msg": "记录不存在"}
    db.delete(note)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/wardRound/getList")
def get_ward_round_list(admission_id: str, db: Session = Depends(get_db)):
    rounds = db.query(WardRound).filter(WardRound.admission_id == admission_id).order_by(WardRound.round_time.desc()).all()
    type_map = ["主任医师查房", "副主任医师查房", "主治医师查房"]
    data = []
    for item in rounds:
        data.append(
            {
                "round_id": item.round_id,
                "admission_id": item.admission_id,
                "patient_id": item.patient_id,
                "patient_name": item.patient.name if item.patient else "",
                "doctor_id": item.doctor_id,
                "doctor_name": item.doctor.name if item.doctor else "",
                "round_type": item.round_type,
                "round_type_text": type_map[item.round_type] if item.round_type is not None and item.round_type < len(type_map) else "",
                "content": item.content,
                "round_time": str(item.round_time) if item.round_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/wardRound/create")
def create_ward_round(req: WardRoundCreateRequest, db: Session = Depends(get_db)):
    round_time = datetime.datetime.now()
    if req.round_time:
        try:
            round_time = datetime.datetime.strptime(req.round_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    ward_round = WardRound(
        admission_id=req.admission_id,
        patient_id=req.patient_id,
        doctor_id=req.doctor_id,
        round_type=req.round_type,
        content=req.content,
        round_time=round_time,
        create_time=datetime.datetime.now(),
    )
    db.add(ward_round)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.post("/wardRound/delete")
def delete_ward_round(req: dict, db: Session = Depends(get_db)):
    ward_round = db.query(WardRound).filter(WardRound.round_id == req.get("round_id")).first()
    if not ward_round:
        return {"code": 500, "msg": "记录不存在"}
    db.delete(ward_round)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/medicalRecordQuality/getList")
def get_quality_list(admission_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(MedicalRecordQuality).order_by(MedicalRecordQuality.check_time.desc())
    if admission_id:
        query = query.filter(MedicalRecordQuality.admission_id == admission_id)
    checks = query.all()
    result_map = ["通过", "警告", "错误"]
    data = []
    for item in checks:
        data.append(
            {
                "quality_id": item.quality_id,
                "admission_id": item.admission_id,
                "record_id": item.record_id,
                "check_item": item.check_item,
                "check_result": item.check_result,
                "check_result_text": result_map[item.check_result] if item.check_result is not None and item.check_result < len(result_map) else "",
                "issue": item.issue or "",
                "score": item.score,
                "checker_name": item.checker.name if item.checker else "",
                "check_time": str(item.check_time) if item.check_time else "",
            }
        )
    return {"code": 200, "msg": "success", "data": data}


@router.post("/medicalRecordQuality/check")
def quality_check(req: MedicalRecordQualityCheckRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    check = MedicalRecordQuality(
        admission_id=req.admission_id,
        record_id=req.record_id,
        check_item=req.check_item,
        check_result=req.check_result,
        issue=req.issue,
        score=req.score,
        checker_id=current_user.user_id,
        check_time=datetime.datetime.now(),
    )
    db.add(check)
    db.commit()
    return {"code": 200, "msg": "success"}


@router.get("/medicalRecordQuality/summary")
def get_quality_summary(db: Session = Depends(get_db)):
    total = db.query(StructuredMedicalRecord).count()
    signed = db.query(StructuredMedicalRecord).filter(StructuredMedicalRecord.status == 1).count()
    archived = db.query(StructuredMedicalRecord).filter(StructuredMedicalRecord.status == 2).count()
    issues = db.query(MedicalRecordQuality).filter(MedicalRecordQuality.check_result == 2).count()
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "total_records": total,
            "signed_records": signed,
            "archived_records": archived,
            "issue_count": issues,
            "sign_rate": round(signed / total * 100, 1) if total > 0 else 0,
        },
    }
