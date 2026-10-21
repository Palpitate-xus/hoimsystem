"""Role-scoped business entry points for authorized AI tasks and human review."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import JSON, type_coerce
from sqlalchemy.orm import Session, defer

from app.ai.catalog import FEATURES
from app.ai.context import accessible_patients, authorize_patient, context_metadata, get_encounter, patient_snapshot
from app.ai.document_extraction_candidates import SaveDocumentCandidate
from app.ai.document_extraction_contract import DocumentExtractionRequest
from app.ai.ecg_assets import authorize_ecg_patient
from app.ai.governance import audit, describe_config, encode_json
from app.ai.image_assets import authorize_image_patient
from app.ai.knowledge import is_document_evidence
from app.ai.models import AIFeatureConfig, AIFeedback, AIRun, utcnow
from app.ai.operational_sources import operational_context, operational_options
from app.ai.pathway_knowledge import eligible_pathway_documents
from app.ai.pathway_sources import PATHWAY_SOURCE_FEATURES
from app.ai.runtime import authorize_run, authorized_feature, create_run, describe_run
from app.ai.schemas import ClinicalContextRequest, FeedbackWrite, OperationalContextRequest, RunRequest
from app.ai.service_sources import service_options
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user, require_roles
from app.models import Admission, ClinicalPathway, Prescription, Registration, User
from app.routers.inpatient_support import QueryPositiveInteger

# Evidence text must bypass the legacy response formatter that truncates timestamps.
router = APIRouter(tags=["AI 业务助手"], default_response_class=JSONResponse)


@router.post("/ai/document-extraction/context")
def inspect_document_extraction_context(req: DocumentExtractionRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Inspect one current complete original without contacting the model."""
    from app.ai import document_evidence_sources as sources
    from app.ai.document_extraction_context import extraction_context, public_payload

    user = sources.current_super(db, user)
    values = req.model_dump(mode="json", exclude_unset=True)
    bundle = extraction_context(db, user, values)
    preview = public_payload({"input": values, "context": bundle.data, "tools": {}, "evidence": bundle.evidence})
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "context": bundle.data,
            "metadata": context_metadata(bundle),
            "evidence": bundle.evidence,
            "document_original": sources.original_detail(db, user, req.document_original_id).model_dump(mode="json"),
            "model_preview": preview,
        },
    }


@router.post("/ai/runs/{run_id}/document-candidates")
def save_document_extraction_candidate(run_id: str, req: SaveDocumentCandidate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))) -> dict:
    """Save one explicitly selected real draft span; review/publication stay separate."""
    from app.ai.document_extraction_candidates import save_candidate

    record = save_candidate(db, user, run_id, req.ordinal)
    return {"code": 200, "msg": "已保存为未审核候选，尚未发布知识", "data": record.model_dump(mode="json")}


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


@router.get("/ai/service-options")
def hospital_service_options(feature_key: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Offer public hospital places or clinicians for the authorized service capability."""
    spec, _ = authorized_feature(db, user, feature_key)
    if spec.number == 72:
        raise HTTPException(422, "双原文版本核对只使用专用有限范围目录，不提供通用业务范围")
    data = operational_options(db, user, spec) if spec.scope == "hospital" else service_options(db, spec.number)
    return {"code": 200, "msg": "success", "data": data}


@router.post("/ai/operational-context")
def inspect_operational_context(req: OperationalContextRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Inspect the same scoped facts used by generation, without contacting a provider."""
    if req.feature_key == "feedback_analysis":
        from app.ai.satisfaction_context import selection
        from app.ai.satisfaction_runtime import current_actor

        selection(req.input)
        user = current_actor(db, user)
    spec, _ = authorized_feature(db, user, req.feature_key)
    if spec.scope != "hospital":
        raise HTTPException(422, "该功能不使用医院运营资料范围")
    if len(encode_json(req.input)) > settings.AI_MAX_INPUT_CHARS:
        raise HTTPException(422, "运营筛选输入超过允许长度")
    bundle = operational_context(db, user, spec, req.input)
    if len(encode_json({"context": bundle.data, "evidence": bundle.evidence, "input": req.input})) > settings.AI_MAX_CONTEXT_CHARS * 2:
        raise HTTPException(422, "运营资料超过任务上下文限制，请缩小日期、科室或品种范围")
    context = bundle.data
    if context.get("roster_binding"):
        from app.ai.roster_context import expand_context

        context = expand_context(db, context, user=user, current=True)
    if context.get("bed_binding"):
        from app.ai.bed_context import expand_context

        context = expand_context(db, context, user=user, current=True)
    if context.get("surgery_binding"):
        from app.ai.surgery_context import expand_context

        context = expand_context(db, context, user=user, current=True)
    if context.get("inventory_binding"):
        from app.ai.inventory_context import expand_context

        context = expand_context(db, context, user=user, current=True)
    if context.get("supply_binding"):
        from app.ai.supply_context import expand_context

        context = expand_context(db, context, user=user, current=True)
    if context.get("satisfaction_binding"):
        from app.ai.satisfaction_context import expand_context
        from app.ai.satisfaction_views import CONTEXT_RESPONSE_BYTES, checked_response

        context = expand_context(db, context, user=user, current=True, locking=True)
        return checked_response({"code": 200, "msg": "success", "data": {"context": context, "metadata": context_metadata(bundle), "evidence": bundle.evidence}}, CONTEXT_RESPONSE_BYTES)
    return {"code": 200, "msg": "success", "data": {"context": context, "metadata": context_metadata(bundle), "evidence": bundle.evidence}}


@router.get("/ai/encounters")
def encounter_options(feature_key: str, patient_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Offer authorized encounters without widening access to another doctor's current case."""
    spec, _ = authorized_feature(db, user, feature_key)
    if spec.number == 36:
        authorize_image_patient(db, user, patient_id, authorize_patient)
    elif spec.number == 37:
        authorize_ecg_patient(db, user, patient_id, authorize_patient)
    else:
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


@router.get("/ai/pathway-options")
def pathway_options(
    feature_key: str, patient_id: int = Query(ge=1), encounter_ref: str | None = Query(None, max_length=64), db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    """Offer bounded template metadata and scoped review availability without loading steps or calling a model."""
    spec, _ = authorized_feature(db, user, feature_key)
    if spec.number not in PATHWAY_SOURCE_FEATURES or user.user_role == "patient":
        raise HTTPException(422, "该能力不提供临床路径选择")
    authorize_patient(db, user, patient_id, spec.category, encounter_ref)
    encounter = get_encounter(db, patient_id, encounter_ref)
    departments = {encounter.department_id} if encounter and encounter.department_id else set()
    rows = db.query(ClinicalPathway).filter_by(status=0).order_by(ClinicalPathway.pathway_id.desc()).limit(101).all()
    reviewed = {item.source_reference_id for item in eligible_pathway_documents(db, [row.pathway_id for row in rows[:100]], spec.key, departments)}
    return {
        "code": 200,
        "msg": "success",
        "data": {
            "items": [
                {"pathway_id": row.pathway_id, "name": row.name, "disease_code": row.disease_code, "disease_name": row.disease_name, "reviewed_for_current_scope": row.pathway_id in reviewed}
                for row in rows[:100]
            ],
            "truncated": len(rows) > 100,
            "scope_note": "仅当前模板目录和本功能、所选就诊科室的审核状态；不证明适用于该患者。未选就诊时仅匹配院内通用知识，选择就诊后须重新核对",
        },
    }


def _context_inspection(db: Session, user: User, key: str, patient_id: int, encounter_ref: str | None, references: dict) -> dict:
    spec, _ = authorized_feature(db, user, key)
    if spec.scope != "patient":
        raise HTTPException(422, "该能力无需加载患者临床资料")
    bundle = patient_snapshot(db, user, spec, patient_id, encounter_ref, references)
    context = bundle.data
    if context.get("sofa_binding"):
        from app.ai.sofa_context import expand_context

        context = expand_context(db, context, user=user, current=True)
    if context.get("charge_binding"):
        from app.ai.charge_reconciliation_context import expand_context

        context = expand_context(db, context, user=user, current=True)
    if context.get("coding_binding"):
        from app.ai.coding_evidence_context import expand_context

        context = expand_context(db, context, user=user, current=True)
    return {"code": 200, "msg": "success", "data": {"context": context, "metadata": context_metadata(bundle), "evidence": bundle.evidence}}


@router.post("/ai/context")
def inspect_context_references(req: ClinicalContextRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Inspect the exact supported source references that will be used by generation."""
    return _context_inspection(db, user, req.feature_key, req.patient_id, req.encounter_ref, req.source_refs)


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
    references = {"record_id": record_id, "structured_record_id": structured_record_id, "prescription_id": prescription_id, "lab_result_id": lab_result_id, "imaging_report_id": imaging_report_id}
    return _context_inspection(db, user, feature_key, patient_id, encounter_ref, references)


@router.post("/ai/runs")
def submit_run(req: RunRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Queue durable work; a separately deployed worker performs inference."""
    run = create_run(db, user, req)
    value = {"code": 200, "msg": "任务已排队", "data": describe_run(run, False, user=user)}
    if req.feature_key == "feedback_analysis":
        from app.ai.satisfaction_views import checked_response

        return checked_response(value)
    return value


@router.get("/ai/runs")
def list_runs(
    feature_key: str | None = None,
    patient_id: int | None = Query(None, ge=1),
    encounter_ref: str | None = Query(None, max_length=64),
    department_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    roster_plan_id: str | None = Query(None, max_length=36),
    ward_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    bed_series_id: str | None = Query(None, max_length=36),
    surgery_pool_id: str | None = Query(None, max_length=36),
    surgery_scenario_id: str | None = Query(None, max_length=36),
    supply_item_kind: str | None = Query(None, max_length=20),
    supply_item_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    supply_series_id: str | None = Query(None, max_length=36),
    inventory_item_kind: str | None = Query(None, max_length=20),
    inventory_item_id: QueryPositiveInteger | None = Query(None, ge=1, le=2147483647),
    inventory_scenario_id: str | None = Query(None, max_length=36),
    coding_case_id: str | None = Query(None, max_length=36),
    charge_case_id: str | None = Query(None, max_length=36),
    charge_native_only: bool = False,
    satisfaction_case_id: str | None = None,
    satisfaction_native_only: bool = False,
    document_original_id: str | None = Query(None, max_length=36),
    drug_label_source_binding_id: str | None = None,
    document_change_scope_id: str | None = Query(None, max_length=36),
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """List own tasks; super-admins can inspect global execution history."""
    from app.ai.native_task_access import lock_directory_gates

    lock_directory_gates(db)
    if feature_key == "feedback_analysis" or satisfaction_case_id is not None or satisfaction_native_only:
        from app.ai.satisfaction_runtime import current_actor

        user = current_actor(db, user)
    if feature_key == "charge_reconciliation" or charge_case_id is not None:
        from app.ai.charge_reconciliation_sources import current_actor

        user = current_actor(db, user)
    if feature_key == "drg_evidence_review" or coding_case_id is not None:
        from app.ai.coding_evidence_sources import current_actor

        user = current_actor(db, user)
    # The per-item native guard below must run before any deferred task TEXT is
    # fetched. This also keeps an unfiltered mixed directory safe to classify.
    query = db.query(AIRun).options(*(defer(getattr(AIRun, key)) for key in ("input_json", "evidence_json", "context_metadata_json", "result_json")))
    if feature_key == "guideline_change_review" or document_change_scope_id is not None:
        from app.ai.document_change_history import filter_history

        query = filter_history(
            db,
            user,
            query,
            feature_key=feature_key,
            scope_id=document_change_scope_id,
            other_scope=(
                patient_id,
                encounter_ref,
                department_id,
                roster_plan_id,
                ward_id,
                bed_series_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
                coding_case_id,
                document_original_id,
                charge_case_id,
                True if charge_native_only else None,
                satisfaction_case_id,
                True if satisfaction_native_only else None,
                drug_label_source_binding_id,
            ),
        )
    if drug_label_source_binding_id is not None:
        from app.ai.drug_label_history import filter_history

        query = filter_history(
            db,
            user,
            query,
            feature_key=feature_key,
            binding_id=drug_label_source_binding_id,
            other_scope=(
                patient_id,
                encounter_ref,
                department_id,
                roster_plan_id,
                ward_id,
                bed_series_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
                coding_case_id,
                charge_case_id,
                True if charge_native_only else None,
                satisfaction_case_id,
                True if satisfaction_native_only else None,
                document_original_id,
                document_change_scope_id,
            ),
        )
    if satisfaction_case_id is not None or satisfaction_native_only:
        from app.ai.satisfaction_history import filter_history

        query = filter_history(
            db,
            user,
            query,
            feature_key=feature_key,
            case_id=satisfaction_case_id,
            native_only=satisfaction_native_only,
            other_scope=(
                patient_id,
                encounter_ref,
                department_id,
                roster_plan_id,
                ward_id,
                bed_series_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
                coding_case_id,
                charge_case_id,
                True if charge_native_only else None,
                document_original_id,
                drug_label_source_binding_id,
                document_change_scope_id,
            ),
        )
    if feature_key == "guideline_ingestion" or document_original_id is not None:
        from app.ai.document_extraction_history import filter_document_history

        query = filter_document_history(
            db,
            user,
            query,
            feature_key=feature_key,
            original_id=document_original_id,
            other_scope=(
                patient_id,
                True if satisfaction_native_only else None,
                satisfaction_case_id,
                charge_case_id,
                True if charge_native_only else None,
                encounter_ref,
                department_id,
                roster_plan_id,
                ward_id,
                bed_series_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
                coding_case_id,
                drug_label_source_binding_id,
                document_change_scope_id,
            ),
        )
    if user.user_role != "super_admin":
        query = query.filter_by(requested_by=user.user_id)
    if feature_key:
        if feature_key == "feedback_analysis":
            from app.ai.satisfaction_history import authorize_history

            user = authorize_history(db, user)
        elif feature_key == "drug_label_extraction":
            from app.ai.drug_label_history import authorize_history

            user = authorize_history(db, user)
        else:
            authorized_feature(db, user, feature_key)
        query = query.filter_by(feature_key=feature_key)
    if charge_native_only:
        if feature_key != "charge_reconciliation" or any(
            value is not None
            for value in (
                department_id,
                roster_plan_id,
                ward_id,
                bed_series_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
                coding_case_id,
                document_original_id,
            )
        ):
            raise HTTPException(422, "新版账目历史筛选仅支持本次真实住院的完整账目任务")
        from app.ai.charge_reconciliation_history import filter_native_history

        query = filter_native_history(db, user, query, patient_id=patient_id, encounter_ref=encounter_ref)
    if charge_case_id is not None:
        if feature_key != "charge_reconciliation" or any(
            value is not None
            for value in (
                department_id,
                roster_plan_id,
                ward_id,
                bed_series_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
                coding_case_id,
                document_original_id,
            )
        ):
            raise HTTPException(422, "账目历史须为本功能同一实际患者住院的单件完整快照，不得混用其他来源")
        from app.ai.charge_reconciliation_history import filter_history

        query = filter_history(db, user, query, charge_case_id=charge_case_id, patient_id=patient_id, encounter_ref=encounter_ref)
    elif coding_case_id is not None:
        if feature_key != "drg_evidence_review" or any(
            value is not None
            for value in (
                department_id,
                roster_plan_id,
                ward_id,
                bed_series_id,
                surgery_pool_id,
                surgery_scenario_id,
                supply_item_kind,
                supply_item_id,
                supply_series_id,
                inventory_item_kind,
                inventory_item_id,
                inventory_scenario_id,
            )
        ):
            raise HTTPException(422, "编码证据历史仅筛选同一实际患者住院的明确快照，不能与其他来源范围混用")
        from app.ai.coding_evidence_history import filter_history

        query = filter_history(db, user, query, coding_case_id=coding_case_id, patient_id=patient_id, encounter_ref=encounter_ref)
    elif any(value is not None for value in (inventory_item_kind, inventory_item_id, inventory_scenario_id)):
        if feature_key != "inventory_optimization" or any(
            value is not None
            for value in (patient_id, encounter_ref, department_id, roster_plan_id, ward_id, bed_series_id, surgery_pool_id, surgery_scenario_id, supply_item_kind, supply_item_id, supply_series_id)
        ):
            raise HTTPException(422, "库存比较历史仅筛选明确品种与原场景，不能与其他运营或患者范围混用")
        from app.ai.inventory_history import filter_history

        query = filter_history(db, user, query, inventory_item_kind=inventory_item_kind, inventory_item_id=inventory_item_id, inventory_scenario_id=inventory_scenario_id)
    elif any(value is not None for value in (supply_item_kind, supply_item_id, supply_series_id)):
        if feature_key != "supply_forecast" or any(
            value is not None for value in (patient_id, encounter_ref, department_id, roster_plan_id, ward_id, bed_series_id, surgery_pool_id, surgery_scenario_id)
        ):
            raise HTTPException(422, "物资历史仅筛选明确品种与原序列，不能与科室、其他运营或患者范围混用")
        from app.ai.supply_history import filter_history

        query = filter_history(db, user, query, supply_item_kind=supply_item_kind, supply_item_id=supply_item_id, supply_series_id=supply_series_id)
    elif surgery_pool_id is not None or surgery_scenario_id is not None or feature_key == "surgery_scheduling" and department_id is not None:
        if feature_key != "surgery_scheduling" or any(value is not None for value in (patient_id, encounter_ref, roster_plan_id, ward_id, bed_series_id)):
            raise HTTPException(422, "手术历史筛选仅用于明确科室、资源池或原场景，不能与其他运营或个体就诊范围混用")
        from app.ai.surgery_history import filter_history

        query = filter_history(db, user, query, department_id=department_id, surgery_pool_id=surgery_pool_id, surgery_scenario_id=surgery_scenario_id)
    elif ward_id is not None or bed_series_id is not None or feature_key == "bed_forecast" and department_id is not None:
        if feature_key != "bed_forecast" or patient_id is not None or encounter_ref is not None or roster_plan_id is not None:
            raise HTTPException(422, "床位历史筛选仅用于床位功能及明确科室、病区或原序列，不与排班或个体就诊混用")
        from app.ai.bed_history import filter_history

        query = filter_history(db, user, query, department_id=department_id, ward_id=ward_id, bed_series_id=bed_series_id)
    elif department_id is not None or roster_plan_id is not None:
        if feature_key != "roster_optimization" or patient_id is not None or encounter_ref is not None:
            raise HTTPException(422, "排班历史筛选仅用于排班功能及明确科室或原计划，不与个体就诊混用")
        from app.ai import roster_facts as facts
        from app.ai.roster_context import selection
        from app.ai.roster_plans import plan_row

        if department_id is not None:
            facts.roster_scope(db, user, department_id, allow_missing=user.user_role == "super_admin")
            query = query.filter(type_coerce(AIRun.input_json, JSON)["payload"]["context"]["roster_binding"]["department_id"].as_integer() == department_id)
        if roster_plan_id is not None:
            roster_plan_id = selection({"roster_plan_id": roster_plan_id})
            plan = plan_row(db, roster_plan_id)
            facts.roster_scope(db, user, plan.department_id, allow_missing=user.user_role == "super_admin")
            if department_id is not None and plan.department_id != department_id:
                raise HTTPException(422, "所选原计划与历史筛选科室不一致")
            query = query.filter(type_coerce(AIRun.input_json, JSON)["payload"]["context"]["roster_binding"]["plan_id"].as_string() == roster_plan_id)
    if patient_id is not None:
        query = query.filter_by(patient_id=patient_id)
    if encounter_ref:
        query = query.filter_by(encounter_ref=encounter_ref)
    data = []
    for item in query.order_by(AIRun.create_time.desc()).limit(limit).all():
        try:
            from app.ai.native_task_access import guard_private_task_read

            guard_private_task_read(db, user, item.run_id)
            authorize_run(db, user, item)
        except HTTPException as exc:
            from app.ai.document_change_storage import is_document_change_run

            if exc.status_code in {403, 404, 409} and is_document_change_run(db, item):
                continue
            if exc.status_code in {403, 404}:
                continue
            if exc.status_code == 409:
                from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact

                if item.feature_key == "feedback_analysis" or db.query(AISatisfactionRunArtifact.run_id).filter_by(run_id=item.run_id).first() is not None:
                    continue
                from app.ai.drug_label_storage import is_drug_label_run

                if is_drug_label_run(db, item):
                    continue
            if exc.status_code == 409 and any(is_document_evidence(db, entry) for entry in json.loads(item.evidence_json)):
                continue
            if exc.status_code == 409:
                from app.ai.coding_evidence_storage import is_coding_run

                if is_coding_run(db, item):
                    continue
            if exc.status_code == 409 and item.feature_key == "surgery_scheduling":
                continue
            if exc.status_code == 409 and item.feature_key == "charge_reconciliation":
                from app.ai.charge_reconciliation_storage import is_charge_run

                if is_charge_run(db, item):
                    continue
            if exc.status_code == 409 and item.feature_key == "inventory_optimization":
                from app.ai.inventory_storage import is_inventory_snapshot

                if is_inventory_snapshot(json.loads(item.input_json)):
                    continue
            if exc.status_code == 409 and item.feature_key == "supply_forecast":
                from app.ai.supply_storage import is_supply_snapshot

                if is_supply_snapshot(json.loads(item.input_json)):
                    continue
            if exc.status_code == 409 and item.feature_key == "roster_optimization":
                from app.ai.roster_storage import is_roster_snapshot

                if is_roster_snapshot(json.loads(item.input_json)):
                    continue
            if exc.status_code == 409 and item.feature_key == "bed_forecast":
                from app.ai.bed_storage import is_bed_snapshot

                if is_bed_snapshot(json.loads(item.input_json)):
                    continue
            raise
        data.append(describe_run(item, False, user=user))
    return {"code": 200, "msg": "success", "data": data}


@router.get("/ai/runs/{run_id}")
def run_detail(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Recheck patient access before exposing a stored result or evidence."""
    from app.ai.native_task_access import guard_private_task_read

    guard_private_task_read(db, user, run_id)
    run = db.get(AIRun, run_id)
    if run is None:
        raise HTTPException(404, "AI 任务不存在")
    authorize_run(db, user, run)
    return {"code": 200, "msg": "success", "data": describe_run(run, user=user)}


@router.post("/ai/runs/{run_id}/cancel")
def cancel_run(run_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Stop accepting a result; an already sent provider call may still finish."""
    from app.ai.document_change_access import has_native_identity
    from app.ai.document_change_runtime import cancel_change_run
    from app.ai.native_task_routing import locate_native_task

    identity = locate_native_task(db, run_id)
    if identity is not None and identity.domain == "document_change" or identity is None and has_native_identity(db, run_id):
        cancel_change_run(db, user, run_id)
        return {"code": 200, "msg": "任务结果已取消接收"}
    from app.ai.native_task_access import guard_private_task_read

    guard_private_task_read(db, user, run_id)
    run = db.get(AIRun, run_id)
    if run is None:
        raise HTTPException(404, "AI 任务不存在")
    from app.ai.charge_reconciliation_storage import is_charge_run

    if is_charge_run(db, run):
        from app.ai.charge_reconciliation_execution import cancel_charge_run

        cancel_charge_run(db, user, run_id)
        return {"code": 200, "msg": "任务结果已取消接收"}
    from app.ai.satisfaction_storage import is_satisfaction_run

    if is_satisfaction_run(db, run):
        from app.ai.satisfaction_execution import cancel_satisfaction_run

        cancel_satisfaction_run(db, user, run_id)
        return {"code": 200, "msg": "任务结果已取消接收"}
    authorize_run(db, user, run)
    from app.ai.drug_label_storage import is_drug_label_run

    if is_drug_label_run(db, run):
        from app.ai.drug_label_runtime import cancel_drug_label_run

        cancel_drug_label_run(db, user, run_id, frozen_audit=user.user_role == "super_admin")
        return {"code": 200, "msg": "任务结果已取消接收"}
    from app.ai.document_extraction_storage import is_extraction_run

    if is_extraction_run(db, run):
        from app.ai.document_extraction_runtime import cancel_document_run

        cancel_document_run(db, user, run_id)
        return {"code": 200, "msg": "任务结果已取消接收"}
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
    from app.ai.native_task_access import guard_private_task_read

    guard_private_task_read(db, user, run_id)
    run = db.get(AIRun, run_id)
    if run is None:
        raise HTTPException(404, "AI 任务不存在")
    authorize_run(db, user, run)
    if run.status != "succeeded":
        raise HTTPException(409, "只能复核已成功生成的建议")
    from app.ai.charge_reconciliation_storage import is_charge_run

    charge = is_charge_run(db, run)
    if charge:
        from app.ai.charge_reconciliation_receipts import load_terminal

        load_terminal(db, run)
    from app.ai.satisfaction_storage import is_satisfaction_run

    satisfaction = not charge and is_satisfaction_run(db, run)
    if satisfaction:
        from app.ai.satisfaction_receipts import load_terminal

        load_terminal(db, run)
    from app.ai.drug_label_storage import is_drug_label_run

    if is_drug_label_run(db, run):
        from app.ai.drug_label_views import run_view

        run_view(db, user, run, frozen_audit=user.user_role == "super_admin")
    from app.ai.document_change_storage import expand_result as expand_change_result
    from app.ai.document_change_storage import is_document_change_run

    if is_document_change_run(db, run):
        expand_change_result(db, user, run, current=True)
    from app.ai.document_extraction_storage import is_extraction_run, load_result

    if not charge and not satisfaction and is_extraction_run(db, run):
        load_result(db, run)
        from app.ai.document_extraction_runtime import usage_receipt

        usage_receipt(db, run)
    from app.ai.coding_evidence_storage import expand_result as expand_coding_result
    from app.ai.coding_evidence_storage import is_coding_run

    if is_coding_run(db, run):
        expand_coding_result(db, run)
    if run.feature_key == "roster_optimization":
        from app.ai.roster_storage import expand_result, is_roster_snapshot

        if is_roster_snapshot(json.loads(run.input_json)):
            expand_result(db, run)
    if run.feature_key == "bed_forecast":
        from app.ai.bed_storage import expand_result, is_bed_snapshot

        if is_bed_snapshot(json.loads(run.input_json)):
            expand_result(db, run)
    if run.feature_key == "surgery_scheduling":
        from app.ai.surgery_storage import expand_result, is_surgery_snapshot

        if is_surgery_snapshot(json.loads(run.input_json)):
            expand_result(db, run)
    if run.feature_key == "inventory_optimization":
        from app.ai.inventory_storage import expand_result, is_inventory_snapshot

        if is_inventory_snapshot(json.loads(run.input_json)):
            expand_result(db, run)
    if run.feature_key == "supply_forecast":
        from app.ai.supply_storage import expand_result, is_supply_snapshot

        if is_supply_snapshot(json.loads(run.input_json)):
            expand_result(db, run)
    if run.feature_key == "sepsis_risk":
        from app.ai.sofa_storage import expand_result, is_sofa_snapshot

        if is_sofa_snapshot(json.loads(run.input_json)):
            expand_result(db, run)
    if req.outcome == "modified" and len(req.comment) < 3:
        raise HTTPException(422, "请说明修改内容")
    item = AIFeedback(run_id=run_id, reviewer_id=user.user_id, outcome=req.outcome, comment=req.comment)
    db.add(item)
    audit(db, user.user_id, "run.feedback", run_id, {"outcome": req.outcome})
    db.commit()
    return {"code": 200, "msg": "复核反馈已记录", "data": {"feedback_id": item.feedback_id}}
