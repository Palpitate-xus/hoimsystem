"""Authenticated specialist v2 endpoint for the optional local CPU speech runtime."""

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import signal
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.ai.audio_files import AUDIO_FORMATS
from app.ai.speech_config import SpeechSettings, runtime_descriptor
from app.ai.speech_model import canonical_json

MAX_TASK_BYTES = 98304


class SpeechTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["2"]
    feature_key: Literal["medical_transcription"]
    engine: Literal["speech"]
    model: str = Field(min_length=1, max_length=160)
    instructions: str = Field(min_length=1, max_length=80000)
    store: bool = Field(strict=True)
    input: dict

    @model_validator(mode="after")
    def recording_only(self):
        if self.store:
            raise ValueError("本地服务只接受不保留副本的任务")
        context = self.input.get("context")
        if not isinstance(context, dict):
            raise ValueError("缺少原音资料")
        source = context.get("audio_source", {})
        SpeechSource.model_validate(source)
        return self


class SpeechSource(BaseModel):
    model_config = ConfigDict(extra="ignore")
    asset_id: str
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    extension: str
    media_type: str
    byte_size: int = Field(gt=0, strict=True)
    duration_ms: int = Field(gt=0, strict=True)
    sample_rate: int = Field(ge=1000, le=192000, strict=True)
    channels: int = Field(ge=1, le=8, strict=True)
    codec: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def source_identity(self):
        if str(uuid.UUID(self.asset_id)) != self.asset_id or self.extension not in AUDIO_FORMATS or self.media_type != AUDIO_FORMATS[self.extension][1]:
            raise ValueError("原音标识或格式无效")
        if self.source_id != f"audio:{self.asset_id}:{self.content_hash[:12]}":
            raise ValueError("原音引用与字节资料不符")
        return self


async def execute_job(job, timeout):
    # Keep application/model credentials out of the child process environment.
    environment = {key: value for key, value in os.environ.items() if key in {"PATH", "SYSTEMROOT", "LD_LIBRARY_PATH", "LANG", "LC_ALL"}}
    environment.update(
        {"HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "OMP_NUM_THREADS": str(job["config"]["cpu_threads"]), "AI_AUDIO_MAX_DURATION_SECONDS": str(job["config"]["max_duration_seconds"])}
    )
    with tempfile.TemporaryFile() as output:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.ai.speech_worker",
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
                raise HTTPException(422, "本地识别未生成完整可用结果，请核对原音与模型适用范围")
            output.seek(0)
            return json.loads(output.read())
        except TimeoutError as exc:
            raise HTTPException(504, "本地语音识别超过处理时限，请缩短录音或调整部署资源") from exc
        finally:
            if process.returncode is None:
                # Also terminate any decoder descendant when the request is cancelled or expires.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()


def create_speech_app(config: SpeechSettings, *, executor=None):
    descriptor = runtime_descriptor(config)
    executor = executor or execute_job
    busy = asyncio.Lock()
    app = FastAPI(title="HOIM local speech adapter", docs_url=None, redoc_url=None, openapi_url=None, default_response_class=JSONResponse)

    def authenticate(request):
        supplied = request.headers.get("authorization", "")
        if not hmac.compare_digest(supplied.encode(), ("Bearer " + config.api_key.get_secret_value()).encode()):
            raise HTTPException(401, "语音服务鉴权失败")

    @app.get("/health/ready")
    async def ready():
        return {"ready": True}

    @app.get("/capabilities")
    async def capabilities(request: Request):
        authenticate(request)
        return descriptor

    @app.post("/tasks")
    async def transcribe(request: Request):
        authenticate(request)
        if busy.locked():
            raise HTTPException(429, "本地语音服务正在处理其他录音，请稍后重试")
        async with busy:
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
                if set(form.keys()) != {"task", "audio"} or not isinstance(form["task"], str) or not isinstance(form["audio"], UploadFile) or len(form["task"].encode()) > MAX_TASK_BYTES:
                    raise HTTPException(422, "须提供唯一的task和原audio附件")
                task = SpeechTask.model_validate_json(form["task"])
                source = SpeechSource.model_validate(task.input["context"]["audio_source"]).model_dump()
                if task.model != descriptor["model_version"]:
                    raise HTTPException(409, "所请求模型与本地实际模型版本不同")
                if source["byte_size"] > config.max_bytes or source["duration_ms"] > config.max_duration_seconds * 1000:
                    raise HTTPException(413, "原录音超出本地服务的大小或时长范围")
                if form["audio"].content_type != source["media_type"]:
                    raise HTTPException(422, "原录音附件格式与资料不一致")
                with tempfile.TemporaryDirectory(prefix="hoim-speech-") as temporary:
                    path = Path(temporary) / ("recording" + source["extension"])
                    digest, size = hashlib.sha256(), 0
                    with path.open("xb") as stream:
                        os.chmod(path, 0o600)
                        while block := form["audio"].file.read(65536):
                            size += len(block)
                            if size > min(config.max_bytes, source["byte_size"]):
                                raise HTTPException(413, "原录音附件超过登记或部署范围")
                            digest.update(block)
                            stream.write(block)
                    if size != source["byte_size"] or digest.hexdigest() != source["content_hash"]:
                        raise HTTPException(422, "原录音实际字节与登记哈希或长度不符")
                    job = {
                        "audio_path": str(path),
                        "source": source,
                        "model_version": task.model,
                        "instructions_digest": hashlib.sha256(task.instructions.encode()).hexdigest(),
                        "config": {**config.model_dump(mode="json", exclude={"api_key"}), "AI_PROVIDER_LOCAL_SPEECH_API_KEY": "offline-child-not-an-authentication-token"},
                    }
                    # This is an acoustic recognizer: free text and full system instructions are
                    # deliberately not used as initial_prompt/hotwords or fabricated spoken content.
                    # The child needs no service credential; use a fixed non-secret for its config check.
                    return await executor(job, config.timeout_seconds)
            except MultiPartException as exc:
                raise HTTPException(413 if exc.message == "body_limit" else 422, "录音表单超过范围或结构无效") from exc
            except (ValidationError, ValueError, TypeError, KeyError, AttributeError) as exc:
                raise HTTPException(422, "语音任务或原录音资料结构无效") from exc
            finally:
                if form is not None:
                    await form.close()

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true", help="Print the actual model identity and supported scope without serving")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8810)
    parser.add_argument("--ssl-certfile")
    parser.add_argument("--ssl-keyfile")
    args = parser.parse_args()
    config = SpeechSettings()
    if args.describe:
        print(canonical_json(runtime_descriptor(config)))
        return
    import uvicorn

    uvicorn.run(create_speech_app(config), host=args.host, port=args.port, ssl_certfile=args.ssl_certfile, ssl_keyfile=args.ssl_keyfile, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
