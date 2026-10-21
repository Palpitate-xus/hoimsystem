"""Authenticated standalone schema14 finite inventory candidate comparison; no hospital database or network."""

import argparse
import asyncio
import hashlib
import hmac
import json
import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import Field, ValidationError, field_validator

from app.ai.inventory_config import InventorySettings, runtime_descriptor, runtime_from_descriptor
from app.ai.inventory_contract import MAX_BYTES, InventorySource, StrictModel, canonical_json
from app.ai.inventory_model import compute_inventory, generation_result_for_analysis, validate_analysis_binding


class InventoryTaskContext(StrictModel):
    inventory_source: InventorySource


class InventoryTaskInput(StrictModel):
    context: InventoryTaskContext


class InventoryTask(StrictModel):
    schema_version: Literal["14"]
    feature_key: Literal["inventory_optimization"]
    engine: Literal["optimizer"]
    model: str = Field(pattern=r"^inventory:[a-f0-9]{64}$")
    instructions: str = Field(min_length=1, max_length=80000)
    store: Literal[False]
    input: InventoryTaskInput

    @field_validator("store", mode="before")
    @classmethod
    def actual_no_storage(cls, value):
        if value is not False:
            raise ValueError("Independent inventory statistics cannot persist input")
        return value


def build_response(task, descriptor):
    prompt_hash = hashlib.sha256(task.instructions.encode()).hexdigest()
    source = task.input.context.inventory_source
    analysis = compute_inventory(source, prompt_hash, runtime_from_descriptor(descriptor))
    validate_analysis_binding(analysis, source, prompt_hash, task.model)
    value = {
        "schema_version": "14",
        "feature_key": "inventory_optimization",
        "model_version": descriptor["model_version"],
        "handled": True,
        "result": generation_result_for_analysis(analysis),
        "inventory_analysis": analysis.model_dump(),
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    if len(canonical_json(value).encode()) > MAX_BYTES:
        raise ValueError("Complete inventory response exceeds the UTF-8 limit; no truncation is allowed")
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


def create_inventory_app(config):
    descriptor = runtime_descriptor(config)
    configuration = config.model_dump()
    credential = config.api_key.get_secret_value()
    env_keys = ("AI_PROVIDER_LOCAL_INVENTORY_API_KEY", "INVENTORY_MAX_REQUEST_BYTES", "INVENTORY_TIMEOUT_SECONDS", "PYTHONTZPATH")
    environment = {key: os.environ.get(key) for key in env_keys}
    busy = asyncio.Lock()
    app = FastAPI(title="HOIM standalone declared inventory candidate comparison", docs_url=None, redoc_url=None, openapi_url=None)

    def authenticate(request):
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), ("Bearer " + credential).encode()):
            raise HTTPException(401, "Inventory statistics authentication failed")

    def check_runtime():
        try:
            current = runtime_descriptor(config)
        except (ValueError, OSError, ImportError) as exc:
            raise HTTPException(503, "Inventory statistics implementation or timezone database cannot be verified") from exc
        if current != descriptor or config.model_dump() != configuration or environment != {key: os.environ.get(key) for key in env_keys}:
            raise HTTPException(503, "Inventory statistics runtime or configuration changed; restart and revalidate")

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
            raise HTTPException(429, "Inventory statistics is already processing a task")
        await busy.acquire()
        worker = None
        try:
            check_runtime()
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise HTTPException(422, "An application/json inventory statistics task is required")
            chunks, size = [], 0
            try:
                # A single whole-upload deadline prevents an authenticated slow
                # sender from reserving the only slot indefinitely. The compute
                # phase below has its own deadline; it is never reset per chunk.
                async with asyncio.timeout(config.timeout_seconds):
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > config.max_request_bytes:
                            raise HTTPException(413, "Complete task exceeds deployment UTF-8 bound")
                        chunks.append(chunk)
            except TimeoutError as exc:
                raise HTTPException(408, "Inventory task upload exceeded its independent deployment deadline") from exc
            try:
                task = InventoryTask.model_validate(json.loads(b"".join(chunks).decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant))
                if task.model != descriptor["model_version"]:
                    raise HTTPException(409, "Requested inventory statistics differs from actual runtime")
                worker = asyncio.create_task(asyncio.to_thread(build_response, task, descriptor))
                value = await asyncio.wait_for(asyncio.shield(worker), config.timeout_seconds)
                check_runtime()
                return value
            except TimeoutError as exc:
                raise HTTPException(504, "Inventory statistics deterministic calculation exceeded deployment timeout") from exc
            except (ValidationError, ValueError, TypeError, KeyError, OverflowError, RecursionError, UnicodeError) as exc:
                raise HTTPException(422, "Invalid original task, exact policy or complete forecasting binding") from exc
        finally:
            if worker is None or worker.done():
                busy.release()
            else:
                # A timeout/disconnection does not stop a stdlib worker thread.
                # Keep the slot reserved until it really finishes, preventing
                # concurrent unbounded background searches after a 504.
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
    parser.add_argument("--port", default=8823, type=int)
    args = parser.parse_args()
    uvicorn.run(create_inventory_app(InventorySettings()), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
