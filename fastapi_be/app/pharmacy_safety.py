import datetime
import re

from sqlalchemy.orm import Session

from app.models import Patient, Pharmaceutical


def get_usable_pharmaceutical(db: Session, pharmaceutical_id: int) -> tuple[Pharmaceutical | None, str | None]:
    """Return a medication that is active and not past its expiry date."""
    pharmaceutical = db.query(Pharmaceutical).filter(Pharmaceutical.pharmaceutical_id == pharmaceutical_id).first()
    if not pharmaceutical:
        return None, "药品不存在"
    if pharmaceutical.status != 0:
        return None, f"药品 {pharmaceutical.name} 已停用，不能开立"
    if pharmaceutical.expireddate and pharmaceutical.expireddate < datetime.date.today():
        return None, f"药品 {pharmaceutical.name} 已过期，不能开立"
    return pharmaceutical, None


def get_patient_safe_pharmaceutical(db: Session, pharmaceutical_id: int, patient_id: int) -> tuple[Pharmaceutical | None, str | None]:
    pharmaceutical, error = get_usable_pharmaceutical(db, pharmaceutical_id)
    if error:
        return None, error
    patient = db.query(Patient).filter(Patient.patient_id == patient_id).first()
    if not patient:
        return None, "患者不存在"
    allergy_history = (patient.allergy_history or "").strip()
    if not allergy_history:
        return pharmaceutical, None
    drug_name = (pharmaceutical.name or "").strip().lower()
    for entry in re.split(r"[,，;；]", allergy_history):
        allergen = re.split(r"[:：]", entry, maxsplit=1)[0].strip().lower()
        if allergen and (allergen == drug_name or drug_name.startswith(allergen)):
            return None, f"过敏史冲突：病人对 [{allergen}] 过敏，不能使用 [{pharmaceutical.name}]"
    return pharmaceutical, None
