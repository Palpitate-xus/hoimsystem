"""Optional offline recognizer configuration, independent of the application database."""

import hashlib
from importlib.metadata import version
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.speech_model import canonical_json, verify_model

ENGINE_VERSIONS = {"faster-whisper": "1.2.1", "ctranslate2": "4.8.4", "onnxruntime": "1.31.1", "av": "18.1.0", "tokenizers": "0.23.3", "numpy": "2.5.4"}


class SpeechSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SPEECH_", env_file=None, extra="ignore")
    model_dir: Path
    api_key: SecretStr = Field(validation_alias="AI_PROVIDER_LOCAL_SPEECH_API_KEY")
    language: str = Field(default="zh", pattern=r"^[a-z]{2,3}$|^auto$")
    cpu_threads: int = Field(default=4, ge=1, le=16)
    beam_size: int = Field(default=5, ge=1, le=10)
    max_bytes: int = Field(default=67108864, ge=1024, le=268435456)
    max_duration_seconds: int = Field(default=300, ge=1, le=3600)
    timeout_seconds: int = Field(default=110, ge=3, le=110)

    @field_validator("model_dir")
    @classmethod
    def absolute_model_directory(cls, value: Path):
        # The recognition child runs from the package directory, not the caller's cwd.
        return value.expanduser().resolve()

    def decoding_options(self):
        return {
            "language": None if self.language == "auto" else self.language,
            "beam_size": self.beam_size,
            "temperature": 0.0,
            "condition_on_previous_text": False,
            "vad_filter": True,
            "task": "transcribe",
        }


def runtime_descriptor(config: SpeechSettings):
    if len(config.api_key.get_secret_value()) < 32:
        raise ValueError("本地语音服务须配置至少32字符的独立服务密钥")
    manifest = verify_model(config.model_dir)
    versions = {name: version(name) for name in ("faster-whisper", "ctranslate2", "onnxruntime", "av", "tokenizers", "numpy")}
    if versions != ENGINE_VERSIONS:
        raise ValueError("请使用已固定的语音运行依赖版本")
    identity = {"model_digest": manifest.digest, "versions": versions, "options": config.decoding_options(), "device": "cpu", "compute_type": "int8", "cpu_threads": config.cpu_threads}
    fingerprint = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    return {
        "schema_version": "2",
        "feature_key": "medical_transcription",
        "model_version": "fw:" + fingerprint,
        "engine": "faster-whisper",
        "engine_versions": versions,
        "model_repository": manifest.repository,
        "model_revision": manifest.revision,
        "model_digest": manifest.digest,
        "runtime_digest": fingerprint,
        "decoding_options_hash": hashlib.sha256(canonical_json(config.decoding_options()).encode()).hexdigest(),
        "language": config.language,
        "max_bytes": config.max_bytes,
        "max_duration_seconds": config.max_duration_seconds,
        "timeout_seconds": config.timeout_seconds,
        "prompt_handling": "acoustic_only",
        "diarization": False,
        "clinical_validation": "not_provided",
    }
