"""Current-purpose76 context and independent complete Task pieces."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai.context import ContextBundle, context_metadata
from app.ai.research_cohort_contract import UUID
from app.ai.research_variables_task_binding import binding_reference
from app.ai.research_variables_task_context import prepare_context
from app.ai.research_variables_task_contract import MAX_BINDING_BYTES, MAX_RUN_TEXT_BYTES, MAX_WIRE_BYTES, VariableTaskSelection
from app.ai.research_variables_task_views import bounded, read_variable_part
from app.database import get_db
from app.dependencies import User, require_roles

router = APIRouter(tags=["科研变量明确来源任务"], default_response_class=JSONResponse)
Part = Literal["binding", "source", "scope", "result", "receipt"]


def exact_query(request):
    if request.query_params:
        raise HTTPException(422, "变量任务分件无自由筛选、患者、模型或审计升级参数")


@router.post("/ai/research-variables/context")
def inspect_variable_context(
    body: VariableTaskSelection,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist")),
):
    exact_query(request)
    prepared = prepare_context(db, user, body.model_dump(mode="json"))
    bundle = ContextBundle(data=prepared.data, evidence=prepared.evidence)
    value = {
        "schema_version": "research_variable_context_preview_v1",
        "context": prepared.data,
        "metadata": context_metadata(bundle),
        "evidence": prepared.evidence,
        "research_variable_binding": prepared.binding.model_dump(mode="json"),
        "binding_reference": binding_reference(prepared.binding),
        "parts": {
            "source": f"/ai/research-variables/batches/{prepared.binding.batch_id}/parts/source",
            "scope": f"/ai/research-variables/batches/{prepared.binding.batch_id}/parts/snapshot",
        },
        "model_preview": {"included": False, "reason": "complete_source_is_an_independent_part"},
        "limits": {"independent_piece_bytes": MAX_WIRE_BYTES, "short_run_column_bytes": MAX_RUN_TEXT_BYTES, "full_binding_bytes": MAX_BINDING_BYTES},
        "scope_note": "完整原件按独立分件核对；登记容量不保证完整模型请求可容纳，入队另全包校验；未调用模型、抽取、导出或验证科学意义。",
    }
    return JSONResponse(bounded({"code": 200, "msg": "success", "data": value}))


@router.get("/ai/runs/{run_id}/research-variables/{part}")
def read_current_variable_part(
    run_id: UUID,
    part: Part,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist")),
):
    exact_query(request)
    # Bare typed part, including all of its own protocol fields, is the exact
    # bounded8MiB response. No later generic wrapper expands a legal boundary.
    return JSONResponse(read_variable_part(db, user, run_id, part))


@router.get("/ai/admin/runs/{run_id}/research-variables/{part}")
def read_frozen_variable_part(run_id: UUID, part: Part, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    exact_query(request)
    return JSONResponse(read_variable_part(db, user, run_id, part, frozen_audit=True))
