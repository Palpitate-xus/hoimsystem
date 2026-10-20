"""Immutable public chest X-ray research weights, without importing a ML runtime.

This manifest binds a reviewed conversion, architecture and tensor schema. It
does not establish a DICOM preprocessing profile or clinical applicability.
"""

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REPOSITORY = "torchxrayvision/densenet121-res224-all"
REVISION = "588eadcc6a744da71f8dce768bc974ec629443f5"
CODE_REVISION = "17726dd8f5e756eec3e5ae958281a289b05b1dae"
MANIFEST_NAME = "hoim-imaging-model.json"
LABELS = [
    "Atelectasis",
    "Consolidation",
    "Infiltration",
    "Pneumothorax",
    "Edema",
    "Emphysema",
    "Fibrosis",
    "Effusion",
    "Pneumonia",
    "Pleural_Thickening",
    "Cardiomegaly",
    "Nodule",
    "Mass",
    "Hernia",
    "Lung Lesion",
    "Fracture",
    "Lung Opacity",
    "Enlarged Cardiomediastinum",
]
TENSOR_COUNT = 727
STATE_SCHEMA_SHA256 = "51875470a4a913653c5eff6286ccc893907241d50a7e19857acf49bfef90b942"

# Only these public immutable artifacts may enter the isolated converter. The
# legacy checkpoint and author source code never enter a runtime model bundle.
REFERENCE_FILES = {
    "model.pt": (28382008, "56524913dd16a906422e8d8b66a7a5c46be1d82eb7ac012d8103776f1aa68899"),
    "config.json": (1158, "4b78be461c44f98af46695ce5cdbe57313e97f2e6255ac7b888e0670f368a1dd"),
    "README.md": (4006, "90b88ae29df845efa2ae97cb834266b3ef7d2fa720f42860ee318d6896323c0a"),
    "models.py": (25374, "3d359ee39db33ae4f9633d7cccc0756f63ad8e38b6d018776c5c2c18a0553af8"),
    "LICENSE": (243, "75bdbb99fbfb7202e33f19ff8f1f2f713d309143612459274005a43aaa7f6061"),
}
REFERENCE_URLS = {
    name: (
        f"https://raw.githubusercontent.com/mlmed/torchxrayvision/{CODE_REVISION}/{name if name == 'LICENSE' else 'torchxrayvision/' + name}"
        if name in {"models.py", "LICENSE"}
        else f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{name}"
    )
    for name in REFERENCE_FILES
}
RELEASE_FILES = {
    "model.safetensors": (28283736, "6b811edb354d83991e36a4836b914bf41faf8fb3203573c0a61820b97937c529"),
    "config.json": REFERENCE_FILES["config.json"],
    "README.md": REFERENCE_FILES["README.md"],
    "upstream-LICENSE.txt": REFERENCE_FILES["LICENSE"],
    "LICENSE": (11357, "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"),
    "NOTICE": (3014, "d23125888206442a1f8e6f3033f7ab5c00a3ac4241e5c27e56db9d3f1ef2b394"),
}


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_bounded_file(directory, name, limit, *, expected_size=None):
    root_fd = None
    try:
        root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
        with os.fdopen(file_fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit or (expected_size is not None and info.st_size != expected_size):
                raise ValueError("影像模型文件大小或类型与固定发布不符")
            raw = stream.read(limit + 1)
    except OSError as exc:
        raise ValueError("无法读取固定影像模型的实际常规文件") from exc
    finally:
        if root_fd is not None:
            os.close(root_fd)
    if len(raw) > limit:
        raise ValueError("影像模型文件超过固定发布大小")
    return raw


def read_verified_file(directory, name, *, files=None):
    """Verify the same bounded regular-file bytes returned to the consumer."""
    files = RELEASE_FILES if files is None else files
    if name not in files or Path(name).name != name:
        raise ValueError("影像模型文件未登记")
    expected_size, expected_digest = files[name]
    raw = _read_bounded_file(directory, name, expected_size, expected_size=expected_size)
    if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_digest:
        raise ValueError("影像模型实际字节与已审查固定发布不一致")
    return raw


class ModelFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    size: int = Field(gt=0, strict=True)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class ImagingModelManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format_version: Literal["1"] = "1"
    repository: Literal["torchxrayvision/densenet121-res224-all"] = REPOSITORY
    revision: Literal["588eadcc6a744da71f8dce768bc974ec629443f5"] = REVISION
    architecture_revision: Literal["17726dd8f5e756eec3e5ae958281a289b05b1dae"] = CODE_REVISION
    tensor_count: Literal[727] = TENSOR_COUNT
    state_schema_sha256: Literal["51875470a4a913653c5eff6286ccc893907241d50a7e19857acf49bfef90b942"] = STATE_SCHEMA_SHA256
    files: dict[str, ModelFile]

    @model_validator(mode="after")
    def reviewed_checkpoint_only(self):
        if set(self.files) != set(RELEASE_FILES) or any((item.size, item.sha256) != RELEASE_FILES[name] for name, item in self.files.items()):
            raise ValueError("影像模型清单与已审查固定发布不符")
        return self

    @property
    def digest(self):
        return hashlib.sha256(canonical_json(self.model_dump()).encode()).hexdigest()


def verify_release_files(directory):
    for name in RELEASE_FILES:
        read_verified_file(directory, name)
    return {name: {"size": size, "sha256": digest} for name, (size, digest) in sorted(RELEASE_FILES.items())}


def create_manifest(directory):
    directory = Path(directory)
    manifest = ImagingModelManifest(files=verify_release_files(directory))
    with (directory / MANIFEST_NAME).open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(manifest.model_dump()) + "\n")
    return manifest


def verify_model(directory):
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("影像模型目录须为实际固定版本目录")
    if {entry.name for entry in directory.iterdir()} != set(RELEASE_FILES) | {MANIFEST_NAME}:
        raise ValueError("影像模型目录含缺失或未登记文件，不加载额外代码或权重")
    path = directory / MANIFEST_NAME
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
        raise ValueError("缺少可核实的影像固定模型清单")
    manifest = ImagingModelManifest.model_validate_json(_read_bounded_file(directory, MANIFEST_NAME, 16384))
    verify_release_files(directory)
    return manifest
