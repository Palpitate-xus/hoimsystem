"""Strict arithmetic on manually assigned clinical score components.

This module does not derive points from observations or estimate clinical risk.
Definitions retain the original SOFA (1996), APACHE II (1985), Aldrete
colour-based (1970) and three-domain Steward (1975) editions. In particular,
the original Aldrete colour item is not the modified oxygen-saturation item.

Reviewed sources:
GCS: https://www.glasgowcomascale.org/gcs-aid/
NT: https://www.glasgowcomascale.org/faq/
SOFA: https://www.esicm.org/wp-content/uploads/2018/03/esicmworking5-2.pdf
APACHE II: https://doi.org/10.1097/00003246-198510000-00009
APACHE II form: https://www.cms.gov/files/document/hcfr-84-supp-091pdf
Aldrete: https://doi.org/10.1213/00000539-197011000-00020
Steward: https://link.springer.com/content/pdf/10.1007/BF03004827.pdf
"""

import datetime
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CALCULATION_VERSION = "manual_components_v2"
LEGACY_CALCULATION_VERSION = "legacy_unverified"
SOURCE_VERIFICATION = "not_independently_verified"
SCORE_SCENES = frozenset({"icu", "pacu"})


@dataclass(frozen=True)
class ScoreComponent:
    key: str
    label: str
    allowed: tuple[int, ...]


@dataclass(frozen=True)
class ScoreDefinition:
    edition: str
    label: str
    components: tuple[ScoreComponent, ...]
    scope_note: str


SCORE_DEFINITIONS = {
    "gcs": ScoreDefinition(
        "gcs_e4_v5_m6",
        "GCS（E4/V5/M6）",
        (ScoreComponent("eye", "睁眼", (1, 2, 3, 4)), ScoreComponent("verbal", "语言", (1, 2, 3, 4, 5)), ScoreComponent("motor", "运动", (1, 2, 3, 4, 5, 6))),
        "仅汇总人工填写的睁眼、语言及运动分项；未测或NT不可计算总分，不由总分自动判断诊断或预后。",
    ),
    "sofa": ScoreDefinition(
        "sofa_1996",
        "SOFA（1996原版）",
        tuple(
            ScoreComponent(key, label, (0, 1, 2, 3, 4))
            for key, label in (("resp_score", "呼吸"), ("coag_score", "凝血"), ("liver_score", "肝脏"), ("cardio_score", "心血管"), ("neuro_score", "中枢神经"), ("renal_score", "肾脏"))
        ),
        "仅汇总人工六分项，未从原始生理资料自动评分或核实取值时间窗；不是SOFA 2.0，不据此确认脏器功能、脓毒症或死亡风险。",
    ),
    "apache2": ScoreDefinition(
        "apache_ii_1985_manual_aps",
        "APACHE II（1985，人工APS小计）",
        (ScoreComponent("aps_total", "外部人工APS小计", tuple(range(61))), ScoreComponent("age_points", "年龄分", (0, 2, 3, 5, 6)), ScoreComponent("chronic_health_points", "慢性健康分", (0, 2, 5))),
        "APS是外部人工小计，本系统未自动评估12项生理参数、年龄对应关系、慢性健康条件或首24小时窗口，不生成死亡风险分级。",
    ),
    "aldrete": ScoreDefinition(
        "aldrete_1970_color",
        "Aldrete（1970原版，肤色项）",
        tuple(
            ScoreComponent(key, label, (0, 1, 2))
            for key, label in (("activity_score", "活动"), ("respiration_score", "呼吸"), ("circulation_score", "循环"), ("consciousness_score", "意识"), ("color_score", "肤色"))
        ),
        "仅汇总1970原版人工五分项，肤色项不等同于1995改良版氧饱和度项；不自动认定达到PACU转出或出院条件。",
    ),
    "steward": ScoreDefinition(
        "steward_1975",
        "Steward（1975三分项版）",
        tuple(ScoreComponent(key, label, (0, 1, 2)) for key, label in (("wake_score", "清醒程度"), ("airway_score", "呼吸道通畅"), ("motor_score", "肢体活动"))),
        "仅汇总1975三分项人工评分，不替代持续观察，也不自动认定达到PACU转出或出院条件。",
    ),
}


def _component_problems(score_type: str, detail: object) -> tuple[list[str], list[str], list[str]]:
    definition = SCORE_DEFINITIONS[score_type]
    expected = [item.key for item in definition.components]
    if type(detail) is not dict:
        return expected, [], expected
    missing = [key for key in expected if key not in detail]
    unexpected = [str(key) for key in detail if key not in expected]
    invalid = [item.key for item in definition.components if item.key in detail and (type(detail[item.key]) is not int or detail[item.key] not in item.allowed)]
    return missing, unexpected, invalid


def compute_manual_score(score_type: str, detail: dict) -> tuple[int, str]:
    """Sum every explicitly supplied integer component; never impute a value."""
    if type(score_type) is not str or score_type not in SCORE_DEFINITIONS:
        raise ValueError("评分类型必须为 apache2/sofa/gcs/aldrete/steward")
    if type(detail) is not dict:
        raise ValueError("评分detail须为完整分项对象")
    definition = SCORE_DEFINITIONS[score_type]
    missing, unexpected, invalid = _component_problems(score_type, detail)
    if missing:
        raise ValueError("评分分项缺失：" + "、".join(missing) + "；未测或NT不可按0或默认值汇总")
    if unexpected:
        raise ValueError("评分包含未定义分项：" + "、".join(unexpected))
    if invalid:
        descriptions = [f"{item.key}须为整数[{','.join(map(str, item.allowed))}]" for item in definition.components if item.key in invalid]
        raise ValueError("评分分项取值无效：" + "；".join(descriptions) + "；不接受布尔、字符串、小数或NT")
    total = sum(detail[item.key] for item in definition.components)
    return total, f"{definition.label}人工分项合计{total}分；来源未独立核实。{definition.scope_note}"


def inspect_manual_components(score_type: str, detail: object, stored_total: object, calculation_version: str) -> dict:
    """Describe stored component integrity without changing a historical record."""
    definition = SCORE_DEFINITIONS.get(score_type)
    legacy = calculation_version != CALCULATION_VERSION
    if definition is None:
        return {
            "status": "legacy_unverified" if legacy else "invalid",
            "required_keys": [],
            "missing_keys": [],
            "unexpected_keys": [],
            "invalid_keys": [],
            "total_matches": None,
            "source_verification": SOURCE_VERIFICATION,
        }
    missing, unexpected, invalid = _component_problems(score_type, detail)
    matches = None
    if not legacy and not (missing or unexpected or invalid):
        total, _ = compute_manual_score(score_type, detail)
        matches = type(stored_total) is int and total == stored_total
    status = "legacy_unverified" if legacy else "complete" if matches else "invalid"
    return {
        "status": status,
        "required_keys": [item.key for item in definition.components],
        "missing_keys": missing,
        "unexpected_keys": unexpected,
        "invalid_keys": invalid,
        "total_matches": matches,
        "source_verification": SOURCE_VERIFICATION,
    }


class ManualScoreRequest(BaseModel):
    """Strict request metadata; observation-to-point assignment remains manual."""

    model_config = ConfigDict(extra="forbid")
    patient_id: int = Field(strict=True, ge=1, le=2**63 - 1)
    admission_id: str | None = Field(default=None, strict=True, max_length=36)
    score_type: Literal["gcs", "sofa", "apache2", "aldrete", "steward"]
    scene: Literal["icu", "pacu"] = "icu"
    detail: dict[str, Any] = Field(strict=True, max_length=6)
    assessed_at: datetime.datetime | None = None

    @field_validator("admission_id")
    @classmethod
    def optional_admission(cls, value):
        return value.strip() or None if value is not None else None

    @field_validator("assessed_at", mode="before")
    @classmethod
    def explicit_assessment_time(cls, value):
        if value is None:
            return None
        if type(value) is not str or not value or len(value) > 64:
            raise ValueError("assessed_at须为带时区的ISO时间，未知时留空")
        try:
            parsed = datetime.datetime.fromisoformat(value)
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("assessed_at必须显式包含时区")
            return parsed.astimezone(datetime.UTC).replace(tzinfo=None)
        except (ValueError, OverflowError) as exc:
            raise ValueError("assessed_at须为有效且带时区的ISO时间，未知时不以录入时间代替") from exc
