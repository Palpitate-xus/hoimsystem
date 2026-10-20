"""One bounded offline recognition process; no database, network input or clinical writes."""

import json
import logging
import math
import os
import subprocess
import sys
from pathlib import Path

from fastapi import HTTPException

from app.ai.audio_files import AUDIO_FORMATS, inspect_audio, sniff_audio
from app.ai.speech_config import SpeechSettings, runtime_descriptor

MAX_RESPONSE_BYTES = 512 * 1024


def decode_native(path, source, max_seconds):
    """Use the same forced local demuxer as registration, with bounded mono float samples."""
    import numpy as np

    extension = source["extension"]
    with path.open("rb") as stream:
        sniff_audio(extension, stream.read(32))
    metadata = inspect_audio(path, extension)
    if metadata["duration_ms"] > max_seconds * 1000 or any(metadata[key] != source[key] for key in ("media_type", "duration_ms", "sample_rate", "channels", "codec")):
        raise ValueError("录音技术资料或适用时长不匹配")
    demuxer = AUDIO_FORMATS[extension][0]
    command = ["ffmpeg", "-v", "error", "-nostdin", "-xerror", "-err_detect", "explode", "-max_alloc", "33554432", "-protocol_whitelist", "file", "-f", demuxer]
    if demuxer == "mov":
        command += ["-enable_drefs", "0", "-use_absolute_path", "0"]
    command += [
        "-threads",
        "1",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-t",
        str(max_seconds + 1),
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-ar",
        "16000",
        "-ac",
        "1",
        "-c:a",
        "pcm_f32le",
        "-f",
        "f32le",
        "pipe:1",
    ]
    completed = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=False)
    if completed.returncode or not completed.stdout or len(completed.stdout) % 4 or len(completed.stdout) > max_seconds * 16000 * 4:
        raise ValueError("录音未能在限定范围内完整解码")
    samples = np.frombuffer(completed.stdout, dtype="<f4")
    duration = math.ceil(len(samples) * 1000 / 16000)
    if not np.isfinite(samples).all() or abs(duration - source["duration_ms"]) > 1:
        raise ValueError("实际样本时长与登记资料不一致")
    return samples, duration


def recognize(job):
    # Recheck the immutable model just before loading it, including after a queue wait.
    config = SpeechSettings(**job["config"])
    descriptor = runtime_descriptor(config)
    if descriptor["model_version"] != job["model_version"]:
        raise ValueError("语音模型或解码配置已变化")
    path, source = Path(job["audio_path"]), job["source"]
    samples, duration = decode_native(path, source, config.max_duration_seconds)
    from faster_whisper import WhisperModel

    model = WhisperModel(str(config.model_dir), device="cpu", compute_type="int8", cpu_threads=config.cpu_threads, num_workers=1, local_files_only=True)
    segments, info = model.transcribe(samples, **config.decoding_options())
    output = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        if not math.isfinite(segment.start) or not math.isfinite(segment.end):
            raise ValueError("模型返回无效时间")
        start, end = round(segment.start * 1000), round(segment.end * 1000)
        # Decoder timestamps estimate speech boundaries; the final estimate can exceed
        # the actual samples. Preserve that estimate in the review note and bound only
        # the playable interval. Never attach content starting outside the recording.
        if start < 0 or start >= min(duration, source["duration_ms"]) or end <= start or len(text) > 2000:
            raise ValueError("模型时间或文本超出原音范围")
        note = "自动识别草稿，尚未听音核对；未进行说话人区分，时间为模型估计"
        if end > source["duration_ms"]:
            note += f"；原模型末尾估计{end}ms，超出原音{source['duration_ms']}ms，听音范围已限定到原音末尾"
        output.append(
            {
                "start_ms": start,
                "end_ms": min(end, source["duration_ms"]),
                "speaker": "unknown",
                "speaker_role": "unknown",
                "text": text,
                "uncertain": True,
                "uncertainty_note": note,
                "source_id": source["source_id"],
            }
        )
        if len(output) > 1000:
            raise ValueError("转写分段超限，不能返回被截断的草稿")
    # Exhausting the generator is essential: transcribe() itself has not run the whole model.
    transcript = {
        "asset_id": source["asset_id"],
        "content_hash": source["content_hash"],
        "time_basis": "relative_decoded_audio",
        "speech_detected": bool(output),
        "language": info.language or "unknown",
        "segments": output,
        "processing": {
            "engine": descriptor["engine"],
            "engine_version": descriptor["engine_versions"]["faster-whisper"],
            "model_revision": descriptor["model_revision"],
            "model_digest": descriptor["model_digest"],
            "runtime_digest": descriptor["runtime_digest"],
            "decoding_options_hash": descriptor["decoding_options_hash"],
            "instructions_digest": job["instructions_digest"],
            "decoded_duration_ms": duration,
            "processed_duration_ms": duration,
            "submitted_samples": len(samples),
            "sample_rate": 16000,
            "iterator_exhausted": True,
            "vad_filter": True,
            "translation": False,
            "diarization": False,
            "prompt_handling": "acoustic_only",
            "timestamp_policy": "estimated_bounded_to_source",
        },
    }
    return {
        "schema_version": "2",
        "feature_key": "medical_transcription",
        "model_version": descriptor["model_version"],
        "applicable": True,
        "result": {
            "summary": f"已生成{len(output)}段待听音核对的转写草稿" if output else "识别器未返回可转写片段，请核对原音",
            "sections": [],
            "warnings": ["本地通用语音模型尚未提供医疗识别质量验证；药名、剂量、否定词和发言者须人工核实", "处理范围报告不保证逐字完整或识别准确；VAD可能漏检语音"],
            "missing_data": ["经核实的说话人身份、专科术语与医疗场景质量评估"],
        },
        "transcription": transcript,
    }


def main():
    logging.disable(logging.CRITICAL)
    try:
        raw = sys.stdin.buffer.read(131073)
        if len(raw) > 131072:
            raise ValueError("job too large")
        result = recognize(json.loads(raw))
        encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise ValueError("response too large")
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, HTTPException, subprocess.SubprocessError):
        # Never print recordings, decoded words, credentials or native-library exceptions.
        sys.stdout.write('{"error":"SPEECH_PROCESSING_FAILED"}')
        return 1
    sys.stdout.buffer.write(encoded)
    return 0


if __name__ == "__main__":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    sys.exit(main())
