"""Strict frozen registration-count sources and deterministic forecast evidence."""

import hashlib
import json
import re
import uuid
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Count = Annotated[int, Field(strict=True, ge=0)]
Finite = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]
Recipe = Literal["weekday_mean_4w", "seasonal_naive_7d", "rolling_mean_7d", "rolling_mean_28d"]
MIN_HISTORY_DAYS = 112
MAX_HISTORY_DAYS = 366
RECIPE = {
    "recipe": "weekday_mean_4w",
    "version": "registration_daily_v1",
    "history_days": {"min": MIN_HISTORY_DAYS, "max": MAX_HISTORY_DAYS},
    "horizon_days": [7, 14],
    "training_min_days": 28,
    "backtest_origins": 28,
    "backtest_origin_step_days": 1,
    "baselines": ["seasonal_naive_7d", "rolling_mean_7d", "rolling_mean_28d"],
    "model_selection": "fixed_no_selection",
    "interval": {
        "nominal_coverage": 0.9,
        "residual_window": 28,
        "minimum_residuals": 20,
        "order": "ceil((n+1)*0.9)",
        "availability": "prior_origin_and_target_on_or_before_origin",
        "lower": "max(0,point-q)",
        "upper": "point+q",
        "coverage_guarantee": "not_provided",
    },
    "mase": {"lag_days": 7, "scale": "origin_prefix_mean_abs_lag7", "zero_scale": "any_zero_makes_aggregate_null"},
    "missing_dates": "reject_never_fill",
    "prompt_handling": "provenance_only",
}


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def source_content_hash(value: dict) -> str:
    return hashlib.sha256(canonical_json({key: item for key, item in value.items() if key not in {"source_id", "content_hash"}}).encode()).hexdigest()


def canonical_date(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("日期须为规范YYYY-MM-DD")
    return value


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ForecastObservation(StrictModel):
    date: str
    value: int = Field(strict=True, ge=0, le=2147483647)
    _date = field_validator("date")(canonical_date)


class ForecastSourceBinding(StrictModel):
    series_id: str
    source_id: str = Field(min_length=58, max_length=58)
    content_hash: SHA256
    target: Literal["registration_record_count"]
    grain: Literal["day"]
    scope: Literal["hospital", "department"]
    department_id: int | None = Field(strict=True, gt=0)
    date_from: str
    date_to: str
    timezone: str = Field(min_length=1, max_length=80)
    time_basis: Literal["naive_registration_time"]
    coverage_status: Literal["super_admin_attested"]
    coverage_attested_at: str = Field(min_length=20, max_length=40)
    coverage_note_hash: SHA256
    registration_digest: SHA256
    unassigned_time_records: Count
    _dates = field_validator("date_from", "date_to")(canonical_date)

    @field_validator("coverage_attested_at")
    @classmethod
    def explicit_utc(cls, value):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)", value):
            raise ValueError("覆盖确认须为显式UTC ISO时刻")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() != timedelta(0):
            raise ValueError("覆盖确认须为UTC")
        return value

    @model_validator(mode="after")
    def identity_and_scope(self):
        if str(uuid.UUID(self.series_id)) != self.series_id or self.source_id != f"forecast:{self.series_id}:{self.content_hash[:12]}":
            raise ValueError("预测来源标识不一致")
        if (self.scope == "hospital") != (self.department_id is None):
            raise ValueError("预测范围与科室不一致")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("须声明有效IANA时区；原登记时间仍为无时区数据库时间") from exc
        return self


class ForecastSource(ForecastSourceBinding):
    observations: list[ForecastObservation] = Field(min_length=MIN_HISTORY_DAYS, max_length=MAX_HISTORY_DAYS)

    @model_validator(mode="after")
    def complete_frozen_series(self):
        if self.observations[0].date != self.date_from or self.observations[-1].date != self.date_to:
            raise ValueError("来源首末日期不一致")
        start = date.fromisoformat(self.date_from)
        for offset, observation in enumerate(self.observations):
            try:
                expected = start + timedelta(days=offset)
            except OverflowError as exc:
                raise ValueError("原日序列超出有效公历范围") from exc
            if date.fromisoformat(observation.date) != expected:
                raise ValueError("原日序列须连续、唯一且有明确零值，不补缺日")
        if source_content_hash(self.model_dump()) != self.content_hash:
            raise ValueError("冻结来源内容哈希不一致")
        return self


class ForecastMetrics(StrictModel):
    n: int = Field(strict=True, ge=1)
    mae: Nonnegative
    rmse: Nonnegative
    wape: Nonnegative | None
    wape_numerator_abs_error: Nonnegative
    wape_denominator_actual: Count
    wape_undefined_reason: Literal["zero_actual_sum"] | None
    mase: Nonnegative | None
    mase_scaled_pairs: Count
    mase_zero_scale_pairs: Count
    mase_undefined_reason: Literal["zero_origin_scale"] | None


class LeadMetrics(StrictModel):
    lead_days: int = Field(strict=True, ge=1, le=14)
    metrics: ForecastMetrics


class OriginScale(StrictModel):
    origin_date: str
    training_days: int = Field(strict=True, ge=28, le=366)
    lag_pair_count: int = Field(strict=True, ge=21)
    absolute_difference_sum: Count
    scale: Nonnegative
    _date = field_validator("origin_date")(canonical_date)


class MASEScale(StrictModel):
    lag_days: Literal[7]
    method: Literal["origin_prefix_mean_abs_lag7"]
    origins: list[OriginScale] = Field(min_length=28, max_length=28)


class IntervalMetrics(StrictModel):
    covered_count: Count
    evaluated_count: int = Field(strict=True, ge=1)
    empirical_coverage: float = Field(strict=True, allow_inf_nan=False, ge=0, le=1)
    unique_target_dates: int = Field(strict=True, ge=1)
    mean_width: Nonnegative
    calibration_n_min: int = Field(strict=True, ge=20, le=28)
    calibration_n_max: int = Field(strict=True, ge=20, le=28)


class LeadIntervals(IntervalMetrics):
    lead_days: int = Field(strict=True, ge=1, le=14)


class BacktestIntervals(IntervalMetrics):
    nominal_coverage: Literal[0.9]
    coverage_guarantee: Literal["not_provided"]
    by_lead: list[LeadIntervals] = Field(min_length=7, max_length=14)


class BaselineComparison(StrictModel):
    recipe: Literal["seasonal_naive_7d", "rolling_mean_7d", "rolling_mean_28d"]
    metrics: ForecastMetrics
    by_lead: list[LeadMetrics] = Field(min_length=7, max_length=14)


class ForecastBacktest(StrictModel):
    data_basis: Literal["current_snapshot_retrospective"]
    origin_count: Literal[28]
    origin_from: str
    origin_to: str
    horizon_days: Literal[7, 14]
    forecast_pair_count: int = Field(strict=True, ge=196, le=392)
    unique_target_dates: int = Field(strict=True, ge=34, le=41)
    overlapping_targets: Literal[True]
    primary_metrics: ForecastMetrics
    primary_by_lead: list[LeadMetrics] = Field(min_length=7, max_length=14)
    baselines: list[BaselineComparison] = Field(min_length=3, max_length=3)
    intervals: BacktestIntervals
    mase_scale: MASEScale
    _dates = field_validator("origin_from", "origin_to")(canonical_date)


class ForecastPoint(StrictModel):
    date: str
    lead_days: int = Field(strict=True, ge=1, le=14)
    point: Nonnegative
    lower: Nonnegative
    upper: Nonnegative
    calibration_n: int = Field(strict=True, ge=20, le=28)
    calibration_order: int = Field(strict=True, ge=1, le=28)
    calibration_quantile: Nonnegative
    calibration_last_target_date: str
    _dates = field_validator("date", "calibration_last_target_date")(canonical_date)


class ForecastRuntime(StrictModel):
    engine: Literal["stdlib-statistical-forecast"]
    recipe: Literal["weekday_mean_4w"]
    recipe_digest: SHA256
    implementation: dict[str, SHA256] = Field(min_length=4, max_length=4)
    python_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    engine_versions: dict[str, str] = Field(min_length=2, max_length=2)
    runtime_digest: SHA256
    model_version: str = Field(pattern=r"^stat-forecast:[a-f0-9]{64}$")
    prompt_handling: Literal["provenance_only"]
    clinical_validation: Literal["not_provided"]
    operational_validation: Literal["not_provided"]
    coverage_guarantee: Literal["not_provided"]


class ForecastAnalysis(StrictModel):
    schema_version: Literal["1"]
    source_binding: ForecastSourceBinding
    recipe: Literal["weekday_mean_4w"]
    horizon_days: Literal[7, 14]
    history_days: int = Field(strict=True, ge=MIN_HISTORY_DAYS, le=MAX_HISTORY_DAYS)
    forecast: list[ForecastPoint] = Field(min_length=7, max_length=14)
    backtest: ForecastBacktest
    local_runtime: ForecastRuntime
    instructions_digest: SHA256
