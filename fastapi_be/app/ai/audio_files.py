"""Private audio files, bounded native decoding and immutable byte verification."""

import hashlib
import json
import os
import select
import stat
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import HTTPException

from app.config import settings

# Force a demuxer selected by a fixed suffix and content signature, never a caller URL.
AUDIO_FORMATS = {
    ".wav": ("wav", "audio/wav"),
    ".mp3": ("mp3", "audio/mpeg"),
    ".m4a": ("mov", "audio/mp4"),
    ".ogg": ("ogg", "audio/ogg"),
    ".oga": ("ogg", "audio/ogg"),
    ".webm": ("matroska", "audio/webm"),
}


def audio_root():
    root = Path(settings.AI_AUDIO_STORAGE_DIR).expanduser().resolve()
    # These bytes must never share the report/avatar download namespace.
    from app.routers.upload import UPLOAD_DIR

    if root == Path(UPLOAD_DIR).resolve() or Path(UPLOAD_DIR).resolve() in root.parents:
        raise HTTPException(503, "录音存储必须位于通用上传目录之外")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    return root


def audio_path(asset_id):
    try:
        if str(uuid.UUID(asset_id)) != asset_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(422, "录音标识格式不正确") from exc
    return audio_root() / (asset_id + ".audio")


def sniff_audio(extension, header):
    valid = {
        ".wav": header[:4] == b"RIFF" and header[8:12] == b"WAVE",
        ".mp3": header[:3] == b"ID3" or (len(header) >= 2 and header[0] == 255 and header[1] & 0xE0 == 0xE0),
        ".m4a": header[4:8] == b"ftyp",
        ".ogg": header[:4] == b"OggS",
        ".oga": header[:4] == b"OggS",
        ".webm": header[:4] == b"\x1aE\xdf\xa3",
    }
    if not valid.get(extension):
        raise HTTPException(422, "录音内容与所选音频格式不一致")


def _command_output(command, cap=16384):
    with tempfile.TemporaryFile() as output:
        try:
            completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL, timeout=settings.AI_AUDIO_PROCESS_TIMEOUT_SECONDS, check=False)
        except FileNotFoundError as exc:
            raise HTTPException(503, "录音处理组件未安装，请在API与worker环境安装FFmpeg") from exc
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(422, "录音校验超过处理时限，请缩小文件或整理原录音") from exc
        if completed.returncode or output.tell() > cap:
            raise HTTPException(422, "录音无法完整解析或包含不适用的数据，请核对原文件")
        output.seek(0)
        return output.read(cap + 1)


def _decoded_duration(command):
    """Count bounded 8kHz mono s16 validation output, never retaining a decoded copy."""
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise HTTPException(503, "录音处理组件未安装，请在API与worker环境安装FFmpeg") from exc
    deadline = time.monotonic() + settings.AI_AUDIO_PROCESS_TIMEOUT_SECONDS
    size = 0
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([process.stdout], [], [], max(0, remaining))[0]:
                raise HTTPException(422, "录音解码超过处理时限，请缩小文件或整理原录音")
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            size += len(chunk)
            if size > settings.AI_AUDIO_MAX_DURATION_SECONDS * 16000:
                raise HTTPException(422, "录音实际解码时长超过限制")
        try:
            code = process.wait(timeout=max(0.01, deadline - time.monotonic()))
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(422, "录音解码超过处理时限") from exc
        if code or size <= 0 or size % 2:
            raise HTTPException(422, "录音未能完整解码，请核对原文件")
        return (size * 1000 + 15999) // 16000
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()


def inspect_audio(path, extension):
    demuxer, media_type = AUDIO_FORMATS[extension]
    common = ["-v", "error", "-max_alloc", "33554432", "-protocol_whitelist", "file", "-f", demuxer]
    if demuxer == "mov":
        common += ["-enable_drefs", "0", "-use_absolute_path", "0"]
    raw = _command_output(["ffprobe", *common, "-show_entries", "stream=codec_type,codec_name,sample_rate,channels", "-of", "json", "-i", str(path)])
    try:
        streams = json.loads(raw)["streams"]
        if len(streams) != 1 or streams[0].get("codec_type") != "audio":
            raise ValueError()
        stream = streams[0]
        rate, channels = int(stream["sample_rate"]), int(stream["channels"])
        codec = stream["codec_name"]
        if not 1 <= channels <= 8 or not 1000 <= rate <= 192000 or not isinstance(codec, str) or not 1 <= len(codec) <= 80:
            raise ValueError()
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, "须提供单一音轨的纯音频，且采样率和声道资料可核实") from exc
    # Counting decoded samples also handles browser WebM without a duration header.
    # Do not use progress's last packet timestamp: short recordings can report zero.
    duration_ms = _decoded_duration(
        [
            "ffmpeg",
            *common,
            "-nostdin",
            "-xerror",
            "-err_detect",
            "explode",
            "-threads",
            "1",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-t",
            str(settings.AI_AUDIO_MAX_DURATION_SECONDS + 1),
            "-threads",
            "1",
            "-filter_threads",
            "1",
            "-ar",
            "8000",
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            "-f",
            "s16le",
            "pipe:1",
        ],
    )
    return {"media_type": media_type, "duration_ms": duration_ms, "sample_rate": rate, "channels": channels, "codec": codec}


def stage_audio(upload):
    extension = Path(upload.filename or "").suffix.lower()
    if extension not in AUDIO_FORMATS:
        raise HTTPException(422, "支持WAV、MP3、M4A、Ogg和WebM录音")
    path = audio_root() / (str(uuid.uuid4()) + ".part")
    size, hasher = 0, hashlib.sha256()
    try:
        with path.open("xb") as output:
            os.chmod(path, 0o600)
            while chunk := upload.file.read(65536):
                size += len(chunk)
                if size > settings.AI_AUDIO_MAX_BYTES:
                    raise HTTPException(413, "录音超过当前文件大小限制")
                hasher.update(chunk)
                output.write(chunk)
        if not size:
            raise HTTPException(422, "录音为空")
        with path.open("rb") as source:
            sniff_audio(extension, source.read(32))
        return path, {"extension": extension, "byte_size": size, "content_hash": hasher.hexdigest(), **inspect_audio(path, extension)}
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def open_verified_audio(asset):
    """Return this very file handle for transmission, after checking bytes and avoiding symlink traversal."""
    path = audio_path(asset.asset_id)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise HTTPException(409, "原录音文件不可用，请核实私有存储") from exc
    source = os.fdopen(descriptor, "rb")
    try:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != asset.byte_size or metadata.st_size > settings.AI_AUDIO_MAX_BYTES:
            raise HTTPException(409, "原录音大小或类型已变化，请重新登记")
        hasher = hashlib.sha256()
        while chunk := source.read(65536):
            hasher.update(chunk)
        if hasher.hexdigest() != asset.content_hash:
            raise HTTPException(409, "原录音内容已变化，请重新登记")
        source.seek(0)
        return source
    except BaseException:
        source.close()
        raise
