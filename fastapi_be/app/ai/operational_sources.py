"""Scoped hospital facts with explicit windows, provenance and aggregation limitations."""

import datetime
import json

from fastapi import HTTPException
from sqlalchemy import case, func

from app.ai.catalog import FeatureSpec
from app.ai.context import ContextBundle
from app.ai.feedback_sources import attach_feedback_sources
from app.ai.governance import digest, encode_json
from app.ai.inventory_sources import attach_inventory_sources
from app.ai.models import utcnow
from app.ai.roster_sources import attach_hourly_demand, attach_roster_sources, planning_window
from app.ai.surgical_resources import attach_surgical_resources
from app.models import Admission, Bed, Consumable, DailyOperationalMetric, Department, Doctor, Pharmaceutical, Registration, User, Ward


def operational_scope(db, user: User, spec: FeatureSpec, values: dict) -> set[int] | None:
    """None denotes authorized hospital scope; a set always denotes specific departments."""
    requested = values.get("department_id")
    if requested is not None and (type(requested) is not int or requested < 1):
        raise HTTPException(422, "科室标识须为正整数")
    if user.user_role in {"admin", "super_admin"} or (user.user_role == "pharmacist" and spec.number in {66, 67}):
        departments = None
    elif user.user_role == "director":
        departments = {row[0] for row in db.query(Doctor.department_id).filter(Doctor.user_id == user.user_id, Doctor.department_id.is_not(None)).all()}
        if not departments:
            raise HTTPException(403, "未建立可核实的科室运营访问范围")
    else:
        raise HTTPException(403, "没有医院或科室运营资料访问权限")
    if requested is not None:
        if departments is not None and requested not in departments:
            raise HTTPException(403, "不能访问其他科室的运营资料")
        if db.get(Department, requested) is None:
            raise HTTPException(422, "所选科室不存在")
        return {requested}
    return departments


def operational_window(values: dict) -> tuple[datetime.date, datetime.date]:
    today = datetime.date.today()

    def read(key, default):
        value = values.get(key)
        if value in (None, ""):
            return default
        try:
            result = datetime.date.fromisoformat(value) if isinstance(value, str) and len(value) == 10 else None
        except ValueError:
            result = None
        if result is None or str(result) != value:
            raise HTTPException(422, "运营日期须为 YYYY-MM-DD")
        return result

    end = read("date_to", today)
    start = read("date_from", end - datetime.timedelta(days=29))
    if start > end or end > today or (end - start).days > 366:
        raise HTTPException(422, "运营历史区间须为正序、不含未来日期且不超过367天")
    return start, end


def authorize_operational_snapshot(db, user: User, spec: FeatureSpec, context: dict) -> None:
    """A retained snapshot does not retain a revoked department or hospital privilege."""
    current = operational_scope(db, user, spec, {})
    if user.user_role == "pharmacist" and context.get("source_domain") != "inventory":
        raise HTTPException(403, "旧任务未保留限定库存的数据范围，请由超级管理员核查原始审计")
    if current is None:
        return
    frozen = context.get("department_ids")
    if context.get("scope") != "department" or not isinstance(frozen, list) or not frozen or not set(frozen) <= current:
        raise HTTPException(403, "任务原始科室或全院范围已不属于当前运营权限")


def operational_options(db, user: User, spec: FeatureSpec) -> dict:
    """Offer only valid filters inside this actor's independently verified scope."""
    departments = operational_scope(db, user, spec, {})
    start, end = operational_window({})
    data = {"default_window": [str(start), str(end)], "allow_hospital_scope": departments is None, "departments": [], "truncated": False}
    if spec.number in {63, 65}:
        data["default_planning_window"] = [str(date) for date in planning_window({})]
    if spec.number in {66, 67}:
        data["inventory_scope_available"] = departments is None
        data["scope_note"] = "库存尚未按科室归属切分；科室范围不提供全院库存。单次最多选择20个真实品种。"
        if departments is None:
            for key, model, id_field in (("inventory_drugs", Pharmaceutical, "pharmaceutical_id"), ("inventory_consumables", Consumable, "consumable_id")):
                rows = db.query(model).order_by(getattr(model, id_field)).limit(301).all()
                data[key] = [{"item_id": getattr(row, id_field), "name": row.name, "status": row.status} for row in rows[:300]]
                data["truncated"] = data["truncated"] or len(rows) > 300
    else:
        query = db.query(Department)
        if departments is not None:
            query = query.filter(Department.department_id.in_(departments))
        rows = query.order_by(Department.department_id).limit(201).all()
        data["departments"] = [{"department_id": row.department_id, "name": row.name} for row in rows[:200]]
        data["truncated"] = len(rows) > 200
        data["scope_note"] = "未选具体科室时使用当前账号已获准的全院或所属科室范围。"
    return data


def operational_context(db, user: User, spec: FeatureSpec, values: dict) -> ContextBundle:
    if spec.number == 62 and values.get("forecast_series_id") not in (None, ""):
        from app.ai.forecast_sources import forecast_context

        return forecast_context(db, user, values)
    departments = operational_scope(db, user, spec, values)
    start, end = operational_window(values)
    bundle = ContextBundle(department_ids=departments or set())
    bundle.data = {
        "scope": "hospital" if departments is None else "department",
        "source_domain": "inventory" if spec.number in {66, 67} else "feedback" if spec.number == 70 else "operations",
        "department_ids": sorted(departments) if departments is not None else None,
        "department_names": [row[0] for row in db.query(Department.name).filter(Department.department_id.in_(departments)).order_by(Department.department_id).all()] if departments is not None else [],
        "since": str(start),
        "until": str(end),
        "business_date": str(datetime.date.today()),
        "snapshot_time": utcnow().replace(tzinfo=datetime.UTC).isoformat(),
        "missing_data": [],
        "truncated_sources": [],
        "scope_note": "仅授权范围内的原始记录汇总和已保存统计；未核实外部数据导入完整性，未记录日不等于已验证零业务量，当前记录状态不回推为历史状态",
    }

    def add(key: str, title: str, fields: dict, *, store=True):
        clean = json.loads(encode_json(fields))
        provenance = {name: bundle.data[name] for name in ("scope", "source_domain", "department_ids", "since", "until")}
        source_id = "operations:" + key + ":" + digest([provenance, clean])[:20]
        record = {"source_id": source_id, **clean}
        if store:
            bundle.data[key] = record
        bundle.evidence.append(
            {"source_id": source_id, "kind": "operational_record", "title": title, "observed_at": bundle.data["snapshot_time"], "content": encode_json({**provenance, "record": clean})}
        )
        return record

    if spec.number in {66, 67}:
        attach_inventory_sources(db, departments, start, end, bundle, add, values)
        return bundle
    if spec.number == 65:
        attach_surgical_resources(db, departments, start, end, values, bundle, add)
        return bundle
    if spec.number == 70:
        attach_feedback_sources(db, departments, start, end, bundle, add)
        return bundle
    if spec.number not in {61, 62, 63, 64}:
        bundle.data["missing_data"].append("本功能的专属运营来源尚需补充，不以无关全院财务指标代替")
        return bundle
    if departments is None and spec.number in {61, 62, 64}:
        rows = db.query(DailyOperationalMetric).filter(DailyOperationalMetric.metric_date >= start, DailyOperationalMetric.metric_date <= end).order_by(DailyOperationalMetric.metric_date).all()
        fields = (
            ("outpatient_visits", "emergency_visits")
            if spec.number == 62
            else ("admissions", "discharges", "active_inpatients")
            if spec.number == 64
            else (
                "outpatient_visits",
                "emergency_visits",
                "admissions",
                "discharges",
                "active_inpatients",
                "prescriptions",
                "lab_orders",
                "imaging_orders",
                "critical_labs",
                "successful_payments",
                "revenue",
                "refunds",
                "average_queue_wait_minutes",
            )
        )
        dates = {row.metric_date for row in rows}
        missing = [str(start + datetime.timedelta(days=index)) for index in range((end - start).days + 1) if start + datetime.timedelta(days=index) not in dates]
        add(
            "saved_daily_metrics",
            "已保存全院日统计",
            {
                "columns": ["date", *fields, "updated_at"],
                "rows": [[row.metric_date, *[getattr(row, field) for field in fields], row.updated_at] for row in rows],
                "missing_dates": missing,
                "definition_note": "按现有日统计任务口径保留原值；门诊计数为挂号记录数，未必为到诊人数；在院值为既有时间区间估算，未独立验证床位占用；不填补缺失日期或等待时间",
            },
        )
        if missing:
            bundle.data["missing_data"].append("日统计有未汇总日期，不能用零值代替或当作完整训练序列")
    elif departments is not None:
        bundle.data["missing_data"].append("全院预聚合指标未按科室拆分，未在科室范围加载；以下使用所属科室原始记录汇总")

    beginning = datetime.datetime.combine(start, datetime.time.min)
    ending = datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min)

    def events(key, model, column, title):
        date = func.date(column)
        state = case((model.status.in_([0, 1, 2, 3]), model.status), else_=-1)
        query = db.query(date, state, func.count()).filter(column >= beginning, column < ending)
        if departments is not None:
            query = query.filter(model.department_id.in_(departments))
        rows = query.group_by(date, state).order_by(date, state).all()
        add(
            key,
            title,
            {
                "columns": ["date", "current_record_status", "record_count"],
                "rows": [[str(date), status, count] for date, status, count in rows],
                "status_note": "保留当前原记录状态；-1为未知状态。仅计有实际记录时间的原始行，不等于实际到诊或历史状态回放",
            },
        )

    if spec.number in {61, 62, 63}:
        events("recorded_registrations", Registration, Registration.time, "授权范围挂号记录日汇总")
    if spec.number in {62, 63}:
        attach_hourly_demand(db, departments, start, end, bundle, add)
    if spec.number == 63:
        attach_roster_sources(db, departments, values, bundle, add)
    if spec.number in {61, 64}:
        events("recorded_admissions", Admission, Admission.admission_time, "授权范围入院记录日汇总")
        events("recorded_discharges", Admission, Admission.discharge_time, "授权范围出院时间日汇总")
        if spec.number == 61 and end < datetime.date.today():
            bundle.data["missing_data"].append("历史分析区间不加载当前病区或床位快照；未提供该时期已核实的床位容量")
            return bundle
        active = db.query(func.count(Admission.admission_id)).filter(Admission.status == 1)
        if departments is not None:
            active = active.filter(Admission.department_id.in_(departments))
        add("current_active_admissions", "当前在院状态记录数", {"record_count": active.scalar() or 0, "definition_note": "当前状态为在院的入院记录数，不等于历史在院人数或核实后的实占床位"})
        query = (
            db.query(Ward.ward_id, Ward.name, Ward.department_id, Ward.bed_count, Ward.status, Bed.status, func.count(Bed.bed_id))
            .outerjoin(Bed)
            .group_by(Ward.ward_id, Ward.name, Ward.department_id, Ward.bed_count, Ward.status, Bed.status)
            .order_by(Ward.ward_id, Bed.status)
        )
        if departments is not None:
            query = query.filter(Ward.department_id.in_(departments))
        wards = {}
        rows = query.limit(1001).all()
        for ward_id, name, department_id, configured_count, ward_status, bed_status, count in rows[:1000]:
            item = wards.setdefault(
                ward_id, {"ward_id": ward_id, "name": name, "department_id": department_id, "ward_status": ward_status, "configured_bed_count": configured_count, "bed_status_counts": []}
            )
            if count:
                item["bed_status_counts"].append({"status": bed_status, "count": count})
        if len(rows) > 1000 or len(wards) > 100:
            bundle.data["truncated_sources"].append({"source": "ward_capacity", "limit": 100, "note": "病区资料仅列有限范围，不按部分清单计算全院容量"})
        for ward in wards.values():
            loaded_count = sum(item["count"] for item in ward["bed_status_counts"])
            free_count = sum(item["count"] for item in ward["bed_status_counts"] if item["status"] == 0)
            ward["loaded_bed_record_count"] = loaded_count
            ward["configured_count_matches_loaded"] = ward["configured_bed_count"] == loaded_count if ward["configured_bed_count"] is not None and len(rows) <= 1000 else None
            ward["recorded_free_beds_in_active_ward"] = free_count if ward["ward_status"] == 0 else 0 if ward["ward_status"] == 1 else None
        add(
            "ward_capacity",
            "当前病区与床位状态",
            {
                "wards": list(wards.values())[:100],
                "status_definitions": {"0": "空闲", "1": "占用", "2": "禁用", "3": "预订"},
                "definition_note": "病区停用时其中空闲床不作为可用床；配置床数与加载床行数分别保留。空闲状态计数不等于已确认可收治名额，不代替人员、设备或感染隔离资质",
            },
        )
    return bundle
