"""Authenticated offline qSOFA arithmetic service; no hospital database or models."""

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

from app.ai.qsofa_config import QsofaSettings, runtime_descriptor, runtime_from_descriptor
from app.ai.qsofa_contract import QsofaAnalysis, QsofaSource, StrictModel
from app.ai.qsofa_model import generation_result_for_analysis, qsofa_values, validate_analysis_binding


class QsofaTaskContext(StrictModel):
    qsofa_source: QsofaSource


class QsofaTaskInput(StrictModel):
    context: QsofaTaskContext


class QsofaTask(StrictModel):
    schema_version: Literal["8"]
    feature_key: Literal["sepsis_risk"]
    engine: Literal["prediction"]
    model: str = Field(min_length=1, max_length=160)
    instructions: str = Field(min_length=1, max_length=80000)
    store: Literal[False]
    input: QsofaTaskInput

    @field_validator("store", mode="before")
    @classmethod
    def no_persistence(cls, value):
        if value is not False:
            raise ValueError("qSOFA服务不保留输入")
        return value


def build_response(task, descriptor):
    source = task.input.context.qsofa_source
    instructions_digest = hashlib.sha256(task.instructions.encode()).hexdigest()
    analysis = QsofaAnalysis.model_validate(
        {"schema_version": "1", "source_binding": source.model_dump(), **qsofa_values(source), "local_runtime": runtime_from_descriptor(descriptor), "instructions_digest": instructions_digest}
    )
    validate_analysis_binding(analysis, source, instructions_digest, task.model)
    return {
        "schema_version": "8",
        "feature_key": "sepsis_risk",
        "model_version": descriptor["model_version"],
        "handled": True,
        "result": generation_result_for_analysis(analysis),
        "qsofa_analysis": analysis.model_dump(),
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


def create_qsofa_app(config):
    descriptor = runtime_descriptor(config)
    configuration = config.model_dump()
    configuration_env = {key: os.environ.get(key) for key in ("AI_PROVIDER_LOCAL_QSOFA_API_KEY", "QSOFA_MAX_REQUEST_BYTES", "QSOFA_TIMEOUT_SECONDS")}
    credential = config.api_key.get_secret_value()
    busy = asyncio.Lock()
    app = FastAPI(title="HOIM independent local qSOFA rules", docs_url=None, redoc_url=None, openapi_url=None, default_response_class=JSONResponse)

    def authenticate(request):
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), ("Bearer " + credential).encode()):
            raise HTTPException(401, "qSOFA服务鉴权失败")

    def check_runtime():
        try:
            current = runtime_descriptor(config)
        except (ValueError, OSError, ImportError) as exc:
            raise HTTPException(503, "qSOFA运行文件或依赖无法核实") from exc
        if config.model_dump() != configuration or current != descriptor or {key: os.environ.get(key) for key in configuration_env} != configuration_env:
            raise HTTPException(503, "qSOFA运行或配置已变化，请重启并重新核对")

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
            raise HTTPException(429, "qSOFA服务正在处理其他任务")
        async with busy:
            check_runtime()
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise HTTPException(422, "须提供JSON qSOFA任务")
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > config.max_request_bytes:
                    raise HTTPException(413, "qSOFA任务超过部署大小限制")
                chunks.append(chunk)
            try:
                task = QsofaTask.model_validate(json.loads(b"".join(chunks), object_pairs_hook=_unique_object, parse_constant=_reject_constant))
                if task.model != descriptor["model_version"]:
                    raise HTTPException(409, "所请求qSOFA模型与实际运行版本不同")
                result = await asyncio.wait_for(asyncio.to_thread(build_response, task, descriptor), config.timeout_seconds)
                check_runtime()
                return result
            except TimeoutError as exc:
                raise HTTPException(504, "qSOFA规则核对超时") from exc
            except (ValidationError, ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError) as exc:
                raise HTTPException(422, "qSOFA任务、原始输入或固定规则绑定无效") from exc

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8816, type=int)
    args = parser.parse_args()
    uvicorn.run(create_qsofa_app(QsofaSettings()), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
