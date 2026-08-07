import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Registration, RegistrationCounter


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
