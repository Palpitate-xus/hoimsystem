import datetime

from sqlalchemy.orm import Session

from app.models import Pharmaceutical


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
