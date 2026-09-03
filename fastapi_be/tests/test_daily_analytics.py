import datetime
from decimal import Decimal

from app.analytics import aggregate_daily_metrics
from app.models import DailyOperationalMetric, Payment, Queue


def test_daily_metrics_are_idempotently_preaggregated(seed_data, db_session):
    now = datetime.datetime.now()
    seed_data["charge"].status = 1
    payment = Payment(
        payment_no="PAY-ANALYTICS-1",
        charge_id=seed_data["charge"].charge_id,
        channel="wechat",
        amount=Decimal("31.00"),
        status=1,
        paid_time=now,
        create_time=now,
    )
    queue = Queue(
        patient_id=seed_data["patient"].patient_id,
        doctor_id=seed_data["doctor"].doctor_id,
        queue_number=1,
        status=1,
        type=0,
        create_time=now - datetime.timedelta(minutes=12),
        call_time=now,
    )
    db_session.add_all([payment, queue])
    db_session.commit()

    first = aggregate_daily_metrics(db_session, now.date())
    second = aggregate_daily_metrics(db_session, now.date())

    assert first["successful_payments"] == 1
    assert first["revenue"] == Decimal("31.00")
    assert first["average_queue_wait_minutes"] == Decimal("12.00")
    assert second["revenue"] == first["revenue"]
    assert db_session.query(DailyOperationalMetric).count() == 1
