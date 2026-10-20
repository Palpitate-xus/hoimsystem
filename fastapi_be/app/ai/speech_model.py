"""Identify offline CTranslate2 weights by their actual files, never a mutable model alias."""

import hashlib
import json
import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

MODEL_FILES = {"config.json", "model.bin", "tokenizer.json", "vocabulary.txt", "vocabulary.json", "preprocessor_config.json"}
REQUIRED_FILES = {"config.json", "model.bin", "tokenizer.json"}
MANIFEST_NAME = "hoim-speech-model.json"


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


class ModelFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    size: int = Field(gt=0, strict=True)


class SpeechModelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: str = "1"
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=160)
    revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    files: dict[str, ModelFile]

    @model_validator(mode="after")
    def known_offline_files(self):
        if self.format_version != "1" or not REQUIRED_FILES <= self.files.keys() or set(self.files) - MODEL_FILES or not {"vocabulary.txt", "vocabulary.json"}.intersection(self.files):
            raise ValueError("须提供完整且类型已知的本地语音模型文件")
        return self

    @property
    def digest(self):
        return hashlib.sha256(canonical_json(self.model_dump()).encode()).hexdigest()


def create_manifest(directory: Path, repository: str, revision: str):
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("模型版本必须是固定的40位提交哈希，不能使用main或标签")
    files = {}
    for name in sorted(MODEL_FILES):
        path = directory / name
        if path.is_file():
            if path.is_symlink():
                raise ValueError("模型目录不能包含指向其他位置的符号链接")
            files[name] = {"size": path.stat().st_size, "sha256": sha256_file(path)}
    manifest = SpeechModelManifest(repository=repository, revision=revision, files=files)
    (directory / MANIFEST_NAME).write_text(canonical_json(manifest.model_dump()) + "\n", encoding="utf-8")
    return manifest


def verify_model(directory: Path):
    manifest_path = directory / MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 16384:
        raise ValueError("缺少可核实的本地语音模型清单")
    manifest = SpeechModelManifest.model_validate_json(manifest_path.read_bytes())
    # Include every file the runtime can consume; adding another vocabulary must change identity too.
    if {name for name in MODEL_FILES if (directory / name).exists()} != set(manifest.files):
        raise ValueError("模型目录文件与清单不一致")
    for name, expected in manifest.files.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != expected.size or sha256_file(path) != expected.sha256:
            raise ValueError("本地语音模型文件与固定清单不一致")
    return manifest
