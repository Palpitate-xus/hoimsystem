"""Complete current review capture, safe capsules and immutable technical governance."""

import datetime
import hashlib
import hmac
import json
import math
import re
import secrets
import uuid
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import String, cast

from app.ai.governance import audit, digest
from app.ai.models import AIReviewExcerpt
from app.ai.satisfaction_contract import POLICY, SOURCE_ROLES, CaptureRequest, CaseCreate, CaseWrapper, Collection, SafeCapture, SafeSnapshot, SatisfactionSource, Snapshot, SourceReview, SourceRevoke
from app.ai.satisfaction_models import MAX_BYTES, MAX_ROOTS, AISatisfactionCase
from app.ai.satisfaction_write_guard import current_actor, current_satisfaction_rows, lock_satisfaction_write
from app.models import Department, Doctor, MedicalRecord, Patient, Registration, Review, User
from app.sql_text import UTF8Bytes

GOVERNANCE = ("status", "revision", "reviewed_at", "reviewed_by", "review_basis_note", "revoked_at", "revoked_by", "revoke_reason")
EXCERPT_BODY = ("excerpt_id", "review_id", "version", "source_hash", "department_id", "redacted_text", "text_hash", "change_note", "created_by", "create_time")
EXCERPT_GOV = ("status", "revision", "privacy_checked", "faithfulness_checked", "review_note", "reviewed_by", "reviewed_at", "retired_by", "retired_at")
SCAN_CAP = 200000


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def utc_text(value):
    return value.isoformat(timespec="microseconds") + "Z"


def canonical_json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def hash_content(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def bounded(value):
    if len(canonical_json(value).encode("utf-8")) > MAX_BYTES:
        raise HTTPException(409, "完整评价证据超过8MiB，拒绝截断或部分提交")
    return value


def typed(model, value):
    return model.model_validate(value.model_dump(mode="json") if hasattr(value, "model_dump") else value)


def legacy_clock(value):
    """Interpret only a real naive stored calendar; never invent UTC or a timezone."""
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?", value):
        return None
    try:
        return datetime.datetime.fromisoformat(value)
    except ValueError:
        return None


def _scalar(value):
    kind = "null" if value is None else "integer" if type(value) is int else "real" if type(value) is float else "text" if type(value) is str else None
    if kind is None or type(value) is float and not math.isfinite(value):
        raise HTTPException(409, "原评分SQL类型不可完整核对")
    return {"kind": kind, "text": None if value is None else str(value)}


def _score(row):
    value = row["score"]
    return int(value["text"]) if value["kind"] == "integer" and 1 <= int(value["text"]) <= 5 else None


def authorize_scope(db, user, request, *, creating=False):
    req = typed(CaptureRequest, request)
    actor = lock_satisfaction_write(db, user, allowed_roles=SOURCE_ROLES)
    if req.scope_kind == "hospital_reviews":
        if actor.user_role == "director" or creating and actor.user_role != "super_admin":
            raise HTTPException(403, "全院评价原件仅超级管理员创建；普通管理员仅可读取安全证据")
        return actor
    rows = current_satisfaction_rows(db.query(Doctor.doctor_id, Doctor.department_id).filter(Doctor.doctor_id.in_(req.doctor_ids)).order_by(Doctor.doctor_id), shared=True).all()
    if [r.doctor_id for r in rows] != req.doctor_ids:
        raise HTTPException(403, "显式医生集合包含当前不存在的实际医生")
    if actor.user_role == "director":
        own = current_satisfaction_rows(db.query(Doctor.doctor_id, Doctor.department_id).filter_by(user_id=actor.user_id).order_by(Doctor.doctor_id), shared=True).all()
        departments = {r.department_id for r in own if r.department_id is not None}
        if not departments or any(r.department_id not in departments for r in rows):
            raise HTTPException(403, "所选医生未全部位于本人真实医生记录的当前科室")
    return actor


def _rows(db, model, primary, ids, names, charge):
    """Exact parent keys, including current reads of missing no-FK visit keys."""
    result = []
    for key in sorted(set(ids)):
        query = db.query(*(getattr(model, name) for name in names)).filter(primary == key)
        row = current_satisfaction_rows(query, shared=True).one_or_none()
        if row is not None:
            value = dict(row._mapping)
            charge(value)
            result.append(value)
    return result


def _collection_body(value):
    return {k: value[k] for k in ("schema_version", "request", "reviews", "excerpts", "parents")}


def capture_sources(db, user, request, *, creating=False, locking=False):
    """Current complete collection, not an as-of replay. Locking reads are unconditional."""
    req = typed(CaptureRequest, request)
    authorize_scope(db, user, req, creating=creating)
    spent = 0

    def charge(value):
        nonlocal spent
        spent += len(canonical_json(value).encode("utf-8"))
        if spent > MAX_BYTES:
            raise HTTPException(409, "完整评价及全部摘录版本超过8MiB，拒绝部分捕获")

    predicate = [] if req.scope_kind == "hospital_reviews" else [Review.doctor_id.in_(req.doctor_ids)]
    last, scanned, review_ids = 0, 0, []
    while True:
        # Only locator metadata is scanned; unauthorized foreign comments are never read.
        rows = (
            current_satisfaction_rows(db.query(Review.review_id, cast(Review.review_time, String).label("clock")).filter(*predicate, Review.review_id > last).order_by(Review.review_id), shared=True)
            .limit(256)
            .all()
        )
        if not rows:
            break
        scanned += len(rows)
        if scanned > SCAN_CAP:
            raise HTTPException(409, "当前医生范围评价技术成员扫描超过200000，未生成截断来源")
        for row in rows:
            clock = legacy_clock(row.clock)
            if clock is None or req.date_from <= clock.date().isoformat() <= req.date_to:
                review_ids.append(row.review_id)
                if len(review_ids) > MAX_ROOTS:
                    raise HTTPException(409, "相关评价与摘录版本合计超过8192，拒绝截断")
        last = rows[-1].review_id
    reviews = []
    for key in review_ids:
        size = current_satisfaction_rows(db.query(UTF8Bytes(Review.comment)).filter(Review.review_id == key), shared=True).scalar()
        if size is not None and size > MAX_BYTES - spent:
            raise HTTPException(409, "原评价正文超过剩余完整捕获容量")
        columns = [cast(c, String).label(c.name) if c.name == "review_time" else c for c in Review.__table__.columns]
        row = current_satisfaction_rows(db.query(*columns).filter(Review.review_id == key), shared=True).one()
        value = dict(row._mapping)
        value["score"] = _scalar(value["score"])
        charge(value)
        reviews.append(value)
    excerpts = []
    last = ""
    while review_ids:
        locator = (
            current_satisfaction_rows(
                db.query(AIReviewExcerpt.excerpt_id).filter(AIReviewExcerpt.review_id.in_(review_ids), AIReviewExcerpt.excerpt_id > last).order_by(AIReviewExcerpt.excerpt_id), shared=True
            )
            .limit(128)
            .all()
        )
        if not locator:
            break
        if len(reviews) + len(excerpts) + len(locator) > MAX_ROOTS:
            raise HTTPException(409, "相关评价与所有摘录版本合计超过8192，拒绝截断")
        for (key,) in locator:
            # Refuse a huge legacy TEXT before loading its full contents into Python.
            length = sum(UTF8Bytes(c) for c in (AIReviewExcerpt.redacted_text, AIReviewExcerpt.change_note, AIReviewExcerpt.review_note))
            size = current_satisfaction_rows(db.query(length).filter(AIReviewExcerpt.excerpt_id == key), shared=True).scalar()
            if size is None or size > MAX_BYTES - spent:
                raise HTTPException(409, "完整摘录原件超过剩余捕获容量")
            columns = [cast(c, String).label(c.name) if c.name in {"create_time", "reviewed_at", "retired_at"} else c for c in AIReviewExcerpt.__table__.columns]
            value = dict(current_satisfaction_rows(db.query(*columns).filter(AIReviewExcerpt.excerpt_id == key), shared=True).one()._mapping)
            charge(value)
            excerpts.append(value)
        last = locator[-1].excerpt_id
    doctors = _rows(db, Doctor, Doctor.doctor_id, req.doctor_ids + [r["doctor_id"] for r in reviews if r["doctor_id"] is not None], ("doctor_id", "department_id", "user_id", "name", "phone"), charge)
    patients = _rows(db, Patient, Patient.patient_id, [r["patient_id"] for r in reviews if r["patient_id"] is not None], ("patient_id", "name", "identity", "phone", "address"), charge)
    visits = _rows(
        db, MedicalRecord, MedicalRecord.medical_record_id, [r["visit_id"] for r in reviews if r["visit_id"] is not None], ("medical_record_id", "patient_id", "doctor_id", "registration_uuid"), charge
    )
    registrations = _rows(
        db,
        Registration,
        Registration.registration_uuid,
        [r["registration_uuid"] for r in visits if r["registration_uuid"] is not None],
        ("registration_uuid", "patient_id", "doctor_id", "department_id"),
        charge,
    )
    department_ids = sorted({r["department_id"] for r in doctors + registrations if r["department_id"] is not None})
    departments = _rows(db, Department, Department.department_id, department_ids, ("department_id",), charge)
    reviewers = _rows(db, User, User.user_id, [r["reviewed_by"] for r in excerpts if r["reviewed_by"] is not None], ("user_id", "user_role"), charge)
    result = {
        "schema_version": "satisfaction_collection_private_v1",
        "request": req.model_dump(),
        "captured_at": utc_text(utcnow()),
        "reviews": reviews,
        "excerpts": excerpts,
        "parents": {"doctors": doctors, "patients": patients, "visits": visits, "registrations": registrations, "department_ids": [r["department_id"] for r in departments], "reviewers": reviewers},
    }
    result["collection_digest"] = hash_content(_collection_body(result))
    return verify_capture(bounded(result))


def verify_capture(value):
    try:
        c = Collection.model_validate(value).model_dump()
        if hash_content(_collection_body(c)) != c["collection_digest"] or len(c["reviews"]) + len(c["excerpts"]) > MAX_ROOTS:
            raise ValueError("Collection digest or root count differs")
        for name, key in (("reviews", "review_id"), ("excerpts", "excerpt_id")):
            if [r[key] for r in c[name]] != sorted({r[key] for r in c[name]}):
                raise ValueError("Original roots must be complete sorted unique identities")
        ids = {r["review_id"] for r in c["reviews"]}
        if any(e["review_id"] not in ids for e in c["excerpts"]):
            raise ValueError("Excerpt is outside captured reviews")
        for name, key in (("doctors", "doctor_id"), ("patients", "patient_id"), ("visits", "medical_record_id"), ("registrations", "registration_uuid"), ("reviewers", "user_id")):
            if [r[key] for r in c["parents"][name]] != sorted({r[key] for r in c["parents"][name]}):
                raise ValueError("Parent identities must be sorted unique")
        p = c["parents"]
        targets = {
            "doctors": ("doctor_id", set(c["request"]["doctor_ids"]) | {r["doctor_id"] for r in c["reviews"] if r["doctor_id"] is not None}),
            "patients": ("patient_id", {r["patient_id"] for r in c["reviews"] if r["patient_id"] is not None}),
            "visits": ("medical_record_id", {r["visit_id"] for r in c["reviews"] if r["visit_id"] is not None}),
            "registrations": ("registration_uuid", {r["registration_uuid"] for r in p["visits"] if r["registration_uuid"] is not None}),
            "reviewers": ("user_id", {e["reviewed_by"] for e in c["excerpts"] if e["reviewed_by"] is not None}),
        }
        if any(not {r[key] for r in p[name]} <= ids for name, (key, ids) in targets.items()):
            raise ValueError("Foreign parent identities are outside the complete root closure")
        if not set(c["request"]["doctor_ids"]) <= {r["doctor_id"] for r in p["doctors"]}:
            raise ValueError("Explicit Doctor cohort is incomplete")
        dept_targets = {r["department_id"] for r in p["doctors"] + p["registrations"] if r["department_id"] is not None}
        if p["department_ids"] != sorted(set(p["department_ids"])) or not set(p["department_ids"]) <= dept_targets:
            raise ValueError("Department proof is outside actual parent bindings")
        req = c["request"]
        for row in c["reviews"]:
            if req["scope_kind"] == "explicit_doctor_cohort" and row["doctor_id"] not in req["doctor_ids"]:
                raise ValueError("A foreign doctor original cannot be captured")
            clock = legacy_clock(row["review_time"])
            if clock is not None and not req["date_from"] <= clock.date().isoformat() <= req["date_to"]:
                raise ValueError("Known unrelated date cannot be included")
        return bounded(c)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(409, "完整评价集合的类型、范围或原SHA无法核对") from exc


def _parents(c):
    p = c["parents"]
    return {
        "doctors": {r["doctor_id"]: r for r in p["doctors"]},
        "patients": {r["patient_id"]: r for r in p["patients"]},
        "visits": {r["medical_record_id"]: r for r in p["visits"]},
        "registrations": {r["registration_uuid"]: r for r in p["registrations"]},
        "reviewers": {r["user_id"]: r for r in p["reviewers"]},
    }


def _parent_state(c, review, parents=None):
    p = parents if parents is not None else _parents(c)
    doctor, patient, visit = p["doctors"].get(review["doctor_id"]), p["patients"].get(review["patient_id"]), p["visits"].get(review["visit_id"])
    registration = p["registrations"].get(visit["registration_uuid"]) if visit else None
    if not doctor or not patient or not visit or visit["patient_id"] != review["patient_id"] or visit["doctor_id"] != review["doctor_id"]:
        return None
    if visit["registration_uuid"] is not None and (registration is None or registration["patient_id"] != review["patient_id"] or registration["doctor_id"] != review["doctor_id"]):
        return None
    department = registration["department_id"] if registration else doctor["department_id"]
    if department not in c["parents"]["department_ids"]:
        return None
    return doctor, patient, visit, registration, department


def _legacy_fingerprint(c, review, parents=None):
    state = _parent_state(c, review, parents)
    clock = legacy_clock(review["review_time"])
    if state is None or clock is None or review["score"]["kind"] not in {"null", "integer"}:
        return None
    doctor, patient, visit, registration, department = state
    original = {k: review[k] for k in ("review_id", "patient_id", "doctor_id", "visit_id", "comment")}
    original.update(review_time=clock, score=None if review["score"]["kind"] == "null" else int(review["score"]["text"]))
    return digest(
        {
            "review": original,
            "visit": visit,
            "registration": registration,
            "department_id": department,
            "patient_identifiers": [patient[k] for k in ("name", "identity", "phone", "address")],
            "doctor_identifiers": [doctor[k] for k in ("name", "phone")],
        }
    )


def excerpt_hashes(row):
    return hash_content({k: row[k] for k in EXCERPT_BODY}), hash_content({k: row[k] for k in EXCERPT_GOV})


def _excerpt_reasons(c, row, parents=None, reviews=None):
    parents = parents if parents is not None else _parents(c)
    review = reviews[row["review_id"]] if reviews is not None else next(r for r in c["reviews"] if r["review_id"] == row["review_id"])
    state = _parent_state(c, review, parents)
    reasons = []
    if row["status"] != "published":
        reasons.append("excerpt_not_published")
    if state is None:
        reasons.append("unresolved_actual_parent")
    if _legacy_fingerprint(c, review, parents) != row["source_hash"]:
        reasons.append("legacy_source_fingerprint_changed")
    if digest(row["redacted_text"]) != row["text_hash"]:
        reasons.append("legacy_text_hash_changed")
    if row["privacy_checked"] != 1:
        reasons.append("privacy_not_explicitly_checked")
    if row["faithfulness_checked"] != 1:
        reasons.append("faithfulness_not_explicitly_checked")
    reviewer = parents["reviewers"].get(row["reviewed_by"])
    if reviewer is None or reviewer["user_role"] != "super_admin":
        reasons.append("reviewer_not_current_super_admin")
    created, reviewed = legacy_clock(row["create_time"]), legacy_clock(row["reviewed_at"])
    if created is None or reviewed is None or reviewed < created:
        reasons.append("legacy_review_clock_unresolved")
    if (
        not row["review_note"].strip()
        or not row["change_note"].strip()
        or not row["redacted_text"].strip()
        or row["version"] is None
        or row["version"] < 1
        or row["revision"] is None
        or row["revision"] < 2
    ):
        reasons.append("manual_review_basis_incomplete")
    if state is not None:
        doctor, patient, _, _, department = state
        if row["department_id"] != department:
            reasons.append("legacy_parent_department_changed")
        # The old known-identifier check is an additional condition, not a new anonymizer.
        from app.ai.context import minimize_identifiers

        text = minimize_identifiers(row["redacted_text"], SimpleNamespace(**patient))
        for identifier in (doctor["name"], doctor["phone"]):
            if identifier and len(identifier) >= 2:
                text = text.replace(identifier, "[已隐藏医务人员标识]")
        if text != row["redacted_text"]:
            reasons.append("known_direct_identifier_retained")
    return reasons


def review_token(c, review):
    return hash_content(["satisfaction_capture_review", c["collection_digest"], review["review_id"], hash_content(review)])


def selection_options(c):
    """Safe technical candidates, with no integer Review/patient/visit identifiers."""
    parents = _parents(c)
    originals = {r["review_id"]: r for r in c["reviews"]}
    all_reasons = {e["excerpt_id"]: _excerpt_reasons(c, e, parents, originals) for e in c["excerpts"]}
    eligible = {key: not value for key, value in all_reasons.items()}
    counts = {}
    for e in c["excerpts"]:
        if eligible[e["excerpt_id"]]:
            counts[e["review_id"]] = counts.get(e["review_id"], 0) + 1
    result = []
    for e in c["excerpts"]:
        reasons = list(all_reasons[e["excerpt_id"]])
        if counts.get(e["review_id"], 0) > 1:
            reasons.append("conflicting_current_published_versions")
        content, governance = excerpt_hashes(e)
        result.append(
            {
                "excerpt_id": e["excerpt_id"],
                "review_token": review_token(c, originals[e["review_id"]]),
                "content_hash": content,
                "governance_hash": governance,
                "status": e["status"] if e["status"] in {"draft", "published", "rejected", "retired"} else "unknown",
                "version": e["version"],
                "eligible": not reasons,
                "exclusion_reasons": reasons,
                "reviewed_text": e["redacted_text"] if not reasons else None,
            }
        )
    return result


def _validate_selection(c, request):
    options = {o["excerpt_id"]: o for o in selection_options(c)}
    selected_reviews = set()
    for s in request["selected_excerpts"]:
        option = options.get(s["excerpt_id"])
        if option is None or not option["eligible"] or any(option[k] != s[k] for k in ("review_token", "content_hash", "governance_hash")):
            raise HTTPException(409, "所选摘录不属于该完整集合，或其原件、审核、隐私声明已失效")
        if s["review_token"] in selected_reviews:
            raise HTTPException(409, "同一评价只能显式选择一个当前合格版本，不能选择有利版本消解冲突")
        selected_reviews.add(s["review_token"])


def _statistics(rows):
    histogram = {str(i): 0 for i in range(1, 6)}
    nulls = invalid = 0
    for row in rows:
        score = _score(row)
        if score is not None:
            histogram[str(score)] += 1
        elif row["score"]["kind"] == "null":
            nulls += 1
        else:
            invalid += 1
    count, total = sum(histogram.values()), sum(int(k) * v for k, v in histogram.items())
    divisor = math.gcd(count, total)
    mean = {"numerator": total // divisor, "denominator": count // divisor} if count else None
    return {"record_count": len(rows), "valid_score_count": count, "null_score_count": nulls, "invalid_score_count": invalid, "histogram": histogram, "mean_valid_score": mean}


def token(snapshot, namespace, identifier):
    return hmac.new(bytes.fromhex(snapshot["identity_secret"]), canonical_json([namespace, identifier]).encode("utf-8"), hashlib.sha256).hexdigest()


def safe_snapshot(snapshot):
    c, req = snapshot["collection"], snapshot["request"]
    selected = {s["excerpt_id"] for s in req["selected_excerpts"]}
    review_tokens = {r["review_id"]: token(snapshot, "review", r["review_id"]) for r in c["reviews"]}
    reviews, manifest, excerpts = [], [], []
    options = {o["excerpt_id"]: o for o in selection_options(c)}
    parents = _parents(c)
    for r in c["reviews"]:
        clock = legacy_clock(r["review_time"])
        source_hash = hash_content(r)
        score = _score(r)
        reviews.append(
            {
                "review_token": review_tokens[r["review_id"]],
                "content_hash": source_hash,
                "recorded_date": clock.date().isoformat() if clock else None,
                "date_status": "in_period_legacy_naive" if clock else "unknown_legacy_clock",
                "recorded_score": score,
                "score_status": "valid_1_to_5" if score is not None else "null" if r["score"]["kind"] == "null" else "invalid",
                "parent_status": "consistent_actual_links" if _parent_state(c, r, parents) else "unresolved_actual_links",
                "has_comment": bool((r["comment"] or "").strip()),
            }
        )
        manifest.append(
            {
                "kind": "review",
                "member_token": review_tokens[r["review_id"]],
                "review_token": review_tokens[r["review_id"]],
                "content_hash": source_hash,
                "governance_hash": None,
                "status": "not_applicable",
                "version": None,
                "revision": None,
                "selected": False,
                "eligibility": "original_record",
                "exclusion_reasons": [],
            }
        )
    for e in c["excerpts"]:
        option = options[e["excerpt_id"]]
        opaque = token(snapshot, "excerpt", e["excerpt_id"])
        manifest.append(
            {
                "kind": "excerpt",
                "member_token": opaque,
                "review_token": review_tokens[e["review_id"]],
                "content_hash": option["content_hash"],
                "governance_hash": option["governance_hash"],
                "status": option["status"],
                "version": e["version"],
                "revision": e["revision"],
                "selected": e["excerpt_id"] in selected,
                "eligibility": "eligible_manual_claim" if option["eligible"] else "ineligible_manual_claim",
                "exclusion_reasons": option["exclusion_reasons"],
            }
        )
        if e["excerpt_id"] in selected:
            excerpts.append(
                {
                    "excerpt_token": opaque,
                    "review_token": review_tokens[e["review_id"]],
                    "original_content_hash": option["content_hash"],
                    "original_governance_hash": option["governance_hash"],
                    "text": e["redacted_text"],
                    "text_hash": hashlib.sha256(e["redacted_text"].encode("utf-8")).hexdigest(),
                    "version": e["version"],
                    "review_basis_hash": token(snapshot, "excerpt_review_basis", e["review_note"]),
                    "claim": "legacy_manual_privacy_and_faithfulness_review_not_anonymity_or_fact_verification",
                }
            )
    manifest.sort(key=lambda r: (r["kind"], r["member_token"]))
    value = {
        "schema_version": "satisfaction_safe_snapshot_v1",
        "case_id": snapshot["case_id"],
        "scope_kind": c["request"]["scope_kind"],
        "doctor_cohort_size": len(c["request"]["doctor_ids"]) if c["request"]["scope_kind"] == "explicit_doctor_cohort" else None,
        "date_from": c["request"]["date_from"],
        "date_to": c["request"]["date_to"],
        "time_basis": "stored_legacy_naive_calendar_timezone_unknown",
        "unknown_date_member_count": sum(r["date_status"] == "unknown_legacy_clock" for r in reviews),
        "unresolved_parent_count": sum(r["parent_status"] == "unresolved_actual_links" for r in reviews),
        "all_member_statistics": _statistics(c["reviews"]),
        "known_period_statistics": _statistics([r for r in c["reviews"] if legacy_clock(r["review_time"]) is not None]),
        "reviews": reviews,
        "selected_excerpts": excerpts,
        "member_manifest": manifest,
        "member_manifest_hash": hash_content(manifest),
        "policy_hash": hash_content(snapshot["policy"]),
    }
    return bounded(SafeSnapshot.model_validate(value).model_dump())


def verify_snapshot(value, *, validate_current_policy=False):
    try:
        snap = Snapshot.model_validate(value).model_dump()
        c = verify_capture(snap["collection"])
        if snap["request"]["request"] != c["request"] or snap["request"]["expected_collection_digest"] != c["collection_digest"]:
            raise ValueError("Scope and capture anchors differ")
        if snap["created_at"] < c["captured_at"] or validate_current_policy and snap["policy"] != POLICY:
            raise ValueError("Capture clock or current policy differs")
        _validate_selection(c, snap["request"])
        safe_snapshot(snap)
        return bounded(snap)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(409, "评价冻结原件自身类型、选择闭集或安全投影无法核对") from exc


def project_snapshot(snapshot, published_metadata, *, validate_current_policy=False):
    snap = verify_snapshot(snapshot, validate_current_policy=validate_current_policy)
    safe = safe_snapshot(snap)
    value = {
        "schema_version": "satisfaction_source_v1",
        "source_id": f"satisfaction_case:{snap['case_id']}:{hash_content(snap)[:12]}",
        "case_id": snap["case_id"],
        "content_hash": hash_content(snap),
        "governance_hash": hash_content({k: published_metadata[k] for k in GOVERNANCE}),
        "collection_digest": snap["collection"]["collection_digest"],
        "safe_projection_hash": hash_content(safe),
        "safe_snapshot": safe,
    }
    return bounded(SatisfactionSource.model_validate(value).model_dump())


def preview_input(db, user, request):
    c = capture_sources(db, user, request, creating=True)
    # Temporary per-preview identity is not part of the current collection digest.
    create = {"request": c["request"], "expected_collection_digest": c["collection_digest"], "selected_excerpts": [], "basis_note": "只读完整集合预览；尚未选择或创建任何受审来源原件。"}
    snap = {
        "schema_version": "satisfaction_case_private_v1",
        "case_id": str(uuid.uuid4()),
        "created_at": utc_text(utcnow()),
        "created_by": current_actor(db, user, allowed_roles=SOURCE_ROLES).user_id,
        "identity_secret": secrets.token_hex(32),
        "request": create,
        "collection": c,
        "policy": POLICY,
    }
    safe = safe_snapshot(snap)
    return bounded(
        SafeCapture.model_validate(
            {
                "schema_version": "satisfaction_capture_safe_v1",
                "request": c["request"],
                "captured_at": c["captured_at"],
                "collection_digest": c["collection_digest"],
                "safe_snapshot": safe,
                "safe_projection_hash": hash_content(safe),
                "excerpt_options": selection_options(c),
            }
        ).model_dump()
    )


def metadata(row, *, include_private_governance=False):
    gov = {k: utc_text(getattr(row, k)) if k in {"reviewed_at", "revoked_at"} and getattr(row, k) is not None else getattr(row, k) for k in GOVERNANCE}
    value = {
        "case_id": row.case_id,
        "schema_version": row.schema_version,
        "scope_kind": row.scope_kind,
        "date_from": row.date_from.isoformat(),
        "date_to": row.date_to.isoformat(),
        "created_at": utc_text(row.created_at),
        "created_by": row.created_by,
        "content_hash": row.content_hash,
        "collection_digest": row.collection_digest,
        "source_id": f"satisfaction_case:{row.case_id}:{row.content_hash[:12]}",
        **gov,
        "governance_hash": hash_content(gov),
    }
    if not include_private_governance:
        value["review_basis_note"] = value["revoke_reason"] = None
    return value


def published_metadata(value):
    result = dict(value)
    if result["status"] not in {"published", "revoked"} or result["reviewed_at"] is None:
        raise HTTPException(409, "该原件没有可核实发布锚")
    result.update(status="published", revision=2, revoked_at=None, revoked_by=None, revoke_reason="")
    result["governance_hash"] = hash_content({k: result[k] for k in GOVERNANCE})
    return result


def case_row(db, identifier, *, locking=False):
    # Current read remains mandatory for archive access and expired JWT identities.
    row = current_satisfaction_rows(db.query(AISatisfactionCase).filter_by(case_id=identifier), shared=not locking).one_or_none()
    if row is None:
        raise HTTPException(404, "评价证据原件不存在")
    return row


def _header(db, user, identifier, *, audit_only=False, locking=False):
    actor = lock_satisfaction_write(db, user, allowed_roles=SOURCE_ROLES)
    if audit_only and actor.user_role != "super_admin":
        raise HTTPException(403, "完整冻结原文审计仅限当前超级管理员")
    # Authorize the bounded technical scope before loading any raw comment JSON.
    columns = (AISatisfactionCase.case_id, AISatisfactionCase.scope_kind, AISatisfactionCase.doctor_ids_json, AISatisfactionCase.date_from, AISatisfactionCase.date_to)
    header = current_satisfaction_rows(db.query(*columns).filter(AISatisfactionCase.case_id == identifier), shared=not locking).one_or_none()
    if header is None:
        raise HTTPException(404, "评价证据原件不存在")
    try:
        request = CaptureRequest(scope_kind=header.scope_kind, doctor_ids=json.loads(header.doctor_ids_json), date_from=header.date_from.isoformat(), date_to=header.date_to.isoformat())
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "原件技术范围头损坏") from exc
    if not audit_only:
        actor = authorize_scope(db, actor, request)
    return actor, case_row(db, identifier, locking=locking)


def case_proof(row):
    """Protected full own proof. Call only after scope authorization or internally."""
    try:
        snap = verify_snapshot(json.loads(row.snapshot_json))
        req = snap["collection"]["request"]
        if (
            hash_content(snap) != row.content_hash
            or snap["case_id"] != row.case_id
            or snap["schema_version"] != row.schema_version
            or snap["created_at"] != utc_text(row.created_at)
            or snap["created_by"] != row.created_by
            or req["scope_kind"] != row.scope_kind
            or req["date_from"] != row.date_from.isoformat()
            or req["date_to"] != row.date_to.isoformat()
            or req["doctor_ids"] != json.loads(row.doctor_ids_json)
            or snap["collection"]["collection_digest"] != row.collection_digest
        ):
            raise ValueError("Immutable server identity/hash differs")
        meta = metadata(row, include_private_governance=True)
        source = None
        if row.projection_json is not None:
            source = project_snapshot(snap, published_metadata(meta))
            if source != json.loads(row.projection_json) or hash_content(source) != row.projection_hash:
                raise ValueError("Frozen public projection differs")
        elif row.projection_hash is not None or row.status == "published" or row.status == "revoked" and row.reviewed_at is not None:
            raise ValueError("Publication projection is missing")
        return {"metadata": meta, "snapshot": snap, "public_source": source, "projection_hash": row.projection_hash}
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(409, "评价冻结原件自身完整SHA、身份或发布投影已损坏") from exc


def _current(db, actor, proof):
    req = proof["snapshot"]["collection"]["request"]
    current = capture_sources(db, actor, req)
    if current["collection_digest"] != proof["metadata"]["collection_digest"]:
        raise HTTPException(409, "完整评价、任一摘录版本、实际父链或审核身份已变化，请重新捕获")
    return current


def _postcheck(db, actor, proof, *, audit_only=False):
    fresh = current_actor(db, actor, allowed_roles=SOURCE_ROLES)
    if audit_only and fresh.user_role == "super_admin":
        return fresh
    authorize_scope(db, fresh, proof["snapshot"]["collection"]["request"])
    _current(db, fresh, proof)
    return fresh


def create_case(db, user, values):
    req = typed(CaseCreate, values)
    try:
        actor = authorize_scope(db, user, req.request, creating=True)
        c = capture_sources(db, actor, req.request, creating=True, locking=True)
        if c["collection_digest"] != req.expected_collection_digest:
            raise HTTPException(409, "完整当前集合已变化，请重新预览后明确选择")
        _validate_selection(c, req.model_dump())
        snap = verify_snapshot(
            {
                "schema_version": "satisfaction_case_private_v1",
                "case_id": str(uuid.uuid4()),
                "created_at": utc_text(utcnow()),
                "created_by": actor.user_id,
                "identity_secret": secrets.token_hex(32),
                "request": req.model_dump(),
                "collection": c,
                "policy": POLICY,
            },
            validate_current_policy=True,
        )
        row = AISatisfactionCase(
            case_id=snap["case_id"],
            schema_version=snap["schema_version"],
            scope_kind=req.request.scope_kind,
            doctor_ids_json=canonical_json(req.request.doctor_ids),
            date_from=datetime.date.fromisoformat(req.request.date_from),
            date_to=datetime.date.fromisoformat(req.request.date_to),
            created_at=datetime.datetime.strptime(snap["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ"),
            created_by=actor.user_id,
            snapshot_json=canonical_json(snap),
            content_hash=hash_content(snap),
            collection_digest=c["collection_digest"],
            status="draft",
            revision=1,
            review_basis_note="",
            revoke_reason="",
        )
        db.add(row)
        db.flush()
        audit(db, actor.user_id, "satisfaction_case.create", row.case_id, {"content_hash": row.content_hash, "collection_digest": row.collection_digest})
        db.flush()
        proof = case_proof(row)
        _postcheck(db, actor, proof)
        authorize_scope(db, actor, req.request, creating=True)
        db.commit()
        return case_current(db, actor, row.case_id)
    except Exception:
        db.rollback()
        raise


def case_current(db, user, identifier, *, audit_only=False, execution=False):
    actor, row = _header(db, user, identifier, audit_only=audit_only)
    proof = case_proof(row)  # Own damaged bytes never become redacted-success or Super bypass.
    reasons = []
    if row.status != "published":
        reasons.append("case_not_published")
    try:
        _current(db, actor, proof)
    except HTTPException as exc:
        if exc.status_code not in (403, 409):
            raise
        reasons.append("current_collection_or_scope_changed")
    if execution and proof["snapshot"]["policy"] != POLICY:
        reasons.append("current_projection_policy_changed")
    visible = audit_only or row.status in {"draft", "published"} and "current_collection_or_scope_changed" not in reasons
    safe = safe_snapshot(proof["snapshot"]) if visible else None
    return CaseWrapper.model_validate(
        {
            **metadata(row, include_private_governance=audit_only),
            "snapshot": proof["snapshot"] if audit_only else None,
            "safe_snapshot": safe,
            "safe_projection_hash": hash_content(safe) if safe is not None else None,
            "public_source": proof["public_source"] if visible else None,
            "projection_hash": row.projection_hash,
            "parent_current": "current_collection_or_scope_changed" not in reasons,
            "eligible": not reasons,
            "exclusion_reasons": reasons,
            "can_record": False,
            "can_review": actor.user_role == "super_admin" and row.status == "draft" and "current_collection_or_scope_changed" not in reasons,
            "can_revoke": (actor.user_role == "super_admin" or actor.user_id == row.created_by and "current_collection_or_scope_changed" not in reasons) and row.status in {"draft", "published"},
            "audit_only": audit_only,
            "raw_content_hash_verification": "protected_full_original_verified_server_side_not_reconstructible_from_safe_view",
        }
    ).model_dump()


def review_case(db, user, identifier, values):
    req = typed(SourceReview, values)
    try:
        actor = lock_satisfaction_write(db, user, allowed_roles={"super_admin"})
        row = case_row(db, identifier, locking=True)
        proof = case_proof(row)
        if row.status != "draft" or row.revision != req.expected_revision:
            raise HTTPException(409, "原件状态或审核版本已变化")
        _current(db, actor, proof)
        now = utcnow()
        gov = {
            "status": "published" if req.decision == "publish" else "rejected",
            "revision": 2,
            "reviewed_at": utc_text(now),
            "reviewed_by": actor.user_id,
            "review_basis_note": req.basis_note,
            "revoked_at": None,
            "revoked_by": None,
            "revoke_reason": "",
        }
        source = project_snapshot(proof["snapshot"], gov, validate_current_policy=True) if req.decision == "publish" else None
        changed = (
            db.query(AISatisfactionCase)
            .filter_by(case_id=identifier, status="draft", revision=req.expected_revision)
            .update(
                {
                    "status": gov["status"],
                    "revision": 2,
                    "reviewed_at": now,
                    "reviewed_by": actor.user_id,
                    "review_basis_note": req.basis_note,
                    "projection_json": canonical_json(source) if source else None,
                    "projection_hash": hash_content(source) if source else None,
                },
                synchronize_session=False,
            )
        )
        if changed != 1:
            raise HTTPException(409, "审核CAS冲突")
        audit(db, actor.user_id, "satisfaction_case.review", identifier, {"decision": req.decision, "revision": 2, "content_hash": row.content_hash})
        db.flush()
        fresh = current_actor(db, actor, allowed_roles={"super_admin"})
        _postcheck(db, fresh, proof)
        case_proof(case_row(db, identifier, locking=True))
        db.commit()
        return case_current(db, fresh, identifier, audit_only=True)
    except Exception:
        db.rollback()
        raise


def revoke_case(db, user, identifier, values):
    req = typed(SourceRevoke, values)
    try:
        actor = lock_satisfaction_write(db, user, allowed_roles=SOURCE_ROLES)
        actor, row = _header(db, actor, identifier, audit_only=actor.user_role == "super_admin", locking=True)
        # A Super may revoke a valid own-frozen case after live scope disappears.
        proof = case_proof(row)
        if actor.user_role != "super_admin" and actor.user_id != row.created_by:
            raise HTTPException(403, "仅创建者或超级管理员可撤销原件")
        if row.status not in {"draft", "published"} or row.revision != req.expected_revision:
            raise HTTPException(409, "原件状态或撤销版本已变化")
        if actor.user_role != "super_admin":
            _current(db, actor, proof)
        changed = (
            db.query(AISatisfactionCase)
            .filter_by(case_id=identifier, status=row.status, revision=req.expected_revision)
            .update({"status": "revoked", "revision": req.expected_revision + 1, "revoked_at": utcnow(), "revoked_by": actor.user_id, "revoke_reason": req.basis_note}, synchronize_session=False)
        )
        if changed != 1:
            raise HTTPException(409, "撤销CAS冲突")
        audit(db, actor.user_id, "satisfaction_case.revoke", identifier, {"revision": req.expected_revision + 1, "content_hash": row.content_hash})
        db.flush()
        fresh = _postcheck(db, actor, proof, audit_only=actor.user_role == "super_admin")
        case_proof(case_row(db, identifier, locking=True))
        db.commit()
        return case_current(db, fresh, identifier, audit_only=fresh.user_role == "super_admin")
    except Exception:
        db.rollback()
        raise


def binding_for(row, source):
    return {
        "case_id": row.case_id,
        "revision": 2,
        "source_id": source["source_id"],
        "content_hash": source["content_hash"],
        "case_governance_hash": source["governance_hash"],
        "projection_hash": hash_content(source),
        "collection_digest": source["collection_digest"],
        "safe_projection_hash": source["safe_projection_hash"],
        "member_manifest_hash": source["safe_snapshot"]["member_manifest_hash"],
        "scope_kind": row.scope_kind,
        "date_from": row.date_from.isoformat(),
        "date_to": row.date_to.isoformat(),
    }


def authorize_case(db, user, identifier, *, binding=None, locking=False, execution=True):
    actor, row = _header(db, user, identifier, locking=locking)
    proof = case_proof(row)
    if row.status != "published":
        raise HTTPException(409, "原件当前未发布")
    _current(db, actor, proof)
    if execution and proof["snapshot"]["policy"] != POLICY:
        raise HTTPException(409, "冻结安全投影政策不是当前执行版本")
    source = proof["public_source"]
    if binding is not None and binding != binding_for(row, source):
        raise HTTPException(409, "任务绑定与原始完整来源不一致")
    return row, proof["snapshot"], source


def frozen_case_proof(db, identifier):
    """Internal safe task proof after caller authorization. Never returns protected JSON."""
    row = case_row(db, identifier)
    proof = case_proof(row)
    safe = safe_snapshot(proof["snapshot"])
    return {
        **metadata(row),
        "snapshot": None,
        "safe_snapshot": safe,
        "safe_projection_hash": hash_content(safe),
        "public_source": proof["public_source"],
        "projection_hash": row.projection_hash,
        "frozen_task_view": True,
        "can_record": False,
        "can_review": False,
        "can_revoke": False,
        "raw_content_hash_verification": "protected_full_original_verified_server_side_not_reconstructible_from_safe_view",
    }
