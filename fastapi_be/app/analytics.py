"""Idempotent operational fact aggregation."""

import datetime
from decimal import Decimal

from sqlalchemy import func

from app.models import (
    Admission,
    DailyOperationalMetric,
    EmergencyTriage,
    ImagingOrder,
    LabOrder,
    LabResult,
    Payment,
    Prescription,
    Queue,
    Registration,
)


def _window(metric_date: datetime.date) -> tuple[datetime.datetime, datetime.datetime]:
    start = datetime.datetime.combine(metric_date, datetime.time.min)
    return start, start + datetime.timedelta(days=1)


def _count_between(db, model, column, start, end, *filters) -> int:
    return db.query(func.count()).select_from(model).filter(column >= start, column < end, *filters).scalar() or 0


def aggregate_daily_metrics(db, metric_date: datetime.date | None = None) -> dict:
    metric_date = metric_date or datetime.date.today()
    start, end = _window(metric_date)
    paid = db.query(
        func.count(Payment.payment_id),
        func.coalesce(func.sum(Payment.amount), 0),
    ).filter(Payment.status == 1, Payment.paid_time >= start, Payment.paid_time < end).one()
    refunded = db.query(func.coalesce(func.sum(Payment.amount), 0)).filter(
        Payment.status == 3,
        Payment.refunded_time >= start,
        Payment.refunded_time < end,
    ).scalar() or Decimal("0")
    if db.bind.dialect.name == "sqlite":
        # SQLite has no native interval average; calculate the bounded daily sample in Python.
        queue_times = db.query(Queue.create_time, Queue.call_time).filter(
            Queue.call_time >= start, Queue.call_time < end, Queue.create_time.isnot(None)
        ).all()
        wait_seconds = (
            sum((called - created).total_seconds() for created, called in queue_times) / len(queue_times)
            if queue_times
            else None
        )
    else:
        wait_seconds = db.query(
            func.avg(func.extract("epoch", Queue.call_time - Queue.create_time))
        ).filter(Queue.call_time >= start, Queue.call_time < end, Queue.create_time.isnot(None)).scalar()

    metric = db.get(DailyOperationalMetric, metric_date) or DailyOperationalMetric(metric_date=metric_date)
    metric.outpatient_visits = _count_between(db, Registration, Registration.time, start, end)
    metric.emergency_visits = _count_between(db, EmergencyTriage, EmergencyTriage.create_time, start, end)
    metric.admissions = _count_between(db, Admission, Admission.admission_time, start, end)
    metric.discharges = _count_between(db, Admission, Admission.discharge_time, start, end)
    metric.active_inpatients = db.query(func.count(Admission.admission_id)).filter(
        Admission.admission_time < end,
        (Admission.discharge_time.is_(None)) | (Admission.discharge_time >= end),
    ).scalar() or 0
    metric.prescriptions = _count_between(db, Prescription, Prescription.create_time, start, end)
    metric.lab_orders = _count_between(db, LabOrder, LabOrder.create_time, start, end)
    metric.imaging_orders = _count_between(db, ImagingOrder, ImagingOrder.create_time, start, end)
    metric.critical_labs = _count_between(
        db,
        LabResult,
        LabResult.report_time,
        start,
        end,
        LabResult.critical_status > 0,
    )
    metric.successful_payments = paid[0]
    metric.revenue = paid[1]
    metric.refunds = refunded
    metric.average_queue_wait_minutes = round(wait_seconds / 60, 2) if wait_seconds is not None else None
    metric.updated_at = datetime.datetime.now()
    db.add(metric)
    db.commit()
    return serialize_metric(metric)


def serialize_metric(metric: DailyOperationalMetric) -> dict:
    return {
        "date": metric.metric_date,
        "outpatient_visits": metric.outpatient_visits,
        "emergency_visits": metric.emergency_visits,
        "admissions": metric.admissions,
        "discharges": metric.discharges,
        "active_inpatients": metric.active_inpatients,
        "prescriptions": metric.prescriptions,
        "lab_orders": metric.lab_orders,
        "imaging_orders": metric.imaging_orders,
        "critical_labs": metric.critical_labs,
        "successful_payments": metric.successful_payments,
        "revenue": metric.revenue,
        "refunds": metric.refunds,
        "net_revenue": metric.revenue - metric.refunds,
        "average_queue_wait_minutes": metric.average_queue_wait_minutes,
        "updated_at": metric.updated_at,
    }
