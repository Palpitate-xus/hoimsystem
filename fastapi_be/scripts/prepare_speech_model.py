"""Explicitly stage a pinned public/private model snapshot; inference itself stays offline."""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.speech_model import MANIFEST_NAME, MODEL_FILES, create_manifest, verify_model


def prepare_model(repository, revision, destination, *, source=None):
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError("目标目录已存在，请选择新目录以保留原模型版本")
    # Validate the revision before any network action.
    import re

    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("须指定模型仓库的40位提交哈希")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".speech-model-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        if source is None:
            from huggingface_hub import snapshot_download

            source = snapshot_download(repo_id=repository, revision=revision, allow_patterns=sorted(MODEL_FILES))
        source = Path(source)
        for name in MODEL_FILES:
            path = source / name
            if path.is_file():
                shutil.copyfile(path, stage / name)
        manifest = create_manifest(stage, repository, revision)
        verify_model(stage)
        stage.rename(destination)
    return {"manifest": str(destination / MANIFEST_NAME), "model_digest": manifest.digest, "repository": manifest.repository, "revision": manifest.revision}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--revision", required=True, help="Immutable 40-character repository commit")
    parser.add_argument("--destination", required=True)
    parser.add_argument("--source-dir", help="Copy existing offline files instead of downloading")
    args = parser.parse_args()
    try:
        result = prepare_model(args.repository, args.revision, args.destination, source=args.source_dir)
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
