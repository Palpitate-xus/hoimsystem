"""Authenticated offline SOFA arithmetic service, no hospital data or persistence."""

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

from app.ai.sofa_config import SofaSettings, runtime_descriptor, runtime_from_descriptor
from app.ai.sofa_contract import MAX_RESPONSE_BYTES, SofaSource, StrictModel, canonical_json
from app.ai.sofa_model import compute_sofa, generation_result_for_analysis, validate_analysis_binding


class SofaTaskContext(StrictModel):
    sofa_source: SofaSource


class SofaTaskInput(StrictModel):
    context: SofaTaskContext


class SofaTask(StrictModel):
    schema_version: Literal["9"]
    feature_key: Literal["sepsis_risk"]
    engine: Literal["prediction"]
    model: str = Field(min_length=1, max_length=160)
    instructions: str = Field(min_length=1, max_length=80000)
    store: Literal[False]
    input: SofaTaskInput

    @field_validator("store", mode="before")
    @classmethod
    def no_persistence(cls, value):
        if value is not False:
            raise ValueError("SOFA服务不保留输入")
        return value


def build_response(task, descriptor):
    source = task.input.context.sofa_source
    prompt_hash = hashlib.sha256(task.instructions.encode()).hexdigest()
    analysis = compute_sofa(source, prompt_hash, runtime_from_descriptor(descriptor))
    validate_analysis_binding(analysis, source, prompt_hash, task.model)
    result = {
        "schema_version": "9",
        "feature_key": "sepsis_risk",
        "model_version": descriptor["model_version"],
        "handled": True,
        "result": generation_result_for_analysis(analysis),
        "sofa_analysis": analysis.model_dump(),
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    if len(canonical_json(result).encode()) > MAX_RESPONSE_BYTES:
        raise ValueError("SOFA完整响应超过8MiB，不截断证据")
    return result


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("不接受重复JSON字段")
        value[key] = item
    return value


def _reject_constant(_):
    raise ValueError("不接受非有限JSON常量")


def create_sofa_app(config):
    descriptor = runtime_descriptor(config)
    configuration = config.model_dump()
    env_keys = ("AI_PROVIDER_LOCAL_SOFA_API_KEY", "SOFA_MAX_REQUEST_BYTES", "SOFA_TIMEOUT_SECONDS")
    configuration_env = {key: os.environ.get(key) for key in env_keys}
    credential = config.api_key.get_secret_value()
    busy = asyncio.Lock()
    app = FastAPI(title="HOIM independent local SOFA-1 native rules", docs_url=None, redoc_url=None, openapi_url=None, default_response_class=JSONResponse)

    def authenticate(request):
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), ("Bearer " + credential).encode()):
            raise HTTPException(401, "SOFA服务鉴权失败")

    def check_runtime():
        try:
            current = runtime_descriptor(config)
        except (ValueError, OSError, ImportError) as exc:
            raise HTTPException(503, "SOFA运行文件或依赖无法核实") from exc
        if config.model_dump() != configuration or current != descriptor or {key: os.environ.get(key) for key in env_keys} != configuration_env:
            raise HTTPException(503, "SOFA运行或配置已变化，请重启并重新核对")

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
            raise HTTPException(429, "SOFA服务正在处理其他任务")
        async with busy:
            check_runtime()
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise HTTPException(422, "须提供JSON SOFA任务")
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > config.max_request_bytes:
                    raise HTTPException(413, "SOFA完整任务超过部署大小限制")
                chunks.append(chunk)
            try:
                task = SofaTask.model_validate(json.loads(b"".join(chunks), object_pairs_hook=_unique_object, parse_constant=_reject_constant))
                if task.model != descriptor["model_version"]:
                    raise HTTPException(409, "所请求SOFA模型与实际运行版本不同")
                result = await asyncio.wait_for(asyncio.to_thread(build_response, task, descriptor), config.timeout_seconds)
                check_runtime()
                return result
            except TimeoutError as exc:
                raise HTTPException(504, "SOFA固定数学核对超时") from exc
            except (ValidationError, ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError) as exc:
                raise HTTPException(422, "SOFA原始输入、固定规则或输出绑定无效") from exc

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8818, type=int)
    args = parser.parse_args()
    uvicorn.run(create_sofa_app(SofaSettings()), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
