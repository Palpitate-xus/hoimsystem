"""Stage only the reviewed ECG release; its repository Python is never downloaded or executed."""

import argparse
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.ecg_model import MANIFEST_NAME, RELEASE_FILES, REPOSITORY, REVISION, create_manifest, verify_model


def prepare_model(destination, *, source=None, repository=REPOSITORY, revision=REVISION):
    if repository != REPOSITORY or revision != REVISION:
        raise ValueError("仅接受已审查的固定心电仓库与40位发布提交")
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise ValueError("目标目录已存在，请选择新目录保留原模型版本")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ecg-model-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        for name, (limit, _) in RELEASE_FILES.items():
            if source is not None:
                origin = Path(source) / name
                if origin.is_symlink() or not origin.is_file() or origin.stat().st_size != limit:
                    raise ValueError("来源缺少已审查的心电发布文件")
                shutil.copyfile(origin, stage / name)
            else:
                url = f"https://huggingface.co/{repository}/resolve/{revision}/{name}"
                with urllib.request.urlopen(url, timeout=30) as response, (stage / name).open("xb") as output:
                    size = 0
                    while block := response.read(65536):
                        size += len(block)
                        if size > limit:
                            raise ValueError("心电模型下载超过已知发布大小")
                        output.write(block)
        manifest = create_manifest(stage)
        verify_model(stage)
        stage.rename(destination)
    return {"manifest": str(destination / MANIFEST_NAME), "model_digest": manifest.digest, "repository": manifest.repository, "revision": manifest.revision}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--source-dir", help="Use an existing offline copy of this exact release")
    parser.add_argument("--repository", default=REPOSITORY)
    parser.add_argument("--revision", default=REVISION)
    args = parser.parse_args()
    try:
        result = prepare_model(args.destination, source=args.source_dir, repository=args.repository, revision=args.revision)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
