"""Frozen, explicitly timed admission observations; no inferred clinical scores."""

import datetime
import hashlib
import json
import uuid
from collections import defaultdict

from fastapi import HTTPException

from app.ai.models import AIObservationWindow, utcnow
from app.config import settings
from app.models import Admission, Patient

WINDOW_ROLES = {"nurse", "doctor", "director", "admin", "super_admin"}
RISK_FEATURES = {41, 42, 43}
MEASUREMENTS = ("heart_rate", "pulse_rate", "respiratory_rate", "systolic_bp", "diastolic_bp", "temperature", "spo2", "body_weight", "oxygen_flow", "fio2")
MAX_ROWS = 1000
SCHEMA_VERSION = "inpatient_window_v1"


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def content_hash(value):
    return hashlib.sha256(canonical_json({key: item for key, item in value.items() if key not in {"source_id", "content_hash"}}).encode()).hexdigest()


def iso(value):
    return value.replace(tzinfo=datetime.UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_id(value):
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise HTTPException(422, "观测窗与住院标识须为规范UUID")
    return value


def authorize_scope(db, user, patient_id, admission_id):
    from app.inpatient_observations import authorize_observation_admission

    return authorize_observation_admission(db, user, patient_id, admission_id)


def _point_quality(points, start, end):
    active = [item for item in points if item["status"] == "active"]
    groups = defaultdict(list)
    missing = []
    for item in active:
        measures = item["payload"]["measurements"]
        missing.append(
            {
                "source_id": item["source_id"],
                "not_recorded": [key for key in MEASUREMENTS if key not in measures],
                "explicitly_unmeasured": [key for key, value in measures.items() if value["value"] is None],
            }
        )
        for key, value in measures.items():
            groups[(item["observed_at"], key)].append((item["source_id"], value))
        for key in ("supplemental_oxygen", "consciousness", "oxygen_device"):
            groups[(item["observed_at"], key)].append((item["source_id"], item["payload"].get(key)))
    conflicts = []
    for (observed, key), values in sorted(groups.items()):
        if len(values) > 1:
            conflicts.append(
                {
                    "observed_at": observed,
                    "measurement_code": key,
                    "source_ids": [item[0] for item in values],
                    "state": "duplicate_same_value" if len({canonical_json(item[1]) for item in values}) == 1 else "conflicting_values_or_missing_state",
                }
            )
    gaps = []
    for key in MEASUREMENTS:
        times = sorted(
            {
                datetime.datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00")).replace(tzinfo=None)
                for item in active
                if item["payload"]["measurements"].get(key, {}).get("value") is not None
            }
        )
        gaps.append(
            {
                "measurement_code": key,
                "unique_numeric_observation_times": len(times),
                "first_at": iso(times[0]) if times else None,
                "last_at": iso(times[-1]) if times else None,
                "max_observed_gap_seconds": max(((right - left).total_seconds() for left, right in zip(times, times[1:])), default=None),
                "leading_gap_seconds": (times[0] - start).total_seconds() if times else None,
                "trailing_gap_seconds": (end - times[-1]).total_seconds() if times else None,
            }
        )
    return {"missing_by_point": missing, "same_time_groups": conflicts, "measurement_gaps": gaps, "continuous_monitoring_confirmed": False, "sampling_completeness": "not_verified"}


def _urine_quality(rows, start, end):
    def clock(value):
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)

    active = sorted([item for item in rows if item["status"] == "active"], key=lambda item: (item["start_at"], item["interval_id"]))
    components, group, maximum = [], [], None
    for item in active:
        begin, finish = clock(item["start_at"]), clock(item["end_at"])
        if group and begin >= maximum:
            if len(group) > 1:
                components.append(group)
            group, maximum = [], None
        group.append(item)
        maximum = finish if maximum is None else max(maximum, finish)
    if len(group) > 1:
        components.append(group)
    overlap_ids = {item["interval_id"] for group in components for item in group}
    excluded, covered = [], []
    for item in rows:
        reasons = []
        payload = item["payload"]
        if item["status"] != "active":
            reasons.append("revoked")
        if clock(item["start_at"]) < start or clock(item["end_at"]) > end:
            reasons.append("crosses_window_boundary_no_proration")
        if payload["collection_completeness"] != "complete":
            reasons.append("collection_not_complete")
        if payload["patient_total"] is not True:
            reasons.append("not_confirmed_patient_total")
        if payload["volume_ml"] is None:
            reasons.append("volume_not_measured")
        if item["interval_id"] in overlap_ids:
            reasons.append("overlapping_intervals")
        if reasons:
            excluded.append({"source_id": item["source_id"], "reasons": reasons})
        else:
            covered.append({"source_id": item["source_id"], "start_at": item["start_at"], "end_at": item["end_at"]})
    covered.sort(key=lambda item: item["start_at"])
    cursor, gaps = start, []
    for item in covered:
        begin, finish = clock(item["start_at"]), clock(item["end_at"])
        if cursor < begin:
            gaps.append({"start_at": iso(cursor), "end_at": iso(begin)})
        cursor = max(cursor, finish)
    if cursor < end:
        gaps.append({"start_at": iso(cursor), "end_at": iso(end)})
    return {
        "interval_semantics": "[start,end)",
        "overlap_group_semantics": "connected_overlap_component",
        "overlap_groups": [{"source_ids": [item["source_id"] for item in group]} for group in components],
        "excluded_intervals": excluded,
        "eligible_coverage_intervals": covered,
        "uncovered_intervals": gaps,
        "volume_aggregation_performed": False,
        "rate_calculation_performed": False,
    }


def build_snapshot(db, *, window_id, patient_id, admission_id, created_by, created_at, start_at, end_at, as_of):
    from app.ai.context import minimize_identifiers
    from app.inpatient_observations import source_current
    from app.models import InpatientObservation, InpatientUrineInterval

    point_rows = (
        db.query(InpatientObservation)
        .filter(
            InpatientObservation.patient_id == patient_id,
            InpatientObservation.admission_id == admission_id,
            InpatientObservation.observed_at >= start_at,
            InpatientObservation.observed_at <= end_at,
            InpatientObservation.recorded_at <= as_of,
        )
        .populate_existing()
        .order_by(InpatientObservation.observed_at, InpatientObservation.observation_id)
        .limit(MAX_ROWS + 1)
        .all()
    )
    urine_rows = (
        db.query(InpatientUrineInterval)
        .filter(
            InpatientUrineInterval.patient_id == patient_id,
            InpatientUrineInterval.admission_id == admission_id,
            InpatientUrineInterval.start_at < end_at,
            InpatientUrineInterval.end_at > start_at,
            InpatientUrineInterval.recorded_at <= as_of,
        )
        .populate_existing()
        .order_by(InpatientUrineInterval.start_at, InpatientUrineInterval.interval_id)
        .limit(MAX_ROWS + 1)
        .all()
    )
    if len(point_rows) + len(urine_rows) > MAX_ROWS:
        raise HTTPException(422, "观测窗超过1000条原记录，不能截断后冒称完整，请缩小窗口")
    points = [source_current(db, item, allow_revoked=True) for item in point_rows]
    urine = [source_current(db, item, allow_revoked=True) for item in urine_rows]
    patient = db.get(Patient, patient_id)
    for item in [*points, *urine]:
        # Bind original governance even when two changed free-text reasons are
        # reduced to the same privacy placeholder. Never redact typed numbers.
        item["governance_hash"] = hashlib.sha256(canonical_json({key: item[key] for key in ("status", "revision", "revoked_at", "revoked_by", "revoke_reason")}).encode()).hexdigest()
        for key in ("note", "oxygen_device", "collection_method"):
            if isinstance(item["payload"].get(key), str):
                item["payload"][key] = minimize_identifiers(item["payload"][key], patient)
        item["revoke_reason"] = minimize_identifiers(item["revoke_reason"], patient)
    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "window_id": window_id,
        "patient_id": patient_id,
        "admission_id": admission_id,
        "created_by": created_by,
        "created_at": iso(created_at),
        "start_at": iso(start_at),
        "end_at": iso(end_at),
        "as_of": iso(as_of),
        "snapshot_basis": "current_snapshot_retrospective",
        "representation": "typed_quantities_preserved_free_text_identifiers_minimized",
        "point_interval_semantics": "[start,end]",
        "points": points,
        "urine_intervals": urine,
        "quality": {
            "point_count": len(points),
            "urine_interval_count": len(urine),
            "query_truncated": False,
            **_point_quality(points, start_at, end_at),
            "urine": _urine_quality(urine, start_at, end_at),
        },
        "lab_input_status": "not_available_requires_explicit_admission_binding_and_reviewed_mapping",
        "model_input_validation": "not_provided",
        "limitations": [
            "所选住院和UTC时段内符合截止时点的离散记录，不证明连续监护或采样完整性",
            "未前填、补零、从脉搏替代心率、从设备推测FiO2或自动计算临床评分",
            "当前快照回溯，不是历史数据库as-of重放；已撤销原值不得作为有效测量",
            "旧患者级体征、检验、护理正文和当前诊断医嘱未作为本窗口特征加载",
        ],
    }
    snapshot["content_hash"] = content_hash(snapshot)
    snapshot["source_id"] = f"observation_window:{window_id}:{snapshot['content_hash'][:12]}"
    if len(canonical_json(snapshot).encode()) > settings.AI_MAX_CONTEXT_CHARS:
        raise HTTPException(422, "原观测窗及质量说明超过AI上下文字节限制，请缩小窗口，不自动截断")
    return snapshot


def create_window(db, user, values):
    authorize_scope(db, user, values["patient_id"], values["admission_id"])
    now, identifier = utcnow(), str(uuid.uuid4())
    if not values["start_at"] < values["end_at"] <= values["as_of"] <= now or values["end_at"] - values["start_at"] > datetime.timedelta(hours=168):
        raise HTTPException(422, "观测窗须start<end<=as_of<=当前UTC且最多168小时")
    snapshot = build_snapshot(db, **values, window_id=identifier, created_by=user.user_id, created_at=now)
    row = AIObservationWindow(
        **values,
        window_id=identifier,
        created_by=user.user_id,
        created_at=now,
        schema_version=SCHEMA_VERSION,
        snapshot_json=canonical_json(snapshot),
        content_hash=snapshot["content_hash"],
        status="active",
        revision=1,
    )
    db.add(row)
    db.flush()
    return row


def snapshot_current(db, user, window_or_id):
    identifier = canonical_id(window_or_id.window_id if isinstance(window_or_id, AIObservationWindow) else window_or_id)
    row = db.query(AIObservationWindow).filter_by(window_id=identifier).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(409, "原观测窗不存在")
    authorize_scope(db, user, row.patient_id, row.admission_id)
    if row.status != "active" or row.revision != 1 or row.schema_version != SCHEMA_VERSION or row.revoked_at is not None or row.revoked_by is not None or row.revoke_reason != "":
        raise HTTPException(409, "原观测窗已撤销或版本不一致")
    if not row.start_at < row.end_at <= row.as_of <= row.created_at <= utcnow() or row.end_at - row.start_at > datetime.timedelta(hours=168):
        raise HTTPException(409, "原观测窗UTC时间边界已不符合冻结契约")
    try:
        frozen = json.loads(row.snapshot_json)
        if content_hash(frozen) != row.content_hash or frozen.get("content_hash") != row.content_hash or frozen.get("source_id") != f"observation_window:{identifier}:{row.content_hash[:12]}":
            raise ValueError()
        expected = build_snapshot(db, **{key: getattr(row, key) for key in ("window_id", "patient_id", "admission_id", "created_by", "created_at", "start_at", "end_at", "as_of")})
        if canonical_json(expected) != canonical_json(frozen):
            raise ValueError()
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(409, "原观测窗内容、来源成员或时间归属已改变") from exc
    return frozen


def observation_context(db, user, patient_id, admission_id, references):
    from app.ai.context import ContextBundle

    if not isinstance(references, dict) or not references.get("observation_window_id") or set(references) - {"observation_window_id", "question"}:
        raise HTTPException(422, "风险输入须仅选择原住院冻结观测窗，不接受其他原资料或自由JSON")
    if "question" in references and (not isinstance(references["question"], str) or len(references["question"]) > 12000):
        raise HTTPException(422, "风险问题须为最多12000字文本，不作为原窗口测量事实")
    authorize_scope(db, user, patient_id, admission_id)
    snapshot = snapshot_current(db, user, references["observation_window_id"])
    if snapshot["patient_id"] != patient_id or snapshot["admission_id"] != admission_id:
        raise HTTPException(409, "观测窗不属于本次患者和原住院")
    admission = db.get(Admission, admission_id)
    evidence = [{"source_id": snapshot["source_id"], "kind": "clinical_record", "title": "冻结原住院观测窗", "observed_at": snapshot["as_of"], "content": canonical_json(snapshot)}]
    for item in [*snapshot["points"], *snapshot["urine_intervals"]]:
        evidence.append(
            {"source_id": item["source_id"], "kind": "clinical_record", "title": "观测窗内原始记录与状态", "observed_at": item.get("observed_at", item.get("end_at")), "content": canonical_json(item)}
        )
    return ContextBundle(
        data={
            "scope": "inpatient_observation_window",
            "observation_window": snapshot,
            "selected_sources": {"observation_window_id": snapshot["window_id"]},
            "missing_data": snapshot["limitations"],
            "snapshot_time": iso(utcnow()),
        },
        evidence=evidence,
        department_ids={admission.department_id} if admission.department_id else set(),
    )


def authorize_window_snapshot(db, user, context, patient_id, admission_id):
    if user.user_role == "super_admin":
        return
    frozen = context.get("observation_window")
    if not isinstance(frozen, dict):
        raise HTTPException(403, "旧风险任务没有可复核的原住院观测窗，请由超级管理员核对冻结审计")
    try:
        current = snapshot_current(db, user, frozen.get("window_id"))
        if current != frozen or current["patient_id"] != patient_id or current["admission_id"] != admission_id:
            raise ValueError()
    except (HTTPException, ValueError, TypeError) as exc:
        raise HTTPException(403, "原观测窗、来源或当前住院权限已改变，不能继续读取旧风险结果") from exc
