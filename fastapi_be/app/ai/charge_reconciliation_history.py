"""History is scoped through the actual durable case foreign key."""

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.charge_reconciliation_contract import UUID
from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
from app.ai.charge_reconciliation_sources import case_current, current_actor
from app.ai.models import AIRun


def filter_history(db, user, query, *, charge_case_id, patient_id, encounter_ref):
    try:
        identifier = TypeAdapter(UUID).validate_python(charge_case_id, strict=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(422, "历史筛选须明确选择规范账目原件UUID") from exc
    actor = current_actor(db, user)
    value = case_current(db, actor, identifier, audit_only=actor.user_role == "super_admin")
    if actor.user_role != "super_admin" and (patient_id is None or encounter_ref is None):
        raise HTTPException(422, "账目历史须绑定同一实际患者和住院")
    if patient_id is not None and patient_id != value["patient_id"] or encounter_ref is not None and encounter_ref != value["admission_id"]:
        raise HTTPException(403, "历史账目原件与实际患者住院不同")
    return query.filter(AIRun.run_id.in_(db.query(AIChargeRunArtifact.run_id).filter_by(case_snapshot_id=identifier)))
