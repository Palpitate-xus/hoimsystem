import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import DoctorSchedule, Registration, RegistrationCounter


def restore_schedule_slot(db: Session, schedule_id: int) -> int:
    """Return one consumed slot atomically inside the cancellation transaction."""
    return db.query(DoctorSchedule).filter(DoctorSchedule.schedule_id == schedule_id).update(
        {DoctorSchedule.number: func.coalesce(DoctorSchedule.number, 0) + 1}, synchronize_session="fetch"
    )


def allocate_registration_id(db: Session, registration_time: datetime.datetime) -> int:
    """Allocate a daily outpatient registration number inside the current transaction."""
    visit_date = registration_time.date()
    counter = (
        db.query(RegistrationCounter)
        .filter(RegistrationCounter.counter_date == visit_date)
        .with_for_update()
        .first()
    )
    if counter is None:
        start = datetime.datetime.combine(visit_date, datetime.time.min)
        end = start + datetime.timedelta(days=1)
        current_max = (
            db.query(func.max(Registration.registration_id))
            .filter(Registration.time >= start, Registration.time < end)
            .scalar()
            or 0
        )
        number = int(current_max) + 1
        db.add(RegistrationCounter(counter_date=visit_date, next_number=number + 1))
    else:
        number = counter.next_number
        counter.next_number += 1
    db.flush()
    return number
