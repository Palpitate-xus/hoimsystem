"""系统配置服务：管理员可配置的业务参数读取。

设计目标：收费标准等业务参数不硬编码，由管理员在系统配置里维护；
未配置时使用代码默认值，保证开箱即用。所有 key 自动初始化到 Config 表，
管理员通过 /api/config/getList + /api/config/update 维护。
"""
from sqlalchemy.orm import Session

from app.models import Config

# 业务默认参数（key → (默认值, 说明)）。首次访问自动落库供管理员调整。
DEFAULTS = {
    "registration_fee_common": ("10", "普通门诊挂号费（元）"),
    "registration_fee_specialist": ("30", "专家门诊挂号费（元）"),
    "surgery_fee_base": ("500", "手术费基础起价（元，按手术等级上浮的基数）"),
    "surgery_fee_level_multiplier": ("1.5", "手术费等级系数（级别每升一级费用×系数）"),
    "anesthesia_fee_base": ("300", "麻醉费基础起价（元）"),
    "deposit_warning_ratio": ("0.3", "预缴金余额预警线（剩余/已缴比例低于此值时开医嘱预警）"),
}


def _ensure_defaults(db: Session) -> None:
    """把默认项写入 Config 表（已存在的不覆盖管理员改动）。"""
    existing = {row.config_key for row in db.query(Config).all()}
    missing = [k for k in DEFAULTS if k not in existing]
    if not missing:
        return
    for key in missing:
        value, desc = DEFAULTS[key]
        db.add(Config(config_key=key, config_value=value, description=desc))
    db.commit()


def get_config_value(db: Session, key: str, fallback: str | None = None) -> str | None:
    """读取配置值；未配置返回 fallback（DEFAULTS 优先于调用方 fallback）。"""
    if key in DEFAULTS and fallback is None:
        fallback = DEFAULTS[key][0]
    row = db.query(Config).filter(Config.config_key == key).first()
    return (row.config_value if row and row.config_value not in (None, "") else fallback)


def get_config_float(db: Session, key: str, fallback: float) -> float:
    """读取数值配置；解析失败回退默认，保证业务不因脏配置中断。"""
    raw = get_config_value(db, key)
    try:
        return float(raw) if raw is not None else fallback
    except (TypeError, ValueError):
        return fallback
