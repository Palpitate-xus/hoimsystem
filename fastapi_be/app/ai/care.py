"""Read-only surgical team care relations, scoped through the actual parent admission."""

from sqlalchemy import or_, select

from app.models import SurgeryApplication, SurgerySchedule


def surgical_patient_ids(doctor_ids: list[int], nurse_user_id: int | None = None, admission_id: str | None = None):
    """Recognize explicit author, surgeon, anesthetist or nursing assignment, excluding cancellations."""
    team = [SurgerySchedule.surgeon_id.in_(doctor_ids), SurgerySchedule.anesthesiologist_id.in_(doctor_ids)]
    if nurse_user_id is not None:
        team.extend([SurgerySchedule.scrub_nurse_id == nurse_user_id, SurgerySchedule.circulating_nurse_id == nurse_user_id])
    assigned = select(SurgerySchedule.application_id).where(SurgerySchedule.status.in_([0, 1, 2]), SurgerySchedule.patient_id == SurgeryApplication.patient_id, or_(*team))
    query = select(SurgeryApplication.patient_id).where(SurgeryApplication.status.in_([0, 1, 2, 3]), or_(SurgeryApplication.doctor_id.in_(doctor_ids), SurgeryApplication.application_id.in_(assigned)))
    if admission_id:
        query = query.where(SurgeryApplication.admission_id == admission_id)
    return query
