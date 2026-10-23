"""Explicit Super RCA preview and split authorized/frozen task pieces."""

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import rca_evidence_task_wire_contract as v
from app.ai import rca_evidence_views as views
from app.database import get_db
from app.dependencies import User, require_roles
from app.routers.ai_rca_evidence import BoundedRcaRoute

router = APIRouter(route_class=BoundedRcaRoute, default_response_class=JSONResponse)
UUID_PATTERN = r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"


@router.post("/ai/rca-evidence/context")
def inspect_rca_context(req: v.RcaPreviewRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return views.response(views.preview(db, user, req))


@router.get("/ai/runs/{run_id}/rca-evidence/source")
def task_source(run_id: str = Path(pattern=UUID_PATTERN), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return views.source_piece(db, user, run_id)


@router.get("/ai/runs/{run_id}/rca-evidence/case")
def task_case(run_id: str = Path(pattern=UUID_PATTERN), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return views.case_piece(db, user, run_id)


@router.get("/ai/runs/{run_id}/rca-evidence/result")
def task_result(run_id: str = Path(pattern=UUID_PATTERN), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return views.result_piece(db, user, run_id)


@router.get("/ai/runs/{run_id}/rca-evidence/receipt")
def task_receipt(run_id: str = Path(pattern=UUID_PATTERN), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return views.receipt_piece(db, user, run_id)


@router.get("/ai/admin/runs/{run_id}/rca-evidence/source")
def frozen_source(run_id: str = Path(pattern=UUID_PATTERN), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return views.source_piece(db, user, run_id, frozen_audit=True)


@router.get("/ai/admin/runs/{run_id}/rca-evidence/case")
def frozen_case(run_id: str = Path(pattern=UUID_PATTERN), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return views.case_piece(db, user, run_id, frozen_audit=True)


@router.get("/ai/admin/runs/{run_id}/rca-evidence/result")
def frozen_result(run_id: str = Path(pattern=UUID_PATTERN), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return views.result_piece(db, user, run_id, frozen_audit=True)


@router.get("/ai/admin/runs/{run_id}/rca-evidence/receipt")
def frozen_receipt(run_id: str = Path(pattern=UUID_PATTERN), db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return views.receipt_piece(db, user, run_id, frozen_audit=True)
