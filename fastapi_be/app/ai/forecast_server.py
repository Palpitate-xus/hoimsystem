"""Authenticated offline registration-count statistics service (v5; no database)."""

import argparse
import asyncio
import hashlib
import hmac
import json
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError, field_validator

from app.ai.forecast_config import ForecastSettings, runtime_descriptor, runtime_from_descriptor
from app.ai.forecast_contract import ForecastAnalysis, ForecastSource, StrictModel
from app.ai.forecast_model import forecast_values, validate_analysis_binding


class ForecastTaskContext(StrictModel):
    forecast_source: ForecastSource


class ForecastTaskInput(StrictModel):
    context: ForecastTaskContext
    horizon_days: Literal[7, 14]

    @field_validator("horizon_days", mode="before")
    @classmethod
    def exact_integer_horizon(cls, value):
        if type(value) is not int:
            raise ValueError("预测日数须为整数7或14")
        return value


class ForecastTask(StrictModel):
    schema_version: Literal["5"]
    feature_key: Literal["visit_forecast"]
    engine: Literal["prediction"]
    model: str = Field(min_length=1, max_length=160)
    instructions: str = Field(min_length=1, max_length=80000)
    store: Literal[False]
    input: ForecastTaskInput

    @field_validator("store", mode="before")
    @classmethod
    def no_persistence(cls, value):
        if value is not False:
            raise ValueError("统计服务不保留输入")
        return value


def build_response(task, descriptor):
    source, horizon = task.input.context.forecast_source, task.input.horizon_days
    instructions_digest = hashlib.sha256(task.instructions.encode()).hexdigest()
    analysis = ForecastAnalysis.model_validate(
        {
            "schema_version": "1",
            "source_binding": source.model_dump(exclude={"observations"}),
            **forecast_values([item.model_dump() for item in source.observations], horizon),
            "local_runtime": runtime_from_descriptor(descriptor),
            "instructions_digest": instructions_digest,
        }
    )
    validate_analysis_binding(analysis, source, horizon, instructions_digest, task.model)
    warnings = [
        "预测目标是每日挂号创建记录数，包含已取消记录；不是实际到诊人数或独立患者数。",
        "预测日期从所选历史窗口末日后开始；旧窗口的外推日期可能已过去，不声称均为相对今天的未来。",
        "覆盖由超级管理员声明；外部历史完整性、原无时区登记时间与所声明时区的对应关系未独立核实。",
        "回测基于当前已确认快照按历史前缀重算，不是历史时点数据库as-of回放；同一目标日期在不同折与步长重复计入，不是独立样本。",
        "名义90%经验区间使用此前已发生目标的绝对误差；不保证时间序列未来覆盖率，工程测试不证明运营预测有效性。",
        "固定weekday_mean_4w算法不按回测成绩自动择优；完整Prompt仅作溯源，不改变数值，结果不自动调整排班或号源。",
    ]
    if source.unassigned_time_records:
        warnings.append(f"范围内另有{source.unassigned_time_records}条原登记时间为空的记录，无法分日，已排除于历史日序列。")
    missing = []
    metrics = analysis.backtest.primary_metrics
    if metrics.wape is None:
        missing.append("回测实际记录数合计为0，WAPE不可计算。")
    if metrics.mase is None:
        missing.append("至少一个历史前缀的7日季节尺度为0，整体MASE不可计算；未挑选非零尺度子集。")
    return {
        "schema_version": "5",
        "feature_key": "visit_forecast",
        "model_version": descriptor["model_version"],
        "applicable": True,
        "result": {
            "summary": f"基于{source.date_from}至{source.date_to}的{len(source.observations)}个已确认连续日，按固定算法外推其后{horizon}日的挂号创建记录数，须由运营人员复核。",
            "sections": [
                {
                    "title": "固定日挂号记录数预测",
                    "content": "逐日点估计、经验区间、28个完整滚动起点的回测与三种共同样本基线见结构化预测表。误差按预测对计算，保留原分母与零尺度不可计算项。",
                    "source_ids": [source.source_id],
                }
            ],
            "warnings": warnings,
            "missing_data": missing,
        },
        "forecast_analysis": analysis.model_dump(),
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("重复JSON字段")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("不接受非有限JSON数值")


def create_forecast_app(config):
    descriptor = runtime_descriptor(config)
    busy = asyncio.Lock()
    app = FastAPI(title="HOIM local registration record forecast", docs_url=None, redoc_url=None, openapi_url=None, default_response_class=JSONResponse)

    def authenticate(request):
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), ("Bearer " + config.api_key.get_secret_value()).encode()):
            raise HTTPException(401, "统计服务鉴权失败")

    def check_runtime():
        try:
            current = runtime_descriptor(config)
        except (ValueError, OSError, ImportError) as exc:
            raise HTTPException(503, "统计服务运行文件或依赖无法核实") from exc
        if current != descriptor:
            raise HTTPException(503, "统计服务运行版本已变化，请重启并重新核对配置")

    @app.get("/health/ready")
    async def ready():
        check_runtime()
        return {"ready": True}

    @app.get("/capabilities")
    async def capabilities(request: Request):
        authenticate(request)
        check_runtime()
        return descriptor

    @app.post("/tasks")
    async def forecast(request: Request):
        authenticate(request)
        if busy.locked():
            raise HTTPException(429, "统计服务正在执行其他任务，请稍后重试")
        async with busy:
            check_runtime()
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise HTTPException(422, "须提供JSON统计任务")
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > config.max_request_bytes:
                    raise HTTPException(413, "统计任务超过部署大小上限")
                chunks.append(chunk)
            try:
                value = json.loads(b"".join(chunks), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
                task = ForecastTask.model_validate(value)
                if task.model != descriptor["model_version"]:
                    raise HTTPException(409, "所请求统计模型与实际运行版本不同")
                return await asyncio.wait_for(asyncio.to_thread(build_response, task, descriptor), config.timeout_seconds)
            except TimeoutError as exc:
                raise HTTPException(504, "统计任务超时，请核对服务资源") from exc
            except (ValidationError, ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeDecodeError) as exc:
                raise HTTPException(422, "统计任务、来源覆盖、日期或固定数值契约无效") from exc

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8813, type=int)
    args = parser.parse_args()
    uvicorn.run(create_forecast_app(ForecastSettings()), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
