#!/usr/bin/env python3
"""Check release versions, locked builds and generated public contracts without changing files."""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    version = (ROOT / "VERSION").read_text().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise SystemExit("VERSION must contain a semantic release version")
    frontend = ROOT / "vue3-new-ui"
    package = json.loads((frontend / "package.json").read_text())
    lock = json.loads((frontend / "package-lock.json").read_text())
    tree = ast.parse((ROOT / "fastapi_be/app/routers/version.py").read_text())
    backend = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "APP_VERSION" for target in node.targets))
    versions = [backend, package["version"], lock["version"], lock["packages"][""]["version"]]
    if any(value != version for value in versions) or lock["name"] != package["name"]:
        raise SystemExit("Backend, frontend, npm lock and VERSION do not agree")
    if not re.search(r"^## \[" + re.escape(version) + r"\] - \d{4}-\d{2}-\d{2}$", (ROOT / "CHANGELOG.md").read_text(), re.MULTILINE):
        raise SystemExit("Missing dated changelog for the current release")
    source = json.loads((ROOT / "fastapi_be/ffmpeg-source.json").read_text())
    for name in ("Dockerfile", "Dockerfile.speech"):
        dockerfile = (ROOT / "fastapi_be" / name).read_text()
        if f"ADD --checksum=sha256:{source['sha256']} {source['url']}" not in dockerfile:
            raise SystemExit(f"{name}: audio source differs from the verified manifest")
    checks = [
        ([sys.executable, "fastapi_be/scripts/lock_dependencies.py"], ROOT),
        ([sys.executable, "fastapi_be/scripts/generate_rbac_matrix.py", "--check"], ROOT),
        ([sys.executable, "fastapi_be/scripts/export_ai_catalog.py", "--check"], ROOT),
        (["node", "scripts/generate-element-plus-style-entry.cjs", "--check"], frontend),
        (["node", "scripts/generate-public-interface-text-pool.cjs", "--check"], frontend),
        (["npm", "run", "check:bundle"], frontend),
    ]
    for command, directory in checks:
        subprocess.run(command, cwd=directory, check=True)
    environment = os.environ.copy()
    environment.update(POSTGRES_PASSWORD="release-config-check-only", SECRET_KEY="release-config-check-only-at-least-32-characters", ALLOWED_ORIGINS="http://localhost:51891")
    subprocess.run(["docker", "compose", "-f", "docker-compose.yml", "config", "--quiet"], cwd=ROOT, env=environment, check=True)
    print(f"Release {version}: versions, dependency hashes, public contracts, bundle and Compose checked")


if __name__ == "__main__":
    main()
