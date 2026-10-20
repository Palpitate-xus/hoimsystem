"""Run the actual bounded v5 adapter with synthetic series and no hospital imports."""

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.ai.forecast_config import ForecastSettings, runtime_descriptor
from app.ai.forecast_contract import ForecastAnalysis, ForecastSource, canonical_json, source_content_hash
from app.ai.forecast_model import validate_analysis_binding
from app.ai.forecast_server import create_forecast_app

SYNTHETIC_KEY = "synthetic-statistical-smoke-not-a-production-credential"
INSTRUCTIONS = "Compute the fixed registration record count recipe from this synthetic series. Preserve actual intervals and evaluation denominators. Do not infer patient arrivals or change operational settings."


def synthetic_source(name, values):
    start = date(2024, 1, 1)
    source = {
        "series_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "hoim-statistical-smoke:" + name)),
        "target": "registration_record_count",
        "grain": "day",
        "scope": "hospital",
        "department_id": None,
        "date_from": str(start),
        "date_to": str(start + timedelta(days=len(values) - 1)),
        "timezone": "UTC",
        "time_basis": "naive_registration_time",
        "coverage_status": "super_admin_attested",
        "coverage_attested_at": "2024-12-31T12:00:00.123456+00:00",
        "coverage_note_hash": hashlib.sha256(b"Nonclinical synthetic count series only; no independent operational validation").hexdigest(),
        "registration_digest": hashlib.sha256(canonical_json({"synthetic_scenario": name, "values": values}).encode()).hexdigest(),
        "unassigned_time_records": 0,
        "observations": [{"date": str(start + timedelta(days=index)), "value": value} for index, value in enumerate(values)],
    }
    source["content_hash"] = source_content_hash(source)
    source["source_id"] = "forecast:" + source["series_id"] + ":" + source["content_hash"][:12]
    return ForecastSource.model_validate(source).model_dump()


async def smoke():
    started = time.monotonic()
    config = ForecastSettings(AI_PROVIDER_LOCAL_FORECAST_API_KEY=SYNTHETIC_KEY)
    descriptor = runtime_descriptor(config)
    cases = [("all_zero", [0] * 112, 7), ("positive_constant", [12] * 112, 14), ("weekly_trend", [[4, 8, 12, 20, 24, 6, 0][index % 7] + 2 * (index // 28) for index in range(112)], 14)]
    records = []
    app = create_forecast_app(config)
    headers = {"Authorization": "Bearer " + SYNTHETIC_KEY}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8813", headers=headers) as client:
        metadata = await client.get("/capabilities")
        assert metadata.status_code == 200 and metadata.json() == descriptor
        for name, values, horizon in cases:
            source = synthetic_source(name, values)
            task = {
                "schema_version": "5",
                "feature_key": "visit_forecast",
                "engine": "prediction",
                "model": descriptor["model_version"],
                "store": False,
                "instructions": INSTRUCTIONS,
                "input": {"context": {"forecast_source": source}, "horizon_days": horizon},
            }
            response = await client.post("/tasks", json=task)
            assert response.status_code == 200, (name, response.status_code)
            result = response.json()
            analysis = ForecastAnalysis.model_validate(result["forecast_analysis"])
            validate_analysis_binding(analysis, ForecastSource.model_validate(source), horizon, hashlib.sha256(INSTRUCTIONS.encode()).hexdigest(), descriptor["model_version"])
            metrics = analysis.backtest.primary_metrics
            assert analysis.backtest.forecast_pair_count == 28 * horizon and len(analysis.forecast) == horizon
            if name == "all_zero":
                assert metrics.wape is None and metrics.mase is None
                assert all(item.point == item.lower == item.upper == 0 for item in analysis.forecast)
            elif name == "positive_constant":
                assert metrics.wape == 0 and metrics.mase is None
                assert all(item.point == item.lower == item.upper == 12 for item in analysis.forecast)
            else:
                assert metrics.wape_denominator_actual > 0 and metrics.mase_zero_scale_pairs == 0
            numeric = analysis.model_dump(exclude={"local_runtime"})
            records.append(
                {
                    "case": name,
                    "horizon_days": horizon,
                    "source_hash": source["content_hash"],
                    "numeric_digest": hashlib.sha256(canonical_json(numeric).encode()).hexdigest(),
                    "forecast_pair_count": analysis.backtest.forecast_pair_count,
                    "unique_target_dates": analysis.backtest.unique_target_dates,
                    "wape": metrics.wape,
                    "wape_numerator_abs_error": metrics.wape_numerator_abs_error,
                    "wape_denominator_actual": metrics.wape_denominator_actual,
                    "mase": metrics.mase,
                    "interval_evaluated_count": analysis.backtest.intervals.evaluated_count,
                    "interval_covered_count": analysis.backtest.intervals.covered_count,
                    "all_numbers_recomputed": True,
                }
            )
        invalid = dict(task)
        invalid["input"] = {"context": {"forecast_source": {**source, "observations": source["observations"][:-1]}}, "horizon_days": 14}
        rejected = await client.post("/tasks", json=invalid)
        assert rejected.status_code == 422
        unauthorized = await client.post("/tasks", headers={"Authorization": "Bearer wrong-synthetic-key"}, json=task)
        assert unauthorized.status_code == 401
    forbidden = [name for name in ("app.config", "app.database", "app.models", "app.main", "sqlalchemy", "numpy", "torch") if name in sys.modules]
    assert not forbidden, forbidden
    return {
        "synthetic_only": True,
        "clinical_or_operational_validation": False,
        "existing_database_accessed": False,
        "external_network_or_model_used": False,
        "actual_v5_service_execution": True,
        "cases": records,
        "invalid_source_status": rejected.status_code,
        "unauthorized_status": unauthorized.status_code,
        "runtime": descriptor,
        "effective_uid": os.getuid(),
        "forbidden_modules_imported": forbidden,
        "seconds": round(time.monotonic() - started, 4),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    record = asyncio.run(smoke())
    encoded = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(encoded)
    else:
        print(encoded, end="")


if __name__ == "__main__":
    main()
