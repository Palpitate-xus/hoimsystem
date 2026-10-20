"""Authenticated v4 native-image service with one bounded offline CPU child per task."""

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import signal
import sys
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.ai.imaging_config import ImagingSettings, runtime_descriptor
from app.ai.imaging_contract import ImageSource
from app.ai.imaging_model import canonical_json

MAX_TASK_BYTES = 98304


class ImagingTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["4"]
    feature_key: Literal["imaging_detection"]
    engine: Literal["vision"]
    model: str = Field(min_length=1, max_length=160)
    instructions: str = Field(min_length=1, max_length=80000)
    store: bool = Field(strict=True)
    input: dict

    @model_validator(mode="after")
    def native_source_only(self):
        if self.store:
            raise ValueError("本地服务不保留患者像素副本")
        ImageSource.model_validate(self.input["context"]["image_source"])
        return self


async def execute_job(job, timeout):
    environment = {key: value for key, value in os.environ.items() if key in {"PATH", "SYSTEMROOT", "LD_LIBRARY_PATH", "LANG", "LC_ALL"}}
    environment.update({"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "OMP_NUM_THREADS": str(job["config"]["cpu_threads"]), "MKL_NUM_THREADS": str(job["config"]["cpu_threads"])})
    with tempfile.TemporaryFile() as output:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.ai.imaging_worker",
            stdin=asyncio.subprocess.PIPE,
            stdout=output,
            stderr=asyncio.subprocess.DEVNULL,
            env=environment,
            start_new_session=True,
            cwd=Path(__file__).resolve().parents[2],
        )
        try:
            await asyncio.wait_for(process.communicate(canonical_json(job).encode()), timeout)
            if process.returncode or output.tell() > 512 * 1024:
                raise HTTPException(422, "本地胸片模型未生成完整结果，请核对真实像素及研究输入范围")
            output.seek(0)
            return json.loads(output.read())
        except TimeoutError as exc:
            raise HTTPException(504, "本地影像处理超过时限，请核对部署资源") from exc
        finally:
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()


def create_imaging_app(config, *, executor=None):
    descriptor = runtime_descriptor(config)
    executor = executor or execute_job
    busy = asyncio.Lock()
    app = FastAPI(title="HOIM local research image adapter", docs_url=None, redoc_url=None, openapi_url=None, default_response_class=JSONResponse)

    def authenticate(request):
        if not hmac.compare_digest(request.headers.get("authorization", "").encode(), ("Bearer " + config.api_key.get_secret_value()).encode()):
            raise HTTPException(401, "影像服务鉴权失败")

    def check_runtime():
        try:
            current = runtime_descriptor(config)
        except (ValueError, OSError, ImportError) as exc:
            raise HTTPException(503, "当前影像模型或运行文件无法核实，请重新部署后检查") from exc
        if current != descriptor:
            raise HTTPException(503, "影像运行版本已变化，请重启服务后重新核对配置")

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
    async def analyze(request: Request):
        authenticate(request)
        if busy.locked():
            raise HTTPException(429, "本地影像服务正在处理其他原图，请稍后重试")
        async with busy:
            check_runtime()
            received = 0

            async def bounded_body():
                nonlocal received
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > config.max_bytes + MAX_TASK_BYTES + 8192:
                        raise MultiPartException("body_limit")
                    yield chunk

            form = None
            try:
                form = await MultiPartParser(request.headers, bounded_body(), max_files=1, max_fields=1, max_part_size=MAX_TASK_BYTES).parse()
                if (
                    len(form.multi_items()) != 2
                    or set(form.keys()) != {"task", "image"}
                    or not isinstance(form["task"], str)
                    or not isinstance(form["image"], UploadFile)
                    or len(form["task"].encode()) > MAX_TASK_BYTES
                ):
                    raise HTTPException(422, "须提供唯一task和实际原始image像素附件")
                task = ImagingTask.model_validate_json(form["task"])
                source = ImageSource.model_validate(task.input["context"]["image_source"]).model_dump()
                if task.model != descriptor["model_version"]:
                    raise HTTPException(409, "所请求影像模型与实际运行版本不同")
                if source["pixel_byte_size"] > config.max_bytes:
                    raise HTTPException(413, "原像素超出本地部署大小范围")
                if form["image"].content_type != "application/octet-stream":
                    raise HTTPException(422, "须提供实际小端int32原存储像素，不接受DICOM头或截图替代")
                with tempfile.TemporaryDirectory(prefix="hoim-imaging-") as temporary:
                    path = Path(temporary) / "pixels.i32le"
                    digest, size = hashlib.sha256(), 0
                    with path.open("xb") as output:
                        os.chmod(path, 0o600)
                        while block := form["image"].file.read(65536):
                            size += len(block)
                            if size > min(config.max_bytes, source["pixel_byte_size"]):
                                raise HTTPException(413, "实际像素超出登记或部署范围")
                            digest.update(block)
                            output.write(block)
                    if size != source["pixel_byte_size"] or digest.hexdigest() != source["pixel_hash"]:
                        raise HTTPException(422, "实际像素字节数或哈希与登记来源不一致")
                    job = {
                        "image_path": str(path),
                        "source": source,
                        "model_version": task.model,
                        "instructions_digest": hashlib.sha256(task.instructions.encode()).hexdigest(),
                        "config": {**config.model_dump(mode="json", exclude={"api_key"}), "AI_PROVIDER_LOCAL_IMAGING_API_KEY": "offline-child-not-an-authentication-token"},
                    }
                    return await executor(job, config.timeout_seconds)
            except MultiPartException as exc:
                raise HTTPException(413 if exc.message == "body_limit" else 422, "影像表单超过范围或结构无效") from exc
            except (ValidationError, ValueError, TypeError, KeyError, AttributeError) as exc:
                raise HTTPException(422, "影像任务、来源或实际研究输入范围无效") from exc
            finally:
                if form is not None:
                    await form.close()

    return app


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8812, type=int)
    parser.add_argument("--ssl-certfile")
    parser.add_argument("--ssl-keyfile")
    args = parser.parse_args()
    uvicorn.run(create_imaging_app(ImagingSettings()), host=args.host, port=args.port, ssl_certfile=args.ssl_certfile, ssl_keyfile=args.ssl_keyfile, access_log=False)


if __name__ == "__main__":
    main()
