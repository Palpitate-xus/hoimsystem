"""Generate hashed Python 3.12 Linux locks, or check their committed provenance."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "dependencies-lock-manifest.json"
MODEL_INPUTS = {"requirements-ecg.txt", "requirements-imaging.txt", "requirements-imaging-service.txt", "requirements-speech.txt", "requirements-ecg-verification.txt"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs():
    return sorted(path for path in ROOT.glob("requirements*.txt") if path.name != "requirements-model-constraints.txt")


def compile_lock(path, *, upgrade=False):
    destination = path.with_suffix(".lock")
    command = ["uv", "pip", "compile", path.name, "--python-version", "3.12", "--python-platform", "x86_64-unknown-linux-gnu", "--generate-hashes", "--no-annotate", "--no-header", "--output-file", destination.name]
    command += ["--default-index", "https://pypi.org/simple"]
    if upgrade:
        command.append("--upgrade")
    if path.name not in {"requirements.txt", "requirements-build.txt"}:
        command += ["--constraints", "requirements.lock"]
    if path.name in MODEL_INPUTS:
        command += ["--constraints", "requirements-model-constraints.txt"]
        # Model inputs use only the official PyPI and PyTorch CPU indexes.
        # PyTorch also mirrors older common packages; allow the PyPI version
        # constrained by the main application instead of stopping at that mirror.
        command += ["--index-strategy", "unsafe-best-match"]
    environment = os.environ.copy()
    for name in ("UV_INDEX", "UV_INDEX_URL", "UV_DEFAULT_INDEX", "UV_EXTRA_INDEX_URL", "UV_INDEX_STRATEGY", "PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL"):
        environment.pop(name, None)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, env=environment)
    if result.returncode:
        raise RuntimeError(f"Lock generation failed for {path.name}:\n{result.stderr}")
    print(f"Locked {path.name}", flush=True)


def update(*, upgrade=False):
    if not shutil.which("uv"):
        raise SystemExit("Install uv before regenerating the lock files.")
    compile_lock(ROOT / "requirements-build.txt", upgrade=upgrade)
    compile_lock(ROOT / "requirements.txt", upgrade=upgrade)
    groups = {}
    for path in inputs():
        if path.name in {"requirements-build.txt", "requirements.txt"}:
            continue
        signature = "\n".join(line for line in path.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#"))
        groups.setdefault(signature, []).append(path)
    # Identical rule-service inputs share one resolution; each Dockerfile still
    # consumes the lock with its own service name.
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(partial(compile_lock, upgrade=upgrade), [group[0] for group in groups.values()]))
    for group in groups.values():
        for path in group[1:]:
            shutil.copyfile(group[0].with_suffix(".lock"), path.with_suffix(".lock"))
    tracked = {path.name: sha(path) for path in [*inputs(), ROOT / "requirements-model-constraints.txt"]}
    locks = {path.with_suffix(".lock").name: sha(path.with_suffix(".lock")) for path in inputs()}
    MANIFEST.write_text(json.dumps({"python": "3.12", "platform": "linux_x86_64", "inputs": tracked, "locks": locks}, indent=2, sort_keys=True) + "\n")


def check():
    if not MANIFEST.is_file():
        raise SystemExit("Missing dependency lock manifest; run python scripts/lock_dependencies.py --update")
    manifest = json.loads(MANIFEST.read_text())
    actual_inputs = {path.name: sha(path) for path in [*inputs(), ROOT / "requirements-model-constraints.txt"]}
    if actual_inputs != manifest["inputs"]:
        raise SystemExit("Requirement inputs changed; regenerate and audit the dependency locks.")
    if set(manifest["locks"]) != {path.with_suffix(".lock").name for path in inputs()}:
        raise SystemExit("Dependency lock manifest must cover every requirement environment exactly once.")
    changed = [name for name, digest in manifest["locks"].items() if not (ROOT / name).is_file() or sha(ROOT / name) != digest]
    if changed:
        raise SystemExit("Dependency lock content changed: " + ", ".join(changed))
    print(f"Checked {len(manifest['locks'])} hashed dependency locks")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update", action="store_true", help="Resolve versions and regenerate hashes")
    parser.add_argument("--upgrade", action="store_true", help="With --update, select the latest versions allowed by the requirement constraints")
    args = parser.parse_args()
    if args.upgrade and not args.update:
        parser.error("--upgrade requires --update")
    if args.update:
        update(upgrade=args.upgrade)
    check()


if __name__ == "__main__":
    main()
