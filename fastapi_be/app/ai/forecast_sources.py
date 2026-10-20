"""Daily registration facts with explicit coverage attestation and current-source guards."""

import datetime
import hashlib
import json
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func

from app.ai.catalog import FEATURE_BY_KEY
from app.ai.models import AIFeatureConfig, AIForecastSeries, utcnow
from app.models import Department, Registration

TARGET = "registration_record_count"
TIME_BASIS = "naive_registration_time"
MAX_REGISTRATION_ROWS = 200000
MIN_DAYS, MAX_DAYS = 112, 366


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha256(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_series_id(value):
    try:
        valid = isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise HTTPException(422, "预测来源标识须为规范UUID")
    return value


def forecast_scope(db, user):
    """Keep source inspection independent of deployment while retaining feature roles."""
    from app.ai.operational_sources import operational_scope

    spec = FEATURE_BY_KEY["visit_forecast"]
    config = db.query(AIFeatureConfig).filter_by(feature_key=spec.key).populate_existing().one_or_none()
    roles = json.loads(config.allowed_roles_json) if config else spec.default_roles
    if user.user_role != "super_admin" and (user.user_role not in spec.default_roles or user.user_role not in roles):
        raise HTTPException(403, "没有使用挂号记录预测来源的权限")
    return operational_scope(db, user, spec, {})


def authorize_series_scope(db, user, series):
    departments = forecast_scope(db, user)
    if departments is not None and (series.scope != "department" or series.department_id not in departments):
        raise HTTPException(403, "预测来源不属于当前科室运营权限")


def _window(scope, department_id, date_from, date_to, timezone):
    if scope not in {"hospital", "department"} or (scope == "hospital" and department_id is not None) or (scope == "department" and (type(department_id) is not int or department_id < 1)):
        raise HTTPException(422, "预测来源须为全院或一个明确科室")
    try:
        start, end = datetime.date.fromisoformat(date_from), datetime.date.fromisoformat(date_to)
        valid_dates = str(start) == date_from and str(end) == date_to
        zone = ZoneInfo(timezone)
    except (ValueError, TypeError, ZoneInfoNotFoundError) as exc:
        raise HTTPException(422, "历史日期或原钟点IANA时区无效") from exc
    if not valid_dates or not MIN_DAYS <= (end - start).days + 1 <= MAX_DAYS:
        raise HTTPException(422, "覆盖区间须为112至366天的连续完整窗口")
    today = utcnow().replace(tzinfo=datetime.UTC).astimezone(zone).date()
    if end > today:
        raise HTTPException(422, "来源窗口不得包含原时区的未来日期")
    return start, end, end < today


def preview_series(db, *, scope, department_id, date_from, date_to, timezone):
    """Project actual rows; unconfirmed empty days remain unknown, including observed zero."""
    start, end, ended = _window(scope, department_id, date_from, date_to, timezone)
    if department_id is not None and db.get(Department, department_id) is None:
        raise HTTPException(422, "来源科室不存在")
    query = db.query(Registration.registration_uuid, Registration.time, Registration.department_id)
    untimed = db.query(func.count()).select_from(Registration).filter(Registration.time.is_(None))
    if department_id is not None:
        query = query.filter(Registration.department_id == department_id)
        untimed = untimed.filter(Registration.department_id == department_id)
    rows = (
        query.filter(
            Registration.time >= datetime.datetime.combine(start, datetime.time.min),
            Registration.time < datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min),
        )
        .order_by(Registration.registration_uuid)
        .limit(MAX_REGISTRATION_ROWS + 1)
        .yield_per(1000)
    )
    counts, fingerprint = {}, hashlib.sha256()
    for index, (row_id, recorded, department) in enumerate(rows):
        if index >= MAX_REGISTRATION_ROWS:
            raise HTTPException(422, "覆盖窗口超过200000条原始挂号记录；不能截断后作为完整来源")
        if recorded.tzinfo is not None:
            raise HTTPException(409, "原记录钟点已不符合无时区数据库时间口径")
        fingerprint.update((canonical_json([row_id, recorded.isoformat(timespec="microseconds"), department]) + "\n").encode("utf-8"))
        key = str(recorded.date())
        counts[key] = counts.get(key, 0) + 1
    observations = [
        {"date": str(start + datetime.timedelta(days=offset)), "observed_count": counts.get(str(start + datetime.timedelta(days=offset)), 0), "value": None} for offset in range((end - start).days + 1)
    ]
    source = {
        "target": TARGET,
        "grain": "day",
        "scope": scope,
        "department_id": department_id,
        "date_from": str(start),
        "date_to": str(end),
        "timezone": timezone,
        "time_basis": TIME_BASIS,
        "registration_digest": fingerprint.hexdigest(),
        "unassigned_time_records": int(untimed.scalar()),
        "observations": observations,
    }
    return {
        **source,
        "expected_digest": sha256(source),
        "quality": {
            "all_days_ended": ended,
            "coverage_status": "unconfirmed",
            "zero_is_confirmed": False,
            "notes": [
                "按原数据库无时区钟点分日，未转换既有钟点；时区解释须由超级管理员明确确认",
                "按所有状态挂号原记录计数，不是实际到诊人数；当前状态不回放历史",
                "无时间记录为全范围计数，无法分日，明确排除于本窗口日计数；无资料日未经确认均为未知",
            ],
        },
    }


def create_series(db, user, values):
    """Freeze only server-recomputed rows after all three explicit attestations."""
    if user.user_role != "super_admin":
        raise HTTPException(403, "只有超级管理员可确认预测来源")
    values = dict(values)
    for key in ("coverage_confirmed", "days_ended_confirmed", "timezone_confirmed"):
        if values.get(key) is not True:
            raise HTTPException(422, "请分别确认完整覆盖、每个日已结束及原无时区钟点解释")
    note = values["coverage_note"]
    if not isinstance(note, str) or not 20 <= len(note.strip()) <= 2000:
        raise HTTPException(422, "完整性依据须为20至2000字")
    preview = preview_series(db, **{key: values[key] for key in ("scope", "department_id", "date_from", "date_to", "timezone")})
    if not preview["quality"]["all_days_ended"]:
        raise HTTPException(422, "来源中每个日期必须在原时区已经结束")
    if values["expected_digest"] != preview["expected_digest"]:
        raise HTTPException(409, "原始来源或预览筛选已改变，请重新预览并核对完整性")
    series_id, now = str(uuid.uuid4()), utcnow()
    content = {key: preview[key] for key in ("target", "grain", "scope", "department_id", "date_from", "date_to", "timezone", "time_basis", "registration_digest", "unassigned_time_records")}
    content.update(
        series_id=series_id,
        coverage_status="super_admin_attested",
        coverage_attested_at=now.replace(tzinfo=datetime.UTC).isoformat(timespec="microseconds"),
        coverage_note_hash=hashlib.sha256(note.encode("utf-8")).hexdigest(),
        observations=[{"date": point["date"], "value": point["observed_count"]} for point in preview["observations"]],
    )
    content_hash = sha256(content)
    content.update(content_hash=content_hash, source_id="forecast:" + series_id + ":" + content_hash[:12])
    content = _typed_source(content)
    row = AIForecastSeries(
        series_id=series_id,
        name=values["name"],
        target=TARGET,
        scope=content["scope"],
        department_id=content["department_id"],
        date_from=datetime.date.fromisoformat(content["date_from"]),
        date_to=datetime.date.fromisoformat(content["date_to"]),
        timezone=content["timezone"],
        time_basis=TIME_BASIS,
        source_json=canonical_json(content),
        content_hash=content_hash,
        registration_digest=content["registration_digest"],
        coverage_note=note,
        status="active",
        revision=1,
        created_by=user.user_id,
        create_time=now,
    )
    db.add(row)
    db.flush()
    return row


def _typed_source(value):
    from app.ai.forecast_contract import ForecastSource

    return ForecastSource.model_validate(value).model_dump(mode="json")


def source_current(db, user, series_or_id):
    """Revalidate the immutable declaration and its actual original rows, never just counts."""
    series_id = canonical_series_id(series_or_id.series_id if isinstance(series_or_id, AIForecastSeries) else series_or_id)
    row = db.query(AIForecastSeries).filter_by(series_id=series_id).populate_existing().one_or_none()
    if row is None:
        raise HTTPException(409, "预测原来源已不存在")
    authorize_series_scope(db, user, row)
    if row.status != "active" or row.revision != 1:
        raise HTTPException(409, "预测原来源已撤销或版本不一致，请选择新来源")
    try:
        source = _typed_source(json.loads(row.source_json))
        matching = {
            "series_id": row.series_id,
            "target": row.target,
            "scope": row.scope,
            "department_id": row.department_id,
            "date_from": str(row.date_from),
            "date_to": str(row.date_to),
            "timezone": row.timezone,
            "time_basis": row.time_basis,
            "content_hash": row.content_hash,
            "registration_digest": row.registration_digest,
        }
        if any(source[key] != expected for key, expected in matching.items()) or source["coverage_note_hash"] != hashlib.sha256(row.coverage_note.encode("utf-8")).hexdigest():
            raise ValueError("table binding changed")
        if source["coverage_attested_at"] != row.create_time.replace(tzinfo=datetime.UTC).isoformat(timespec="microseconds"):
            raise ValueError("attestation time changed")
    except (ValueError, TypeError, KeyError, ValidationError) as exc:
        raise HTTPException(409, "预测来源声明与冻结内容不一致") from exc
    preview = preview_series(db, **{key: source[key] for key in ("scope", "department_id", "date_from", "date_to", "timezone")})
    current_observations = [{"date": item["date"], "value": item["observed_count"]} for item in preview["observations"]]
    if (
        not preview["quality"]["all_days_ended"]
        or preview["registration_digest"] != source["registration_digest"]
        or preview["unassigned_time_records"] != source["unassigned_time_records"]
        or current_observations != source["observations"]
    ):
        raise HTTPException(409, "原始挂号资料已改变，旧覆盖声明不能继续使用，请重新预览并建立新来源")
    return source


def series_metadata(row):
    return {
        "series_id": row.series_id,
        "name": row.name,
        "source_id": "forecast:" + row.series_id + ":" + row.content_hash[:12],
        "target": row.target,
        "grain": "day",
        "scope": row.scope,
        "department_id": row.department_id,
        "date_from": str(row.date_from),
        "date_to": str(row.date_to),
        "timezone": row.timezone,
        "time_basis": row.time_basis,
        "day_count": (row.date_to - row.date_from).days + 1,
        "content_hash": row.content_hash,
        "status": row.status,
        "revision": row.revision,
        "create_time": row.create_time.replace(tzinfo=datetime.UTC).isoformat(timespec="microseconds"),
        "freshness": "not_checked",
    }


def forecast_context(db, user, values):
    """Attach only the selected typed daily source, without unrelated operational facts."""
    from app.ai.context import ContextBundle

    allowed = {"forecast_series_id", "horizon_days", "question", "date_from", "date_to", "department_id"}
    if set(values) - allowed:
        raise HTTPException(422, "预测输入仅接受原来源、7或14天跨度及问题，不能覆盖来源日计数或口径")
    horizon = values.get("horizon_days")
    if type(horizon) is not int or horizon not in {7, 14}:
        raise HTTPException(422, "预测跨度须为7或14天")
    source = source_current(db, user, values.get("forecast_series_id"))
    for key in ("date_from", "date_to", "department_id"):
        if key in values and (values[key] != source[key] or (key == "department_id" and values[key] is not None and type(values[key]) is not int)):
            raise HTTPException(422, "预测筛选与已选不可变来源不匹配")
    row = db.get(AIForecastSeries, source["series_id"])
    data = {
        "scope": source["scope"],
        "source_domain": "registration_forecast",
        "department_ids": [source["department_id"]] if source["department_id"] is not None else None,
        "since": source["date_from"],
        "until": source["date_to"],
        "timezone": source["timezone"],
        "time_basis": source["time_basis"],
        "forecast_source": source,
        "series_revision": row.revision,
        "horizon_days": horizon,
        "snapshot_time": utcnow().replace(tzinfo=datetime.UTC).isoformat(),
        "missing_data": ["统计目标为原钟点每日所有状态挂号记录数，不代表实际到诊；完整性由超级管理员声明，不等于预测模型已验证"],
    }
    if source["unassigned_time_records"]:
        data["missing_data"].append("存在无原记录时间的挂号行，无法分日，已明确排除于日计数")
    evidence = [
        {"source_id": source["source_id"], "kind": "operational_record", "title": "已声明完整覆盖的每日挂号原记录数", "observed_at": source["coverage_attested_at"], "content": canonical_json(source)}
    ]
    return ContextBundle(data=data, evidence=evidence, department_ids={source["department_id"]} if source["department_id"] is not None else set())


def authorize_forecast_snapshot(db, user, context):
    """Ordinary retained results require current source facts; Super retains frozen audit."""
    if user.user_role == "super_admin":
        return
    frozen = context.get("forecast_source")
    if not isinstance(frozen, dict):
        raise HTTPException(403, "旧预测任务缺少可复核来源，请由超级管理员核查冻结审计")
    try:
        source = source_current(db, user, frozen.get("series_id"))
        if source != _typed_source(frozen) or context.get("series_revision") != 1:
            raise ValueError("frozen source changed")
    except (HTTPException, ValueError, TypeError, ValidationError) as exc:
        raise HTTPException(403, "预测原来源、资料或当前科室权限已变化，旧结果不能继续读取；超级管理员保留冻结审计") from exc
