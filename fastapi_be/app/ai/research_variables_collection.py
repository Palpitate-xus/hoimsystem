"""Whole76 declared literal fields; no temporal winner, inference or export."""

import datetime as dt

from fastapi import HTTPException
from sqlalchemy import or_

from app.ai.research_cohort_collection import FAMILY_CLOCKS, FAMILY_KEYS, Budget, _authorization_manifest, _literal, _models, _parent_locator
from app.ai.research_cohort_sources import _typed, hash_content, utc_text, utcnow
from app.ai.research_cohort_write_guard import current_research_rows
from app.ai.research_variables_authority import authorize_variable_scope
from app.ai.research_variables_contract import BatchCapture, DictionaryCreate
from app.ai.research_variables_dictionary import dictionary_current
from app.ai.research_variables_fields import VARIABLE_USE

MAX_BYTES = 8388608
MAX_ROOTS = 8192
BATCH_SIZE = 32
PARENT_KEYS = {"medical_records": "registration_uuid", "structured_medical_records": "admission_id"}
LIFECYCLE = {"registrations": ("status",), "admissions": ("status",), "medical_records": ("status", "sign_time"), "structured_medical_records": ("status", "sign_time")}


def _windows(variables):
    return sorted({(v.record_window.date_from, v.record_window.date_to) for v in variables if v.record_window is not None})


def _active(variable, clock):
    if variable.record_window is None or clock is None:
        return True
    if not isinstance(clock, dt.datetime) or clock.tzinfo is not None:
        raise HTTPException(409, "原记录窗口时钟类型或未声明时区无法核对")
    day = clock.date().isoformat()
    return variable.record_window.date_from <= day <= variable.record_window.date_to


def _family_records(db, family, patient_id, variables):
    model, key = _models()[family], FAMILY_KEYS[family]
    clock_name = FAMILY_CLOCKS.get(family)
    header_columns = tuple(sorted({key, "patient_id"} | ({clock_name} if clock_name else set())))
    conditions = [model.patient_id == patient_id]
    if clock_name:
        clock = getattr(model, clock_name)
        intervals = [(clock >= dt.datetime.fromisoformat(start)) & (clock < dt.datetime.fromisoformat(end) + dt.timedelta(days=1)) for start, end in _windows(variables)]
        conditions.append(or_(clock.is_(None), *intervals))
    cursor = None
    while True:
        query = db.query(*(getattr(model, name) for name in header_columns)).filter(*conditions)
        if cursor is not None:
            query = query.filter(getattr(model, key) > cursor)
        headers = current_research_rows(query.order_by(getattr(model, key)), shared=True).limit(BATCH_SIZE).all()
        if not headers:
            return
        for values in headers:
            header = dict(zip(header_columns, values, strict=True))
            clock = header[clock_name] if clock_name else None
            active = [variable for variable in variables if _active(variable, clock)]
            if not active:
                raise HTTPException(409, "当前原记录头与明确变量窗口集合不一致")
            columns = tuple(sorted(set(header_columns) | {v.field for v in active} | set(LIFECYCLE.get(family, ())) | ({PARENT_KEYS[family]} if family in PARENT_KEYS else set())))
            current = current_research_rows(db.query(*(getattr(model, name) for name in columns)).filter(getattr(model, key) == header[key]), shared=True).one_or_none()
            if current is None:
                raise HTTPException(409, "变量原记录在完整扫描期间已变化")
            original = dict(zip(columns, (_literal(value) for value in current), strict=True))
            if any(original[name] != _literal(header[name]) for name in header_columns):
                raise HTTPException(409, "变量原记录身份或当前窗口时钟变化")
            yield {
                "family": family,
                "patient_id": patient_id,
                "record_id": original[key],
                "recorded_clock": original[clock_name] if clock_name else None,
                "window_status": "static_subject_without_event_clock" if not clock_name else "unknown_record_clock" if clock is None else "recorded_naive_calendar_in_variable_window",
                "lifecycle_original": {name: original[name] for name in LIFECYCLE.get(family, ())},
                "parent_binding": _parent_locator(db, family, original, patient_id, locking=False),
                "variables": [
                    {
                        "variable_key": variable.variable_key,
                        "field": variable.field,
                        "value_kind": variable.value_kind,
                        "literal": original[variable.field],
                        "record_window": variable.record_window.model_dump() if variable.record_window is not None else None,
                    }
                    for variable in active
                ],
            }
            cursor = header[key]


def capture_variable_sources(db, user, values):
    request = _typed(BatchCapture, values)
    dictionary = dictionary_current(db, user, request.variable_dictionary_id)
    if not dictionary["eligible"] or (dictionary["scope_id"], dictionary["content_hash"], dictionary["governance_hash"]) != (
        request.scope_id,
        request.dictionary_content_hash,
        request.dictionary_governance_hash,
    ):
        raise HTTPException(409, "明确变量字典尚未独立核查发布、当前失效或原三锚已变化")
    reference = {key: getattr(request, key) for key in ("scope_id", "scope_content_hash", "scope_governance_hash")}
    actor, scope, acl, permissions = authorize_variable_scope(db, user, reference, patient_ids=request.patient_ids, capture=True)
    definition = DictionaryCreate.model_validate(dictionary["original"]["payload"])
    budget = Budget()
    for original in (scope, acl, dictionary["original"], *permissions):
        budget.add(original)
    authorizations = _authorization_manifest(db, request.scope_id, budget, locking=False)
    by_family = {}
    for variable in definition.variables:
        by_family.setdefault(variable.family, []).append(variable)
    records, manifest = [], []
    for patient_id in request.patient_ids:
        for family in sorted(by_family):
            for record in _family_records(db, family, patient_id, by_family[family]):
                budget.add(record)
                if len(records) >= MAX_ROOTS:
                    raise HTTPException(413, "完整变量原记录超过8192根，未截断保留部分")
                records.append(record)
                manifest.append({"patient_id": patient_id, "family": family, "record_id": record["record_id"], "content_hash": hash_content(record)})
    body = {
        "schema_version": "research_variable_capture_v1",
        "purpose": VARIABLE_USE,
        "request": request.model_dump(),
        "actor_id": actor.user_id,
        "scope_original": scope,
        "actor_acl": acl,
        "patient_authorizations": permissions,
        "authorization_manifest": authorizations,
        "dictionary_original": dictionary["original"],
        "records": records,
        "member_manifest": manifest,
        "member_manifest_hash": hash_content(manifest),
        "time_basis": "retained_legacy_naive_record_clock_not_historical_asof_availability",
        "missingness_basis": "no_record_null_or_no_model_candidate_does_not_establish_not_measured_not_applicable_or_absent",
        "privacy_basis": "purpose_authorized_literal_fields_may_contain_identifiers_not_anonymous",
    }
    from app.ai.research_cohort_contract import canonical_json

    result = {**body, "captured_at": utc_text(utcnow()), "collection_digest": hash_content(body)}
    if len(canonical_json(result).encode("utf-8")) > MAX_BYTES:
        raise HTTPException(413, "完整变量批次来源超过8MiB，未截断保存或发送")
    return result
