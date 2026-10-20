"""Role-scoped business entry points for authorized AI tasks and human review."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.ai.catalog import FEATURES
from app.ai.context import accessible_patients, authorize_patient, context_metadata, patient_snapshot
from app.ai.governance import audit, describe_config
from app.ai.models import AIFeatureConfig, AIFeedback, AIRun, utcnow
from app.ai.runtime import authorize_run, authorized_feature, create_run, describe_run
from app.ai.schemas import FeedbackWrite, RunRequest
from app.database import get_db
from app.dependencies import get_current_user
from app.models import Admission, Prescription, Registration, User

router = APIRouter(tags=["AI 业务助手"])


@router.get("/ai/features")
def available_features(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Show authorized capabilities without disclosing provider configuration."""
    configs = {item.feature_key: item for item in db.query(AIFeatureConfig).all()}
    data = []
    for spec in FEATURES:
        try:
            authorized_feature(db, user, spec.key)
        except HTTPException as exc:
            if exc.status_code == 403:
                continue
            raise
        data.append(describe_config(db, spec, configs.get(spec.key)))
    return {"code": 200, "msg": "success", "data": data}


@router.get("/ai/patients")
def patient_options(feature_key: str, keyword: str = Query("", max_length=100), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Offer only patients this user may select for the specified capability."""
    spec, _ = authorized_feature(db, user, feature_key)
    if spec.scope != "patient":
        raise HTTPException(422, "该能力无需选择患者")
    items = accessible_patients(db, user, spec, keyword)
    return {"code": 200, "msg": "success", "data": [{"patient_id": item.patient_id, "label": f"{item.name} · #{item.patient_id}"} for item in items]}


@router.get("/ai/encounters")
def encounter_options(feature_key: str, patient_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Offer authorized encounters without widening access to another doctor's current case."""
    spec, _ = authorized_feature(db, user, feature_key)
    authorize_patient(db, user, patient_id, spec.category)
    items = []
    for model, id_field, time_field, label in [(Registration, "registration_uuid", "time", "门诊"), (Admission, "admission_id", "admission_time", "住院")]:
        for row in db.query(model).filter_by(patient_id=patient_id).order_by(getattr(model, time_field).desc()).limit(20).all():
            reference = getattr(row, id_field)
            try:
                authorize_patient(db, user, patient_id, spec.category, reference)
            except HTTPException as exc:
                if exc.status_code == 403:
                    continue
                raise
            items.append({"encounter_ref": reference, "label": f"{label} · {getattr(row, time_field)}", "kind": "outpatient" if model is Registration else "inpatient"})
    return {"code": 200, "msg": "success", "data": items}


@router.get("/ai/prescriptions")
def prescription_options(feature_key: str, patient_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Select a prescription for review without exposing another patient's records."""
    spec, _ = authorized_feature(db, user, feature_key)
    if spec.category != "pharmacy":
        raise HTTPException(422, "该能力无需选择处方")
    authorize_patient(db, user, patient_id, spec.category)
    items = db.query(Prescription).filter_by(patient_id=patient_id).order_by(Prescription.create_time.desc()).limit(30).all()
    return {"code": 200, "msg": "success", "data": [{"prescription_id": item.prescription_id, "label": f"{item.create_time} · {item.prescription_id[:8]}", "status": item.status} for item in items]}


@router.get("/ai/context")
def inspect_context(
    feature_key: str,
    patient_id: int,
    encounter_ref: str | None = None,
    record_id: str | None = Query(None, max_length=50),
    structured_record_id: str | None = Query(None, max_length=50),
    prescription_id: str | None = Query(None, max_length=50),
    lab_result_id: str | None = Query(None, max_length=50),
    imaging_report_id: str | None = Query(None, max_length=50),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Inspect the patient's authorized facts and missing information before submission."""
    spec, _ = authorized_feature(db, user, feature_key)
    if spec.scope != "patient":
        raise HTTPException(422, "该能力无需加载患者临床资料")
    references = {"record_id": record_id, "structured_record_id": structured_record_id, "prescription_id": prescription_id, "lab_result_id": lab_result_id, "imaging_report_id": imaging_report_id}
    bundle = patient_snapshot(db, user, spec, patient_id, encounter_ref, references)
    return {"code": 200, "msg": "success", "data": {"context": bundle.data, "metadata": context_metadata(bundle)}}


@router.post("/ai/runs")
def submit_run(req: RunRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Queue durable work; a separately deployed worker performs inference."""
    run = create_run(db, user, req)
    return {"code": 200, "msg": "任务已排队", "data": describe_run(run, False)}


@router.get("/ai/runs")
def list_runs(feature_key: str | None = None, limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """List own tasks; super-admins can inspect global execution history."""
    query = db.query(AIRun)
    if user.user_role != "super_admin":
        query = query.filter_by(requested_by=user.user_id)
    if feature_key:
        authorized_feature(db, user, feature_key)
        query = query.filter_by(feature_key=feature_key)
    data = []
    for item in query.order_by(AIRun.create_time.desc()).limit(limit).all():
        try:
            authorize_run(db, user, item)
        except HTTPException as exc:
            if exc.status_code == 403:
                continue
            raise
        data.append(describe_run(item, False))
    return {"code": 200, "msg": "success", "data": data}


@router.get("/ai/runs/{run_id}")
def run_detail(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Recheck patient access before exposing a stored result or evidence."""
    run = db.get(AIRun, run_id)
    if run is None:
        raise HTTPException(404, "AI 任务不存在")
    authorize_run(db, user, run)
    return {"code": 200, "msg": "success", "data": describe_run(run)}


@router.post("/ai/runs/{run_id}/cancel")
def cancel_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Stop accepting a result; an already sent provider call may still finish."""
    run = db.get(AIRun, run_id)
    if run is None:
        raise HTTPException(404, "AI 任务不存在")
    authorize_run(db, user, run)
    if run.status not in {"queued", "running"}:
        raise HTTPException(409, "任务已结束")
    changed = db.query(AIRun).filter(AIRun.run_id == run_id, AIRun.status.in_(["queued", "running"])).update({"status": "cancelled", "finish_time": utcnow()}, synchronize_session=False)
    if changed != 1:
        db.rollback()
        raise HTTPException(409, "任务状态已改变")
    audit(db, user.user_id, "run.cancel", run_id)
    db.commit()
    return {"code": 200, "msg": "任务结果已取消接收"}


@router.post("/ai/runs/{run_id}/feedback")
def review_result(run_id: str, req: FeedbackWrite, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Append review without editing clinical records, orders or prescriptions."""
    run = db.get(AIRun, run_id)
    if run is None:
        raise HTTPException(404, "AI 任务不存在")
    authorize_run(db, user, run)
    if run.status != "succeeded":
        raise HTTPException(409, "只能复核已成功生成的建议")
    if req.outcome == "modified" and len(req.comment) < 3:
        raise HTTPException(422, "请说明修改内容")
    item = AIFeedback(run_id=run_id, reviewer_id=user.user_id, outcome=req.outcome, comment=req.comment)
    db.add(item)
    audit(db, user.user_id, "run.feedback", run_id, {"outcome": req.outcome})
    db.commit()
    return {"code": 200, "msg": "复核反馈已记录", "data": {"feedback_id": item.feedback_id}}
