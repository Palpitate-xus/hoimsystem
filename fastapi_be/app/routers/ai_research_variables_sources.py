"""76 source registry: current purpose authority, metadata and bounded parts.

These Main source endpoints neither run extraction models nor write
clinical/queue/export records.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.ai import research_variables_views as views
from app.ai.research_cohort_contract import SHA, UUID, SourceReview, SourceRevoke
from app.ai.research_variables_batches import create_batch, review_batch
from app.ai.research_variables_collection import capture_variable_sources
from app.ai.research_variables_contract import BatchCapture, BatchCreate, DefinitionReview, DictionaryCreate
from app.ai.research_variables_dictionary import create_dictionary, review_dictionary
from app.ai.research_variables_models import MAX_BYTES
from app.database import get_db
from app.dependencies import User, require_roles
from app.routers.inpatient_support import QueryPositiveInteger

router = APIRouter(prefix="/ai/research-variables", tags=["Research variable governed sources"])
Status = Literal["draft", "published", "rejected", "revoked"]
Page = Annotated[QueryPositiveInteger, Query(ge=1, le=100000)]
Size = Annotated[QueryPositiveInteger, Query(ge=1, le=100)]


def reply(value, *, maximum=MAX_BYTES):
    response = JSONResponse({"code": 200, "msg": "success", "data": value})
    if len(response.body) > maximum:
        raise HTTPException(413, "完整来源分件含回执超过8MiB，未截断正文、字段或授权")
    return response


def exact_query(request, allowed):
    pairs = list(request.query_params.multi_items())
    if any(key not in allowed for key, _ in pairs) or len({key for key, _ in pairs}) != len(pairs):
        raise HTTPException(422, "来源查询须使用无重复的闭集参数")


@router.get("/scopes/{scope_id}")
def get_variable_scope_context(
    scope_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist")),
):
    from app.ai.research_variables_scope_context import scope_context

    exact_query(request, set())
    return reply(scope_context(db, user, scope_id))


@router.get("/dictionaries")
def list_dictionaries(
    request: Request,
    scope_id: UUID,
    scope_content_hash: SHA,
    scope_governance_hash: SHA,
    status: Status | None = None,
    page: Page = 1,
    size: Size = 20,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist")),
):
    exact_query(request, {"scope_id", "scope_content_hash", "scope_governance_hash", "status", "page", "size"})
    reference = dict(scope_id=scope_id, scope_content_hash=scope_content_hash, scope_governance_hash=scope_governance_hash)
    return reply(views.list_sources(db, user, "dictionary", scope_reference=reference, status=status, page=page, size=size))


@router.post("/dictionaries")
def make_dictionary(body: DictionaryCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist"))):
    return reply(views.mutation_ack(create_dictionary(db, user, body), "dictionary"))


@router.get("/dictionaries/{dictionary_id}")
def get_dictionary(dictionary_id: UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist"))):
    exact_query(request, set())
    return reply(views.source_metadata(db, user, "dictionary", dictionary_id))


@router.get("/dictionaries/{dictionary_id}/parts/{part}")
def get_dictionary_part(
    dictionary_id: UUID,
    part: Literal["definition", "scope"],
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist")),
):
    exact_query(request, set())
    return reply(views.read_source_part(db, user, "dictionary", dictionary_id, part))


@router.post("/dictionaries/{dictionary_id}/definition-review")
def sign_dictionary(dictionary_id: UUID, body: DefinitionReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist"))):
    return reply(views.mutation_ack(review_dictionary(db, user, dictionary_id, body, definition=True), "dictionary"))


@router.post("/dictionaries/{dictionary_id}/review")
def publish_dictionary(dictionary_id: UUID, body: SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(views.mutation_ack(review_dictionary(db, user, dictionary_id, body), "dictionary"))


@router.post("/dictionaries/{dictionary_id}/revoke")
def revoke_dictionary(dictionary_id: UUID, body: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist"))):
    return reply(views.mutation_ack(review_dictionary(db, user, dictionary_id, body, revoke=True), "dictionary"))


@router.post("/batches/preview")
def preview_batch(body: BatchCapture, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist"))):
    return reply(capture_variable_sources(db, user, body))


@router.get("/batches")
def list_batches(
    request: Request,
    scope_id: UUID,
    scope_content_hash: SHA,
    scope_governance_hash: SHA,
    status: Status | None = None,
    page: Page = 1,
    size: Size = 20,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist")),
):
    exact_query(request, {"scope_id", "scope_content_hash", "scope_governance_hash", "status", "page", "size"})
    reference = dict(scope_id=scope_id, scope_content_hash=scope_content_hash, scope_governance_hash=scope_governance_hash)
    return reply(views.list_sources(db, user, "batch", scope_reference=reference, status=status, page=page, size=size))


@router.post("/batches")
def make_batch(body: BatchCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist"))):
    return reply(views.mutation_ack(create_batch(db, user, body), "batch"))


@router.get("/batches/{batch_id}")
def get_batch(batch_id: UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist"))):
    exact_query(request, set())
    return reply(views.source_metadata(db, user, "batch", batch_id))


@router.get("/batches/{batch_id}/parts/{part}")
def get_batch_part(
    batch_id: UUID,
    part: Literal["source", "snapshot"],
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist")),
):
    exact_query(request, set())
    return reply(views.read_source_part(db, user, "batch", batch_id, part))


@router.post("/batches/{batch_id}/review")
def publish_batch(batch_id: UUID, body: SourceReview, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin"))):
    return reply(views.mutation_ack(review_batch(db, user, batch_id, body), "batch"))


@router.post("/batches/{batch_id}/revoke")
def revoke_batch(batch_id: UUID, body: SourceRevoke, db: Session = Depends(get_db), user: User = Depends(require_roles("super_admin", "admin", "director", "doctor", "pharmacist"))):
    return reply(views.mutation_ack(review_batch(db, user, batch_id, body, revoke=True), "batch"))


@router.get("/technical/{directory}")
def list_technical(
    directory: Literal["dictionaries", "batches"],
    request: Request,
    scope_id: UUID | None = None,
    status: Status | None = None,
    page: Page = 1,
    size: Size = 20,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    exact_query(request, {"scope_id", "status", "page", "size"})
    return reply(views.list_sources(db, user, "dictionary" if directory == "dictionaries" else "batch", technical=True, scope_id=scope_id, status=status, page=page, size=size))


@router.get("/technical/{directory}/{record_id}")
def get_technical(
    directory: Literal["dictionaries", "batches"],
    record_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("super_admin")),
):
    exact_query(request, set())
    return reply(views.source_metadata(db, user, "dictionary" if directory == "dictionaries" else "batch", record_id, technical=True))
