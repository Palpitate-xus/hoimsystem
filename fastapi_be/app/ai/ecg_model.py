"""Verify the reviewed, permissively licensed checkpoint without executing model-repository code."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REPOSITORY = "Tumo505/SSL-ECG-Classification-model-card"
REVISION = "6ec2ee1a1badd9508f9c1219fb07de38f3f6936b"
LEADS = ["I", "II", "III", "aVR", "aVL", "aVF", "V1", "V2", "V3", "V4", "V5", "V6"]
LABELS = ["NORM", "CD", "HYP", "MI", "STTC"]
MANIFEST_NAME = "hoim-ecg-model.json"
# Reviewed release, including the original license and preprocessing/label provenance.
RELEASE_FILES = {
    "model.safetensors": (2170628, "c2497259f7f672fee5568b1906e95272f256f057a6860f3aa60acf8f8d903db8"),
    "config.json": (1093, "36c896f1d05b92f59a0e004ef034c69ba74ea0a77936859244bf0d94d57c66ce"),
    "LICENSE": (11357, "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"),
    "README.md": (8159, "f9559d9e12bcf9321840847a040a1656e7c36d713a8d42ea88268f79be917bfc"),
    "provenance.json": (7110, "4a7dddb0c52f0f47a47ae4f95446a370af14369a5de09425b73ded87de1dee13"),
}
PREPROCESSING = {
    "format": "wfdb16",
    "original_sample_rate_hz": 100,
    "original_samples_per_lead": 1000,
    "required_leads": LEADS,
    "calibration": "(ADC-baseline)/gain*original_unit_to_mV; float64 then float32",
    "lead_selection": "exact twelve original leads; explicit permutation to required order",
    "normalization": "per_record_per_lead_population_std_v1",
    "normalization_dtype": "numpy.float32",
    "normalization_epsilon": 1e-6,
    "normalization_epsilon_policy": "floor_standard_deviation",
    "missing_sample_policy": "reject",
    "resampling": False,
    "filtering": False,
    "padding": False,
    "cropping": False,
    "output": "independent sigmoid for all five recording-level labels; no diagnosis threshold",
    "label_order": LABELS,
    "prompt_handling": "signal_only",
}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(65536):
            digest.update(block)
    return digest.hexdigest()


class ModelFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: int = Field(gt=0, strict=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ECGModelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal["1"] = "1"
    repository: Literal["Tumo505/SSL-ECG-Classification-model-card"] = REPOSITORY
    revision: Literal["6ec2ee1a1badd9508f9c1219fb07de38f3f6936b"] = REVISION
    files: dict[str, ModelFile]

    @model_validator(mode="after")
    def reviewed_checkpoint_only(self):
        if set(self.files) != set(RELEASE_FILES) or any((item.size, item.sha256) != RELEASE_FILES[name] for name, item in self.files.items()):
            raise ValueError("心电模型清单与已审查的固定发布不符")
        return self

    @property
    def digest(self):
        return hashlib.sha256(canonical_json(self.model_dump()).encode()).hexdigest()


def verify_release_files(directory):
    directory = Path(directory)
    for name, (size, digest) in RELEASE_FILES.items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size or sha256_file(path) != digest:
            raise ValueError("心电模型文件与已审查固定发布不一致")
    return {name: {"size": size, "sha256": digest} for name, (size, digest) in sorted(RELEASE_FILES.items())}


def create_manifest(directory):
    directory = Path(directory)
    manifest = ECGModelManifest(files=verify_release_files(directory))
    (directory / MANIFEST_NAME).write_text(canonical_json(manifest.model_dump()) + "\n")
    return manifest


def verify_model(directory):
    directory = Path(directory)
    path = directory / MANIFEST_NAME
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
        raise ValueError("缺少可核实的心电固定模型清单")
    manifest = ECGModelManifest.model_validate_json(path.read_bytes())
    if {entry.name for entry in directory.iterdir()} != set(RELEASE_FILES) | {MANIFEST_NAME}:
        raise ValueError("心电模型目录含未登记文件，不能加载额外代码或权重")
    verify_release_files(directory)
    return manifest
