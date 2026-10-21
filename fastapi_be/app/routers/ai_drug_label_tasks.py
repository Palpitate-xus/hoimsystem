"""Inspect one complete released leaflet without invoking inference."""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai.drug_label_context_contract import DrugLabelRequest
from app.ai.drug_label_views import preview, response
from app.database import get_db
from app.dependencies import User, require_roles
from app.routers.ai_document_evidence import BoundedDocumentRoute

router = APIRouter(route_class=BoundedDocumentRoute, default_response_class=JSONResponse)


@router.post("/ai/drug-label/context")
def inspect_drug_label_context(req: DrugLabelRequest, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "pharmacist"))):
    """Authorize the current source before expanding its full public projection."""
    return response(preview(db, user, req.model_dump(mode="json", exclude_unset=True)))
