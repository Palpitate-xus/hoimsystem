"""Authenticated schema12 declared-stage optimizer; no hospital DB or network."""

import argparse
import asyncio
import hashlib
import hmac
import json
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import Field, ValidationError, field_validator

from app.ai.surgery_config import SurgerySettings, runtime_descriptor, runtime_from_descriptor
from app.ai.surgery_contract import MAX_BYTES, StrictModel, SurgerySource, canonical_json
from app.ai.surgery_model import compute_surgery, generation_result_for_analysis, validate_analysis_binding


class SurgeryTaskContext(StrictModel):
    surgery_source: SurgerySource


class SurgeryTaskInput(StrictModel):
    context: SurgeryTaskContext


class SurgeryTask(StrictModel):
    schema_version: Literal["12"]
    feature_key: Literal["surgery_scheduling"]
    engine: Literal["optimizer"]
    model: str = Field(pattern=r"^surgery:[a-f0-9]{64}$")
    instructions: str = Field(min_length=1, max_length=80000)
    store: Literal[False]
    input: SurgeryTaskInput

    @field_validator("store", mode="before")
    @classmethod
    def actual_no_storage(cls, value):
        if value is not False:
            raise ValueError("Independent surgery scheduling cannot persist input")
        return value


def build_response(task, descriptor):
    digest = hashlib.sha256(task.instructions.encode()).hexdigest()
    source = task.input.context.surgery_source
    analysis = compute_surgery(source, digest, runtime_from_descriptor(descriptor))
    validate_analysis_binding(analysis, source, digest, task.model)
    value = {
        "schema_version": "12",
        "feature_key": "surgery_scheduling",
        "model_version": descriptor["model_version"],
        "handled": True,
        "result": generation_result_for_analysis(analysis),
        "surgery_analysis": analysis.model_dump(),
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    if len(canonical_json(value).encode()) > MAX_BYTES:
        raise ValueError("Complete surgery response exceeds UTF8 capacity; no truncation")
    return value


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON keys are not accepted")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("Nonfinite JSON numbers are not accepted")


def create_surgery_app(config):
    descriptor = runtime_descriptor(config)
    configuration = config.model_dump()
    credential = config.api_key.get_secret_value()
    env_keys = ("AI_PROVIDER_LOCAL_SURGERY_API_KEY", "SURGERY_MAX_REQUEST_BYTES", "SURGERY_TIMEOUT_SECONDS", "PYTHONTZPATH")
    environment = {key: os.environ.get(key) for key in env_keys}
    busy = asyncio.Lock()
    app = FastAPI(title="HOIM standalone declared-stage surgery optimizer", docs_url=None, redoc_url=None, openapi_url=None)

    def authenticate(request):
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), ("Bearer " + credential).encode()):
            raise HTTPException(401, "Surgery optimizer authentication failed")

    def check_runtime():
        try:
            current = runtime_descriptor(config)
        except (ValueError, OSError, ImportError) as exc:
            raise HTTPException(503, "Surgery implementation or timezone database cannot be verified") from exc
        if current != descriptor or config.model_dump() != configuration or environment != {key: os.environ.get(key) for key in env_keys}:
            raise HTTPException(503, "Surgery runtime or configuration changed; restart and revalidate")

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
            raise HTTPException(429, "Surgery optimizer is already processing a task")
        await busy.acquire()
        worker = None
        try:
            check_runtime()
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise HTTPException(422, "An application/json surgery task is required")
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > config.max_request_bytes:
                    raise HTTPException(413, "Complete task exceeds deployment UTF8 bound")
                chunks.append(chunk)
            try:
                task = SurgeryTask.model_validate(json.loads(b"".join(chunks), object_pairs_hook=_unique_object, parse_constant=_reject_constant))
                if task.model != descriptor["model_version"]:
                    raise HTTPException(409, "Requested surgery optimizer differs from actual runtime")
                worker = asyncio.create_task(asyncio.to_thread(build_response, task, descriptor))
                value = await asyncio.wait_for(asyncio.shield(worker), config.timeout_seconds)
                check_runtime()
                return value
            except TimeoutError as exc:
                raise HTTPException(504, "Surgery deterministic search exceeded deployment timeout") from exc
            except (ValidationError, ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError) as exc:
                raise HTTPException(422, "Invalid declared task, exact policy or complete scheduling binding") from exc
        finally:
            if worker is None or worker.done():
                busy.release()
            else:

                def release_after_actual_completion(future):
                    if not future.cancelled():
                        future.exception()
                    busy.release()

                worker.add_done_callback(release_after_actual_completion)

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8821, type=int)
    args = parser.parse_args()
    uvicorn.run(create_surgery_app(SurgerySettings()), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
