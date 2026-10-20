"""Complete current staffing capture and deterministic private-to-public projection."""

import copy
import datetime
import uuid
from types import SimpleNamespace
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import AfterValidator, Field, ValidationError, field_validator, model_validator

from app.ai import roster_contract as core
from app.ai import roster_facts as facts
from app.ai.roster_models import AIRosterSource
from app.models import Doctor

SCHEMA_VERSION = "roster_plan_private_v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_FACTS = core.MAX_INTERVALS
MAX_STAFF = core.MAX_STAFF
MAX_SESSIONS = core.MAX_SESSIONS
MAX_OPTIONS = core.MAX_OPTIONS


def utcnow():
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def local_date(value):
    if not isinstance(value, str) or str(datetime.date.fromisoformat(value)) != value or len(value) != 10:
        raise ValueError("Canonical YYYY-MM-DD business date required")
    return value


LocalDate = Annotated[str, AfterValidator(local_date)]
Basis = Annotated[str, Field(min_length=20, max_length=4000)]


def meaningful_basis(value):
    if len("".join(value.split())) < 20:
        raise ValueError("An explicit basis requires at least 20 non-whitespace characters")
    return value


class CoverageDeclaration(facts.StrictInput):
    status: Literal["attested_complete", "incomplete", "unknown"]
    basis: Basis
    _basis = field_validator("basis")(meaningful_basis)


class DutyCoverage(core.Interval):
    status: Literal["attested_complete", "incomplete", "unknown"]
    basis: Basis
    _basis = field_validator("basis")(meaningful_basis)


class StaffDeclaration(facts.StrictInput):
    doctor_id: facts.PositiveInteger
    all_locations_duty_coverage: DutyCoverage


class SessionDeclaration(core.Interval):
    session_key: facts.CanonicalId
    business_date: LocalDate
    required_job_key: facts.JobKey
    minimum_staff: int = Field(ge=0, le=MAX_STAFF)
    maximum_staff: int = Field(ge=0, le=MAX_STAFF)
    required_slots: core.ConstraintValue
    facility_slot_ceiling: core.ConstraintValue
    requirements_basis: Basis
    capacity_basis: Basis
    _basis = field_validator("requirements_basis", "capacity_basis")(meaningful_basis)

    @model_validator(mode="after")
    def staff_bounds(self):
        if self.minimum_staff > self.maximum_staff:
            raise ValueError("Session minimum staff cannot exceed its maximum")
        return self


class OptionDeclaration(facts.StrictInput):
    doctor_id: facts.PositiveInteger
    session_key: facts.CanonicalId
    cost_points: core.ConstraintValue
    slot_capacity: core.ConstraintValue
    breaks: list[core.RosterBreak] = Field(max_length=256)
    breaks_complete: bool
    time_accounting_status: Literal["verified", "unknown"]
    basis: Basis
    _basis = field_validator("basis")(meaningful_basis)


class SubmittedAssignment(facts.StrictInput):
    doctor_id: facts.PositiveInteger
    session_key: facts.CanonicalId


class PlanRequest(facts.StrictInput):
    department_id: facts.PositiveInteger
    date_from: LocalDate
    date_to: LocalDate
    business_timezone: str = Field(min_length=1, max_length=80)
    objective_mode: core.ObjectiveMode
    personnel_coverage: CoverageDeclaration
    session_requirements_coverage: CoverageDeclaration
    staff: list[StaffDeclaration] = Field(max_length=MAX_STAFF)
    sessions: list[SessionDeclaration] = Field(max_length=MAX_SESSIONS)
    options: list[OptionDeclaration] = Field(max_length=MAX_OPTIONS)
    submitted_candidate: list[SubmittedAssignment] | None = Field(max_length=MAX_OPTIONS)

    @field_validator("business_timezone")
    @classmethod
    def real_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Actual IANA business timezone required") from exc
        return value

    @model_validator(mode="after")
    def complete_cartesian_options(self):
        first, last = datetime.date.fromisoformat(self.date_from), datetime.date.fromisoformat(self.date_to)
        if not 1 <= (last - first).days + 1 <= 31:
            raise ValueError("The complete business-date interval must contain 1 to 31 consecutive days")
        people = {item.doctor_id for item in self.staff}
        sessions = {item.session_key: item for item in self.sessions}
        if len(people) != len(self.staff) or len(sessions) != len(self.sessions):
            raise ValueError("Repeated staff or session identity")
        expected = {(doctor_id, session_key) for doctor_id in people for session_key in sessions}
        options = {(item.doctor_id, item.session_key) for item in self.options}
        if len(expected) > MAX_OPTIONS or len(options) != len(self.options) or options != expected:
            raise ValueError("Every staff/session pair requires exactly one explicit option, without truncation")
        start, end, dates = period_bounds(self)
        zone = ZoneInfo(self.business_timezone)
        for session in self.sessions:
            if session.start_at < start or session.end_at > end or session.business_date not in dates or str(facts.instant(session.start_at).astimezone(zone).date()) != session.business_date:
                raise ValueError("Session UTC clocks, business date and complete planning interval differ")
        for option in self.options:
            session = sessions[option.session_key]
            core.DutyAccounting(start_at=session.start_at, end_at=session.end_at, breaks=option.breaks, breaks_complete=option.breaks_complete, time_accounting_status=option.time_accounting_status)
        if self.submitted_candidate is not None:
            selected = {(item.doctor_id, item.session_key) for item in self.submitted_candidate}
            if len(selected) != len(self.submitted_candidate) or not selected <= expected:
                raise ValueError("Submitted candidate must refer to unique declared options")
        if len(facts.canonical_json(self.model_dump(mode="json")).encode()) > MAX_BYTES:
            raise ValueError("Complete private request exceeds the UTF-8 bound")
        return self


def period_bounds(request):
    zone = ZoneInfo(request.business_timezone)
    first, last = datetime.date.fromisoformat(request.date_from), datetime.date.fromisoformat(request.date_to)
    dates = [str(first + datetime.timedelta(days=index)) for index in range((last - first).days + 1)]

    def midnight(day):
        wall = datetime.datetime.combine(day, datetime.time.min, tzinfo=zone)
        utc = wall.astimezone(datetime.UTC)
        if utc.astimezone(zone).date() != day or utc.astimezone(zone).time().replace(tzinfo=None) != datetime.time.min:
            raise ValueError("This business boundary has no real local midnight; it cannot be silently shifted")
        return facts.utc_text(utc)

    try:
        return midnight(first), midnight(last + datetime.timedelta(days=1)), dates
    except OverflowError as exc:
        raise ValueError("Business-date midnights and the exclusive end must fit the supported UTC range") from exc


def typed_request(value, *, stored=False):
    try:
        return value if isinstance(value, PlanRequest) else PlanRequest.model_validate(value)
    except (ValidationError, ValueError, TypeError, RecursionError) as exc:
        raise HTTPException(409 if stored else 422, "排班场景的完整人员、日期、选项、原量或明确依据不符合契约") from exc


def validate_planning_period(request, *, now=None):
    request = typed_request(request)
    now = utcnow() if now is None else now
    today = facts.instant(facts.utc_text(now)).astimezone(ZoneInfo(request.business_timezone)).date()
    first, last = datetime.date.fromisoformat(request.date_from), datetime.date.fromisoformat(request.date_to)
    if first < today or last > today + datetime.timedelta(days=366):
        raise HTTPException(422, "新规划须从当前业务日期起，且结束日期不超过当前日期后366天")
    return period_bounds(request)


def _manifest_item(record):
    keys = (*facts.IDENTITY_FIELDS, "source_id", "content_hash", "governance_hash", "status", "revision", "parent_current", "eligible", "exclusion_reasons")
    return {key: copy.deepcopy(record[key]) for key in keys}


def _collection_digest(cohort, manifest):
    return facts.hash_content({"cohort": cohort, "fact_manifest": manifest})


def current_collection(db, user, department_id, *, locking=False):
    """Date-independent live closed collection; do not rewrite a historical cutoff."""
    actor = facts.roster_scope(db, user, department_id, locking=locking)
    cohort_query = db.query(Doctor.doctor_id, Doctor.department_id).filter(Doctor.department_id == department_id).order_by(Doctor.doctor_id).limit(MAX_STAFF + 1)
    rows = facts.current_query(cohort_query, locking=locking).all()
    if len(rows) > MAX_STAFF:
        raise HTTPException(422, "完整科室人员集合超过容量，不得截断为部分候选")
    cohort = [{"doctor_id": row.doctor_id, "department_id": row.department_id} for row in rows]
    original_query = db.query(AIRosterSource).filter_by(department_id=department_id).order_by(AIRosterSource.source_record_id).limit(MAX_FACTS + 1)
    originals = facts.current_query(original_query, locking=locking).all()
    if len(originals) > MAX_FACTS:
        raise HTTPException(422, "完整原来源集合超过容量，不得仅选择已发布或最新原件")
    # Explicitly refuse audit_only even for a Super-created problem. Stale
    # personnel notes cannot enter a new scenario through administrative access.
    records = [facts.source_current(db, actor, row.source_kind, row.source_record_id, audit_only=False, locking=locking) for row in originals]
    manifest = [_manifest_item(record) for record in records]
    result = {"department_id": department_id, "cohort": cohort, "fact_manifest": manifest, "facts": records, "collection_digest": _collection_digest(cohort, manifest)}
    if len(facts.canonical_json(result).encode()) > MAX_BYTES:
        raise HTTPException(422, "完整来源集合超过字节容量，不得截断正文或失效原件清单")
    return result


def _require_cohort(request, collection):
    if {item.doctor_id for item in request.staff} != {item["doctor_id"] for item in collection["cohort"]}:
        raise HTTPException(409, "声明人员必须恰好覆盖当前科室全部Doctor，包括没有周期排班的人员")


def preview_input(db, user, request):
    request = typed_request(request)
    start, end, dates = validate_planning_period(request)
    collection = current_collection(db, user, request.department_id)
    _require_cohort(request, collection)
    return {
        key: value
        for key, value in {
            **collection,
            "planning_start_at": start,
            "planning_end_at": end,
            "business_dates": dates,
            "capture_mode": "current_capture",
            "capacity_basis": "declared_scenario_capacity_not_live_bookable_inventory",
        }.items()
        if key != "facts"
    }


def _mapping(problem_id, cohort, request):
    namespace = uuid.UUID(problem_id)
    return {
        "staff": {str(item["doctor_id"]): str(uuid.uuid5(namespace, str(item["doctor_id"]))) for item in cohort},
        "sessions": {item.session_key: str(uuid.uuid5(namespace, item.session_key)) for item in request.sessions},
        "options": {f"{item.doctor_id}:{item.session_key}": str(uuid.uuid5(namespace, f"{item.doctor_id}:{item.session_key}")) for item in request.options},
    }


def capture_input(db, user, request, problem_id, *, expected_collection_digest=None):
    request = typed_request(request)
    try:
        problem_id = facts.canonical_id(problem_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "场景标识须为规范UUID") from exc
    now = utcnow()
    start, end, dates = validate_planning_period(request, now=now)
    actor = facts.roster_scope(db, user, request.department_id)
    collection = current_collection(db, actor, request.department_id)
    _require_cohort(request, collection)
    if expected_collection_digest is not None and expected_collection_digest != collection["collection_digest"]:
        raise HTTPException(409, "完整人员或原来源集合已改变，请重新预览并逐项核对")
    clock = facts.utc_text(now)
    if any(record["recorded_at"] > clock for record in collection["facts"]):
        raise HTTPException(409, "原来源登记时刻晚于本次服务器捕获时刻，不能伪作已可用依据")
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "problem_id": problem_id,
        "department_id": request.department_id,
        "created_by": actor.user_id,
        "as_of": clock,
        "captured_at": clock,
        "capture_mode": "current_capture",
        "request": request.model_dump(mode="json"),
        "collection_digest": collection["collection_digest"],
        "cohort": collection["cohort"],
        "facts": collection["facts"],
        "fact_manifest": collection["fact_manifest"],
        "mapping": _mapping(problem_id, collection["cohort"], request),
        "planning_start_at": start,
        "planning_end_at": end,
        "business_dates": dates,
        "scope_binding_hash": facts.hash_content({"department_id": request.department_id, "cohort": collection["cohort"]}),
        "manifest_digest": facts.hash_content(collection["fact_manifest"]),
        "algorithm": {
            "rule_id": core.RULE_ID,
            "recipe": copy.deepcopy(core.RECIPE),
            "recipe_digest": core.recipe_digest(),
            "input_policy": copy.deepcopy(core.INPUT_POLICY),
            "input_policy_digest": core.input_policy_digest(),
        },
    }
    verify_snapshot(snapshot)
    return snapshot


def _validate_frozen_fact(record):
    expected = (
        set(facts.IDENTITY_FIELDS)
        | set(facts.GOVERNANCE_FIELDS)
        | {
            "source_id",
            "content_hash",
            "governance_hash",
            "payload",
            "parent_binding",
            "parent_current",
            "eligible",
            "exclusion_reasons",
            "can_record",
            "can_review",
            "can_revoke",
            "audit_only",
            "eligibility_basis",
        }
    )
    if not isinstance(record, dict) or set(record) != expected:
        raise ValueError("Unexpected frozen original wrapper fields")
    core.RosterFactRef.model_validate(
        {"kind": record["source_kind"], **{key: record[key] for key in ("source_record_id", "source_id", "content_hash", "governance_hash", "status", "revision", "recorded_at")}}
    )
    facts.FrozenIdentity.model_validate({key: record[key] for key in facts.IDENTITY_FIELDS})
    if record["audit_only"] is not False or type(record["parent_current"]) is not bool or type(record["eligible"]) is not bool:
        raise ValueError("A scenario cannot capture a privileged audit as current facts")
    if (
        record["eligible"] != (record["status"] == "published" and record["parent_current"])
        or not isinstance(record["exclusion_reasons"], list)
        or record["eligible"] != (not record["exclusion_reasons"])
    ):
        raise ValueError("Frozen eligibility differs from original governance and parent state")
    if record["payload"] is None:
        if record["eligible"] or record["parent_binding"] is not None or record["review_basis_note"] is not None or record["revoke_reason"] is not None:
            raise ValueError("Excluded private notes must remain explicitly redacted")
        return
    if not record["parent_current"] or record["status"] not in {"draft", "published"}:
        raise ValueError("An excluded original must not restore personnel notes")
    fields = {key: record[key] for key in (*facts.IDENTITY_FIELDS, "content_hash", *facts.GOVERNANCE_FIELDS)}
    for key in ("recorded_at", "reviewed_at", "revoked_at"):
        fields[key] = facts.instant(fields[key]).replace(tzinfo=None) if fields[key] is not None else None
    fields.update(payload_json=facts.canonical_json(record["payload"]), parent_binding_json=facts.canonical_json(record["parent_binding"]))
    facts.source_proof(SimpleNamespace(**fields))
    if facts.hash_content({key: record[key] for key in facts.GOVERNANCE_FIELDS}) != record["governance_hash"]:
        raise ValueError("Complete frozen governance hash differs")


def verify_snapshot(snapshot, *, validate_current_recipe=False):
    """Verify frozen self-consistency without today's planning boundary or DB reads."""
    try:
        expected = {
            "schema_version",
            "problem_id",
            "department_id",
            "created_by",
            "as_of",
            "captured_at",
            "capture_mode",
            "request",
            "collection_digest",
            "cohort",
            "facts",
            "fact_manifest",
            "mapping",
            "planning_start_at",
            "planning_end_at",
            "business_dates",
            "scope_binding_hash",
            "manifest_digest",
            "algorithm",
        }
        if not isinstance(snapshot, dict) or set(snapshot) != expected or snapshot["schema_version"] != SCHEMA_VERSION or snapshot["capture_mode"] != "current_capture":
            raise ValueError("Unexpected private snapshot shape/version")
        if len(facts.canonical_json(snapshot).encode()) > MAX_BYTES:
            raise ValueError("Complete snapshot exceeds UTF-8 capacity")
        facts.canonical_id(snapshot["problem_id"])
        request = typed_request(snapshot["request"], stored=True)
        if type(snapshot["created_by"]) is not int or snapshot["created_by"] < 1 or snapshot["department_id"] != request.department_id:
            raise ValueError("Private author/department differs")
        core.utc(snapshot["as_of"])
        core.utc(snapshot["captured_at"])
        if snapshot["as_of"] > snapshot["captured_at"]:
            raise ValueError("Original availability cutoff follows capture")
        cohort = snapshot["cohort"]
        if not isinstance(cohort, list) or len(cohort) > MAX_STAFF:
            raise ValueError("Invalid complete cohort")
        for item in cohort:
            facts.DoctorBinding.model_validate(item)
            if item["department_id"] != request.department_id:
                raise ValueError("Cohort contains another department")
        if cohort != sorted(cohort, key=lambda item: item["doctor_id"]) or len({item["doctor_id"] for item in cohort}) != len(cohort):
            raise ValueError("Cohort order/identity differs")
        _require_cohort(request, snapshot)
        records = snapshot["facts"]
        if not isinstance(records, list) or len(records) > MAX_FACTS or len({item["source_record_id"] for item in records}) != len(records):
            raise ValueError("Fact collection is duplicated or oversized")
        if records != sorted(records, key=lambda item: item["source_record_id"]):
            raise ValueError("Fact collection is not deterministic")
        for record in records:
            _validate_frozen_fact(record)
            if record["department_id"] != request.department_id or record["recorded_at"] > snapshot["as_of"]:
                raise ValueError("Fact outside original scope or cutoff")
            if record["eligible"] and record["doctor_id"] is not None and record["doctor_id"] not in {item["doctor_id"] for item in cohort}:
                raise ValueError("Current eligible fact references a person outside the closed cohort")
        manifest = [_manifest_item(record) for record in records]
        if snapshot["fact_manifest"] != manifest or snapshot["collection_digest"] != _collection_digest(cohort, manifest) or snapshot["manifest_digest"] != facts.hash_content(manifest):
            raise ValueError("Complete manifest or its digest differs")
        if snapshot["mapping"] != _mapping(snapshot["problem_id"], cohort, request) or snapshot["scope_binding_hash"] != facts.hash_content({"department_id": request.department_id, "cohort": cohort}):
            raise ValueError("Private identity mapping or scope binding differs")
        if (snapshot["planning_start_at"], snapshot["planning_end_at"], snapshot["business_dates"]) != period_bounds(request):
            raise ValueError("Frozen local dates and UTC midnights differ")
        algorithm = snapshot["algorithm"]
        if set(algorithm) != {"rule_id", "recipe", "recipe_digest", "input_policy", "input_policy_digest"} or algorithm["rule_id"] != core.RULE_ID:
            raise ValueError("Frozen algorithm identity differs")
        if (
            facts.hash_content(algorithm["recipe"]) != algorithm["recipe_digest"]
            or facts.hash_content(algorithm["input_policy"]) != algorithm["input_policy_digest"]
            or algorithm["recipe"].get("input_policy") != algorithm["input_policy"]
        ):
            raise ValueError("Frozen algorithm/policy content differs from its own digest")
        if validate_current_recipe and (algorithm["recipe_digest"] != core.recipe_digest() or algorithm["input_policy_digest"] != core.input_policy_digest()):
            raise ValueError("Frozen algorithm/policy differs from current implementation")
        return snapshot
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError, ValidationError, HTTPException) as exc:
        raise HTTPException(409, "排班场景的完整冻结请求、原来源、身份映射、时刻或算法绑定不一致") from exc


def _fact_ref(record):
    return {"kind": record["source_kind"], **{key: record[key] for key in ("source_record_id", "source_id", "content_hash", "governance_hash", "status", "revision", "recorded_at")}}


def _public_fact(record):
    payload = copy.deepcopy(record["payload"])
    payload["basis_hash"] = facts.hash_content(payload.pop("evidence_basis_note"))
    payload["ref"] = _fact_ref(record)
    if record["source_kind"] == "qualification":
        payload["authorized_job_hashes"] = [facts.hash_content(key) for key in payload.pop("authorized_job_keys")]
    elif record["source_kind"] == "duty_interval":
        key = payload.pop("job_key")
        payload["job_key_hash"] = facts.hash_content(key) if key is not None else None
    elif record["source_kind"] == "work_rule_policy":
        payload["policy_reference_hash"] = facts.hash_content(payload.pop("policy_reference"))
    return payload


def project_source(snapshot, governance_hash, *, validate_current_recipe=True):
    verify_snapshot(snapshot, validate_current_recipe=validate_current_recipe)
    try:
        if not isinstance(governance_hash, str) or len(governance_hash) != 64 or any(char not in "0123456789abcdef" for char in governance_hash):
            raise ValueError("Complete problem governance digest required")
        request = typed_request(snapshot["request"], stored=True)
        mapping = snapshot["mapping"]
        staff = []
        coverage = {item.doctor_id: item.all_locations_duty_coverage for item in request.staff}
        eligible = [record for record in snapshot["facts"] if record["eligible"]]
        for member in snapshot["cohort"]:
            doctor_id = member["doctor_id"]
            declared = coverage[doctor_id].model_dump(mode="json")
            declared["basis_hash"] = facts.hash_content(declared.pop("basis"))
            owned = [record for record in eligible if record["doctor_id"] == doctor_id]
            staff.append(
                {
                    "staff_id": mapping["staff"][str(doctor_id)],
                    "identity_binding_hash": facts.hash_content(member),
                    "qualifications": [_public_fact(record) for record in owned if record["source_kind"] == "qualification"],
                    "duties": [_public_fact(record) for record in owned if record["source_kind"] == "duty_interval"],
                    "availability": [_public_fact(record) for record in owned if record["source_kind"] == "availability"],
                    "all_locations_duty_coverage": declared,
                }
            )
        sessions = []
        for item in request.sessions:
            session = item.model_dump(mode="json")
            session["session_id"] = mapping["sessions"][session.pop("session_key")]
            session["required_job_hash"] = facts.hash_content(session.pop("required_job_key"))
            session["requirements_basis_hash"] = facts.hash_content(session.pop("requirements_basis"))
            session["capacity_basis_hash"] = facts.hash_content(session.pop("capacity_basis"))
            sessions.append(session)
        options = []
        for item in request.options:
            option = item.model_dump(mode="json")
            doctor_id, session_key = option.pop("doctor_id"), option.pop("session_key")
            option.update(
                option_id=mapping["options"][f"{doctor_id}:{session_key}"],
                staff_id=mapping["staff"][str(doctor_id)],
                session_id=mapping["sessions"][session_key],
                basis_hash=facts.hash_content(option.pop("basis")),
            )
            options.append(option)
        policies = [_public_fact(record) for record in eligible if record["source_kind"] == "work_rule_policy" and staff]
        for policy in policies:
            policy["applicable_staff_ids"] = [item["staff_id"] for item in staff]
        digest = facts.hash_content(snapshot)
        result = {
            "schema_version": "roster_source_v1",
            "problem_id": snapshot["problem_id"],
            "source_id": f"roster_problem:{snapshot['problem_id']}:{digest[:12]}",
            "content_hash": digest,
            "problem_governance_hash": governance_hash,
            "scope_binding_hash": snapshot["scope_binding_hash"],
            "manifest_digest": snapshot["manifest_digest"],
            "rule_id": snapshot["algorithm"]["rule_id"],
            "recipe_digest": snapshot["algorithm"]["recipe_digest"],
            "input_policy_digest": snapshot["algorithm"]["input_policy_digest"],
            "objective_mode": request.objective_mode,
            "planning_start_at": snapshot["planning_start_at"],
            "planning_end_at": snapshot["planning_end_at"],
            "business_timezone": request.business_timezone,
            "business_dates": snapshot["business_dates"],
            "as_of": snapshot["as_of"],
            "captured_at": snapshot["captured_at"],
            "capture_mode": "current_capture",
            "personnel_coverage": request.personnel_coverage.status,
            "personnel_coverage_basis_hash": facts.hash_content(request.personnel_coverage.basis),
            "session_requirements_coverage": request.session_requirements_coverage.status,
            "session_requirements_coverage_basis_hash": facts.hash_content(request.session_requirements_coverage.basis),
            "work_policies": policies,
            "staff": staff,
            "sessions": sessions,
            "options": options,
            "submitted_candidate": None if request.submitted_candidate is None else [mapping["options"][f"{item.doctor_id}:{item.session_key}"] for item in request.submitted_candidate],
        }
        if len(facts.canonical_json(result).encode()) > MAX_BYTES:
            raise ValueError("Complete public problem exceeds UTF-8 capacity")
        return core.RosterSource.model_validate(result).model_dump(mode="json") if validate_current_recipe else result
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise HTTPException(409, "无法按完整冻结原量构建该排班算法的公开投影") from exc
