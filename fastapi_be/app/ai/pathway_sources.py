"""Patient enrollment facts and the availability of reviewed hospital pathway snapshots."""

from fastapi import HTTPException

from app.ai.pathway_knowledge import eligible_pathway_documents, pathway_hash
from app.models import Admission, ClinicalPathway, PathwayEnrollment
from app.pathway_progress import pathway_progress

PATHWAY_SOURCE_FEATURES = frozenset({1, 5, 6, 7, 8, 23, 24, 25, 48, 76})


def selected_pathway_ids(context):
    identifier = context.get("pathway_sources", {}).get("selected_pathway_id")
    return {identifier} if identifier is not None else set()


def attach_pathway_sources(db, user, spec, patient, encounter, bundle, add, selected, bounded, authorize):
    chosen = selected.get("pathway_enrollment_id")
    template = selected.get("pathway_id")
    if user.user_role == "patient" or spec.number not in PATHWAY_SOURCE_FEATURES:
        if chosen is not None or template is not None:
            raise HTTPException(422, "该功能不接受内部临床路径资料")
        return
    if template is not None and chosen is not None and template.pathway_id != chosen.pathway_id:
        raise HTTPException(422, "所选路径与入径记录不一致")
    chosen_id = template.pathway_id if template is not None else chosen.pathway_id if chosen is not None else None
    admissions = {}

    def admission_scope(row, explicit=False):
        if not row.admission_id:
            return "not_recorded"
        admission = db.get(Admission, row.admission_id)
        if admission is None or admission.patient_id != patient.patient_id:
            if explicit:
                raise HTTPException(422, "所选入径记录的住院关联不存在或患者不一致，须先核对原记录")
            return None
        if encounter is not None and (not isinstance(encounter, Admission) or encounter.admission_id != admission.admission_id):
            if explicit:
                raise HTTPException(422, "所选入径记录与本次就诊不一致")
            return None
        try:
            authorize(db, user, patient.patient_id, spec.category, admission.admission_id)
        except HTTPException as exc:
            if exc.status_code != 403 or explicit:
                raise
            return None
        admissions[admission.admission_id] = admission
        return "current_encounter" if encounter is not None else "verified_historical_admission"

    if chosen is not None:
        admission_scope(chosen, True)
        if encounter is None and chosen.admission_id in admissions:
            department = admissions[chosen.admission_id].department_id
            bundle.department_ids = {department} if department else set()
    query = db.query(PathwayEnrollment).filter_by(patient_id=patient.patient_id)
    if encounter is not None:
        query = query.filter(PathwayEnrollment.admission_id == encounter.admission_id) if isinstance(encounter, Admission) else query.filter(False)
    candidates = bounded(query.order_by(PathwayEnrollment.enroll_date.desc(), PathwayEnrollment.enrollment_id.desc()), 6, "临床路径入径记录", "pathway_enrollment_id", "enrollment_id")
    rows = []
    for row in candidates:
        state = admission_scope(row, row is chosen)
        if state is not None:
            rows.append((row, state))
        else:
            bundle.data["missing_data"].append("部分入径记录的住院关联无法核实或超出当前授权范围，未加载；有限记录不代表完整路径史")
    ids = {row.pathway_id for row, _ in rows}
    if chosen_id is not None:
        ids.add(chosen_id)
    templates = {row.pathway_id: row for row in db.query(ClinicalPathway).filter(ClinicalPathway.pathway_id.in_(ids)).all()}
    documents = eligible_pathway_documents(db, ids, spec.key, bundle.department_ids) if ids else []
    reviewed = {}
    for document in documents:
        # Use the newest currently applicable reviewed version of each exact source.
        reviewed.setdefault(document.source_reference_id, document)
    envelope = {
        "scope_note": "仅原入径、变异、退出及节点计数记录；路径启用和入径状态不证明适用性、实际治疗执行、疗效或出院适宜性。当前模板不是入径当时冻结版本，未把今天的步骤倒填为历史治疗",
        "selected_pathway_id": chosen_id,
        "source_admission_refs": sorted(admissions),
        "current_templates": [],
        "enrollments": [],
    }
    for identifier in sorted(ids):
        row = templates.get(identifier)
        document = reviewed.get(identifier)
        envelope["current_templates"].append(
            add(
                "pathway-template:" + str(identifier),
                "当前临床路径模板元数据（不是治疗依据）",
                {
                    "pathway_id": identifier,
                    "exists_in_current_directory": row is not None,
                    "name": row.name if row else None,
                    "disease_code": row.disease_code if row else None,
                    "disease_name": row.disease_name if row else None,
                    "recorded_status": row.status if row else None,
                    "expected_days": row.expected_days if row else None,
                    "snapshot_hash": pathway_hash(row) if row else None,
                    "source_revision": row.source_revision if row else None,
                    "explicitly_selected": identifier == chosen_id,
                    "reviewed_knowledge": {"document_id": document.document_id, "version": document.version, "content_hash": document.content_hash} if document else None,
                    "steps_in_patient_context": False,
                    "definition_note": "原步骤仅通过当前匹配、适用科室和功能且已审核发布的知识引用提供；模板元数据不能作为治疗推荐的依据。预计天数不是个体治疗终点或出院目标，疾病编码未验证与本次诊断等价",
                },
                row.create_time if row else None,
            )
        )
    for row, state in rows:
        progress = pathway_progress(row.completed_items, row.total_items)
        envelope["enrollments"].append(
            add(
                "pathway-enrollment:" + str(row.enrollment_id),
                "原临床路径入径、变异与计数记录",
                {
                    "enrollment_id": row.enrollment_id,
                    "pathway_id": row.pathway_id,
                    "admission_id": row.admission_id or None,
                    "encounter_assignment": state,
                    "recorded_status": row.status,
                    "recorded_status_meaning": {1: "在径标记", 2: "变异标记", 3: "完成出径标记", 4: "退出标记"}.get(row.status, "未知"),
                    **{
                        name: getattr(row, name)
                        for name in ("enroll_date", "exit_date", "variation_type", "variation_reason", "exit_reason", "completed_items", "total_items", "create_time", "update_time")
                    },
                    **progress,
                    "explicitly_selected": row is chosen,
                    "enrollment_template_version": "not_recorded",
                    "actual_item_execution": "not_recorded",
                    "definition_note": "原表没有入径时的模板快照、逐项执行时间与实际治疗起止；不能把计数、变异文字或完成标记转成疗效、治疗因果或出院判断",
                },
                row.update_time or row.create_time,
            )
        )
        if progress["counter_state"] != "known":
            bundle.data["missing_data"].append("入径记录#" + str(row.enrollment_id) + "：" + progress["counter_note"])
    if chosen_id is not None and chosen_id not in reviewed:
        bundle.data["missing_data"].append("所选路径缺少当前匹配且适用于本功能和科室的已审核知识版本，未提供原步骤用于推荐")
    if rows:
        bundle.data["missing_data"].append("入径记录未保存历史模板版本、逐项执行和实际治疗起止；疗效复评须另核对治疗前后资料，不能由路径状态推断")
    bundle.data["pathway_sources"] = envelope
