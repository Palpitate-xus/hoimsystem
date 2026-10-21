"""Complete technical Source directory inside an explicitly authorized scope."""

from fastapi import HTTPException

from app.ai import deidentification_sources as sources
from app.ai.deidentification_access import authorize_subject
from app.ai.deidentification_contract import MAX_BYTES, MAX_ROOTS, PatientScopeRequest
from app.ai.deidentification_http import response_bytes
from app.ai.deidentification_models import AIDeidentificationCase
from app.ai.deidentification_spans import canonical, utf8
from app.ai.research_cohort_sources import _typed
from app.ai.research_cohort_write_guard import current_research_rows


def case_directory(db, user, values):
    request = _typed(PatientScopeRequest, values)
    actor, _, _ = authorize_subject(db, user, request.scope_id, request.patient_id)
    # The caller's scope hashes are still exact required capture anchors.
    from app.ai import deidentification_collection as collection

    collection._scope(db, actor, request, capture=False, external_model=False)
    items, last, amount = [], None, 0
    while True:
        query = db.query(AIDeidentificationCase.case_id).filter_by(scope_id=request.scope_id, patient_id=request.patient_id)
        if last is not None:
            query = query.filter(AIDeidentificationCase.case_id > last)
        ids = current_research_rows(query.order_by(AIDeidentificationCase.case_id), shared=True).limit(32).all()
        if not ids:
            break
        for (identifier,) in ids:
            meta = sources.metadata(sources._opaque(db, identifier))
            amount += len(utf8(canonical(meta)))
            if len(items) >= MAX_ROOTS or amount > MAX_BYTES:
                raise HTTPException(413, "75完整目录超限，未截断或伪称complete")
            items.append(meta)
        last = ids[-1].case_id
    result = {"schema_version": "deidentification_case_directory_v1", "items": items, "total": len(items), "complete": True, "detail_required": True}
    response_bytes(result)
    return result
