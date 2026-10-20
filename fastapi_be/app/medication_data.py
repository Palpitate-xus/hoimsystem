"""Lossless outpatient medication instructions shared by prescribing and review."""

from decimal import Decimal, InvalidOperation


def _positive_number(raw: object, label: str, *, integer: bool = False) -> Decimal | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raise ValueError(label + "必须是有效正数")
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise ValueError(label + "必须是有效正数") from exc
    if value.is_finite() and value <= 0 and label == "药品数量":
        raise ValueError("药品数量必须大于0")
    if not value.is_finite() or not 0 < value <= 1000000000:
        raise ValueError(label + "必须是有效正数")
    if integer and value != value.to_integral_value():
        raise ValueError(label + "必须是正整数")
    if not integer and value != value.quantize(Decimal("0.000001")):
        raise ValueError(label + "最多保留6位小数，请核对剂量单位")
    return value


def normalize_medication_item(raw: dict) -> dict:
    """Preserve legacy unspecified instructions as unknown instead of inventing defaults."""
    number = _positive_number(raw.get("number"), "药品数量", integer=True)
    if number is None:
        raise ValueError("药品数量必须是正整数")
    dosage = _positive_number(raw.get("dosage"), "每次剂量")
    duration = _positive_number(raw.get("duration_days"), "疗程天数", integer=True)
    if duration is not None and duration > 3650:
        raise ValueError("疗程天数超过可记录范围")
    result = {"number": int(number), "dosage": dosage, "duration_days": int(duration) if duration is not None else None}
    for name, label, length in [("dose_unit", "剂量单位", 24), ("frequency", "用药频次", 40), ("route", "给药途径", 24)]:
        value = raw.get(name)
        if value is None or value == "":
            result[name] = None
        elif not isinstance(value, str) or len(value.strip()) > length:
            raise ValueError(label + "格式无效")
        else:
            result[name] = value.strip() or None
    return result


def medication_fields(item) -> dict:
    """Expose decimal dose text without binary conversion or fabricated instructions."""
    return {
        "dosage": format(item.dosage.normalize(), "f") if item.dosage is not None else None,
        "dose_unit": item.dose_unit,
        "frequency": item.frequency,
        "route": item.route,
        "duration_days": item.duration_days,
    }
