"""Super-only complete comparison previews and separately bounded run artifacts."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import document_change_storage as storage
from app.ai.context import context_metadata
from app.ai.document_change_context import prepare_context
from app.ai.document_change_view_contract import DocumentChangeRequest, bounded_wire, result_packet
from app.database import get_db
from app.dependencies import require_roles
from app.models import User

router = APIRouter(tags=["双原文变更核对任务"], default_response_class=JSONResponse)


def response(value):
    bounded_wire(value)
    return {"code": 200, "msg": "success", "data": value.model_dump(mode="json") if hasattr(value, "model_dump") else value}


@router.post("/ai/document-change/context")
def inspect_context(req: DocumentChangeRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    bundle, _, source = prepare_context(db, user, req.model_dump(mode="json", exclude_unset=True))
    return response(
        {
            "context": bundle.data,
            "metadata": context_metadata(bundle),
            "evidence": bundle.evidence,
            "document_change_source_reference": {"scope_id": source.scope.scope_id, "source_digest": bundle.data["document_change_binding"]["source_digest"]},
            "model_preview_scope": "complete_public_source_plus_question_only;provider_whole_wire_budget_checked_before_queue",
        }
    )


def _run(db, user, run_id, frozen):
    return storage.authorize_run_id(db, user, run_id, current=not frozen)


@router.get("/ai/runs/{run_id}/document-change/source")
def source(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return response(storage.expanded_source(db, user, _run(db, user, run_id, False), current=True))


@router.get("/ai/runs/{run_id}/document-change/scope")
def scope(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return response(storage.expanded_private_scope(db, user, _run(db, user, run_id, False), current=True))


def _result(db, user, run_id, frozen):
    run = _run(db, user, run_id, frozen)
    if run.status != "succeeded":
        raise HTTPException(409, "该任务没有已接受的完整逐字问题结果")
    _, metadata, _, binding, _, _ = storage.authorize_run(db, user, run, current=not frozen)
    return response(result_packet(run_id, binding, metadata["instructions_digest"], storage.expand_result(db, user, run, current=not frozen)))


@router.get("/ai/runs/{run_id}/document-change/result")
def result(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _result(db, user, run_id, False)


@router.get("/ai/admin/runs/{run_id}/document-change/source")
def frozen_source(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return response(storage.expanded_source(db, user, _run(db, user, run_id, True), current=False))


@router.get("/ai/admin/runs/{run_id}/document-change/scope")
def frozen_scope(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return response(storage.expanded_private_scope(db, user, _run(db, user, run_id, True), current=False))


@router.get("/ai/admin/runs/{run_id}/document-change/result")
def frozen_result(run_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return _result(db, user, run_id, True)
