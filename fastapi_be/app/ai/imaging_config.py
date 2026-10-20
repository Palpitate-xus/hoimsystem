"""Offline research image runtime, independent of hospital settings and credentials."""

import hashlib
import platform
import sys
from importlib.metadata import version
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.imaging_model import LABELS, canonical_json, verify_model
from app.ai.imaging_preprocessing import PREPROCESSING


class ImagingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="IMAGING_", env_file=None, extra="ignore")
    model_dir: Path
    api_key: SecretStr = Field(validation_alias="AI_PROVIDER_LOCAL_IMAGING_API_KEY")
    cpu_threads: int = Field(default=4, ge=1, le=16)
    max_bytes: int = Field(default=64 * 1024 * 1024, ge=1024, le=64 * 1024 * 1024)
    timeout_seconds: int = Field(default=60, ge=3, le=110)

    @field_validator("model_dir")
    @classmethod
    def absolute_model_directory(cls, value):
        return value.expanduser().resolve()


def runtime_descriptor(config):
    if len(config.api_key.get_secret_value()) < 32:
        raise ValueError("本地影像服务须配置至少32字符的独立密钥")
    manifest = verify_model(config.model_dir)
    versions = {name: version(name) for name in ("torch", "numpy", "safetensors")}
    if versions != {"torch": "2.14.1+cpu", "numpy": "2.4.4", "safetensors": "0.8.0"}:
        raise ValueError("请使用固定的可选CPU影像运行依赖")
    preprocessing_digest = hashlib.sha256(canonical_json(PREPROCESSING).encode()).hexdigest()
    files = ("imaging_model.py", "imaging_network.py", "imaging_contract.py", "imaging_preprocessing.py", "imaging_config.py", "imaging_worker.py", "imaging_server.py")
    identity = {
        "model_digest": manifest.digest,
        "versions": versions,
        "preprocessing_digest": preprocessing_digest,
        "device": "cpu",
        "cpu_threads": config.cpu_threads,
        "implementation": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in files},
        "python_version": platform.python_version(),
        "machine": platform.machine(),
        "byte_order": sys.byteorder,
    }
    fingerprint = hashlib.sha256(canonical_json(identity).encode()).hexdigest()
    return {
        "schema_version": "4",
        "feature_key": "imaging_detection",
        "model_version": "xrv:" + fingerprint,
        "engine": "torchxrayvision-densenet121",
        "engine_versions": versions,
        "model_repository": manifest.repository,
        "model_revision": manifest.revision,
        "model_digest": manifest.digest,
        "runtime_digest": fingerprint,
        "preprocessing_digest": preprocessing_digest,
        "profile": "xrv_stored_range_v1",
        "preprocessing": PREPROCESSING,
        "labels": LABELS,
        "prompt_handling": "pixels_only",
        "clinical_validation": "not_provided",
        "population_applicability": "not_verified",
        "max_bytes": config.max_bytes,
        "timeout_seconds": config.timeout_seconds,
    }
