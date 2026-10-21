"""Exact case history filters under the actual patient and Admission authority."""

from fastapi import HTTPException
from sqlalchemy import JSON, type_coerce

from app.ai.coding_evidence_context import selection
from app.ai.coding_evidence_sources import case_current, current_actor
from app.ai.models import AIRun


def filter_history(db, user, query, *, coding_case_id, patient_id=None, encounter_ref=None):
    actor = current_actor(db, user)
    identifier = selection({"coding_case_id": coding_case_id})
    case = case_current(db, actor, identifier, audit_only=actor.user_role == "super_admin", execution=actor.user_role != "super_admin")
    if patient_id is not None and patient_id != case["patient_id"] or encounter_ref is not None and encounter_ref != case["admission_id"]:
        raise HTTPException(422, "所选编码证据与历史患者或住院筛选范围不一致")
    binding = type_coerce(AIRun.input_json, JSON)["payload"]["context"]["coding_binding"]
    return query.filter(binding["case_snapshot_id"].as_string() == identifier, AIRun.patient_id == case["patient_id"], AIRun.encounter_ref == case["admission_id"])
