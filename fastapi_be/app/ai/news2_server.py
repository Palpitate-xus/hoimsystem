"""Authenticated offline NEWS2 arithmetic service; no hospital database or models."""

import argparse
import asyncio
import hashlib
import hmac
import json
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError, field_validator

from app.ai.news2_config import News2Settings, runtime_descriptor, runtime_from_descriptor
from app.ai.news2_contract import News2Analysis, News2Source, StrictModel
from app.ai.news2_model import generation_result_for_analysis, news2_values, validate_analysis_binding


class News2TaskContext(StrictModel):
    news2_source: News2Source


class News2TaskInput(StrictModel):
    context: News2TaskContext


class News2Task(StrictModel):
    schema_version: Literal["6"]
    feature_key: Literal["deterioration_risk"]
    engine: Literal["prediction"]
    model: str = Field(min_length=1, max_length=160)
    instructions: str = Field(min_length=1, max_length=80000)
    store: Literal[False]
    input: News2TaskInput

    @field_validator("store", mode="before")
    @classmethod
    def no_persistence(cls, value):
        if value is not False:
            raise ValueError("NEWS2服务不保留输入")
        return value


def build_response(task, descriptor):
    source = task.input.context.news2_source
    instructions_digest = hashlib.sha256(task.instructions.encode()).hexdigest()
    analysis = News2Analysis.model_validate(
        {"schema_version": "1", "source_binding": source.model_dump(), **news2_values(source), "local_runtime": runtime_from_descriptor(descriptor), "instructions_digest": instructions_digest}
    )
    validate_analysis_binding(analysis, source, instructions_digest, task.model)
    return {
        "schema_version": "6",
        "feature_key": "deterioration_risk",
        "model_version": descriptor["model_version"],
        "handled": True,
        "result": generation_result_for_analysis(analysis),
        "news2_analysis": analysis.model_dump(),
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("不接受重复JSON字段")
        value[key] = item
    return value


def _reject_constant(_):
    raise ValueError("不接受非有限JSON常量")


def create_news2_app(config):
    descriptor = runtime_descriptor(config)
    configuration = config.model_dump()
    configuration_env = {key: os.environ.get(key) for key in ("AI_PROVIDER_LOCAL_NEWS2_API_KEY", "NEWS2_MAX_REQUEST_BYTES", "NEWS2_TIMEOUT_SECONDS")}
    credential = config.api_key.get_secret_value()
    busy = asyncio.Lock()
    app = FastAPI(title="HOIM independent local NEWS2 rules", docs_url=None, redoc_url=None, openapi_url=None, default_response_class=JSONResponse)

    def authenticate(request):
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), ("Bearer " + credential).encode()):
            raise HTTPException(401, "NEWS2服务鉴权失败")

    def check_runtime():
        try:
            current = runtime_descriptor(config)
        except (ValueError, OSError, ImportError) as exc:
            raise HTTPException(503, "NEWS2运行文件或依赖无法核实") from exc
        if config.model_dump() != configuration or current != descriptor or {key: os.environ.get(key) for key in configuration_env} != configuration_env:
            raise HTTPException(503, "NEWS2运行或配置已变化，请重启并重新核对")

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
    async def calculate(request: Request):
        authenticate(request)
        if busy.locked():
            raise HTTPException(429, "NEWS2服务正在处理其他任务")
        async with busy:
            check_runtime()
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise HTTPException(422, "须提供JSON NEWS2任务")
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > config.max_request_bytes:
                    raise HTTPException(413, "NEWS2任务超过部署大小限制")
                chunks.append(chunk)
            try:
                task = News2Task.model_validate(json.loads(b"".join(chunks), object_pairs_hook=_unique_object, parse_constant=_reject_constant))
                if task.model != descriptor["model_version"]:
                    raise HTTPException(409, "所请求NEWS2模型与实际运行版本不同")
                result = await asyncio.wait_for(asyncio.to_thread(build_response, task, descriptor), config.timeout_seconds)
                check_runtime()
                return result
            except TimeoutError as exc:
                raise HTTPException(504, "NEWS2规则核对超时") from exc
            except (ValidationError, ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError) as exc:
                raise HTTPException(422, "NEWS2任务、原始输入或固定规则绑定无效") from exc

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8814, type=int)
    args = parser.parse_args()
    uvicorn.run(create_news2_app(News2Settings()), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
