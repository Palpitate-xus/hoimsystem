"""Stage the fixed public XRV research model; never deserialize pickle on the host.

An explicit destination is required. Offline prepared bundles can be copied
without Docker or network. Preparing the original public checkpoint requires
an explicit local CPU image for the network-disabled isolated converter.
"""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.imaging_model import (
    MANIFEST_NAME,
    REFERENCE_FILES,
    REFERENCE_URLS,
    RELEASE_FILES,
    REPOSITORY,
    REVISION,
    create_manifest,
    read_verified_file,
    verify_model,
)


def download_reference(directory):
    for name, (limit, expected_digest) in REFERENCE_FILES.items():
        with urllib.request.urlopen(REFERENCE_URLS[name], timeout=30) as response, (directory / name).open("xb") as output:
            size, digest = 0, hashlib.sha256()
            while block := response.read(65536):
                size += len(block)
                if size > limit:
                    raise ValueError("影像公开参考文件下载超过固定发布大小")
                digest.update(block)
                output.write(block)
        if size != limit or digest.hexdigest() != expected_digest:
            raise ValueError("影像公开参考文件与固定发布字节不符")


def run_isolated_conversion(reference, output, image):
    if not image or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:./@_-]{0,250}", image):
        raise ValueError("原始权重转换须明确指定已安装的本地 CPU Docker 镜像")
    inspected = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], capture_output=True, text=True, check=True, timeout=30)
    image_id = inspected.stdout.strip()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_id):
        raise ValueError("无法固定本地转换镜像的实际镜像摘要")
    name = "hoim-public-imaging-convert-" + uuid4().hex
    converter = Path(__file__).with_name("convert_imaging_weights.py")
    shutil.copyfile(converter, reference / converter.name)
    # Only public artifacts are mounted. A fixed unprivileged container UID
    # may write this temporary public-output directory; it is never the final
    # user destination and contains no credentials, model service or patient data.
    output.mkdir(mode=0o777)
    output.chmod(0o777)
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--pull",
        "never",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "10001:10001",
        "--memory",
        "2g",
        "--cpus",
        "4",
        "--pids-limit",
        "128",
        "--ipc",
        "none",
        "--tmpfs",
        "/tmp:size=256m",
        "--workdir",
        "/tmp",
        "--entrypoint",
        "python",
        "--mount",
        f"type=bind,source={reference},target=/reference,readonly",
        "--mount",
        f"type=bind,source={output},target=/output",
        image_id,
        "/reference/convert_imaging_weights.py",
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
    finally:
        # Clean up only this uniquely named converter, including a timeout
        # where Docker's client exited before its isolated container did.
        subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True, timeout=30)
    return image_id


def prepare_model(destination, *, source=None, reference=None, image=None, repository=REPOSITORY, revision=REVISION):
    if repository != REPOSITORY or revision != REVISION:
        raise ValueError("仅接受已审查的固定胸片模型仓库与40位发布提交")
    if source is not None and (reference is not None or image is not None):
        raise ValueError("现成固定模型包与原始参考文件转换须选择一种方式")
    if source is None and not image:
        raise ValueError("原始权重转换须明确指定已安装的本地 CPU Docker 镜像")
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("目标目录已存在，请选择新目录保留原模型版本")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".imaging-model-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        if source is not None:
            verify_model(source)
            for name in RELEASE_FILES:
                (stage / name).write_bytes(read_verified_file(source, name))
        else:
            # Legacy checkpoints and source code stay in /tmp, never in the
            # repository or published runtime model directory.
            with tempfile.TemporaryDirectory(prefix="hoim-public-imaging-") as raw_temporary:
                public = Path(raw_temporary)
                raw_reference, converted = public / "reference", public / "converted"
                raw_reference.mkdir(mode=0o755)
                if reference is None:
                    download_reference(raw_reference)
                else:
                    for name in REFERENCE_FILES:
                        (raw_reference / name).write_bytes(read_verified_file(reference, name, files=REFERENCE_FILES))
                run_isolated_conversion(raw_reference, converted, image)
                (stage / "model.safetensors").write_bytes(read_verified_file(converted, "model.safetensors"))
                for name in ("config.json", "README.md"):
                    (stage / name).write_bytes(read_verified_file(raw_reference, name, files=REFERENCE_FILES))
                (stage / "upstream-LICENSE.txt").write_bytes(read_verified_file(raw_reference, "LICENSE", files=REFERENCE_FILES))
                legal = Path(__file__).resolve().parents[1] / "third_party" / "torchxrayvision"
                for name in ("LICENSE", "NOTICE"):
                    (stage / name).write_bytes(read_verified_file(legal, name))
        manifest = create_manifest(stage)
        verify_model(stage)
        stage.rename(destination)
    return {"manifest": str(destination / MANIFEST_NAME), "model_digest": manifest.digest, "repository": manifest.repository, "revision": manifest.revision}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--source-dir", help="Copy an existing verified safetensors model bundle without Docker or network")
    parser.add_argument("--reference-dir", help="Copy the exact original public checkpoint/code/config from an offline directory")
    parser.add_argument("--conversion-image", help="Explicit already-installed CPU Docker image; never pulled automatically")
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--revision", default=REVISION)
    args = parser.parse_args()
    try:
        result = prepare_model(args.destination, source=args.source_dir, reference=args.reference_dir, image=args.conversion_image, repository=args.repository, revision=args.revision)
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
