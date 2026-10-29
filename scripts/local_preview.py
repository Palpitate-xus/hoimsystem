#!/usr/bin/env python3
"""Build and manage the isolated local preview at http://localhost:51891."""

import argparse
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".local-preview"
ENV_FILE = STATE / "preview.env"


def prepare():
    STATE.mkdir(mode=0o700, exist_ok=True)
    if ENV_FILE.exists():
        if not (STATE / "simulator.key").is_file():
            raise SystemExit("Missing .local-preview/simulator.key; restore it before restarting the preview.")
        return
    key = secrets.token_urlsafe(32)
    values = {
        "PREVIEW_DB_PASSWORD": secrets.token_urlsafe(32),
        "SECRET_KEY": secrets.token_urlsafe(48),
        "AI_CREDENTIAL_KEY": secrets.token_urlsafe(48),
        "AI_PROVIDER_PREVIEW_API_KEY": key,
    }
    for path, content in [(STATE / "simulator.key", key + "\n"), (ENV_FILE, "".join(f"{k}={v}\n" for k, v in values.items()))]:
        with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
            stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status", "logs"])
    parser.add_argument("--skip-frontend-build", action="store_true", help="Use an already verified vue3-new-ui/dist build")
    args = parser.parse_args()
    if args.action == "start":
        prepare()
        if not args.skip_frontend_build:
            subprocess.run(["npm", "run", "build"], cwd=ROOT / "vue3-new-ui", check=True)
        if not (ROOT / "vue3-new-ui/dist/index.html").is_file():
            raise SystemExit("Missing frontend build. Install dependencies with npm ci --legacy-peer-deps, then run start again.")
    elif not ENV_FILE.is_file():
        raise SystemExit("The local preview has not been initialized. Run: python scripts/local_preview.py start")
    command = ["docker", "compose", "--env-file", str(ENV_FILE), "-f", str(ROOT / "deploy/preview/compose.yml")]
    if args.action == "start":
        # Build the shared API image once; concurrent exports to one image tag
        # race on containerd-backed Docker installations.
        subprocess.run(command + ["build", "backend", "frontend"], cwd=ROOT, check=True)
    actions = {
        "start": ["up", "--no-build", "-d", "--wait", "--wait-timeout", "300"],
        "stop": ["down"],
        "status": ["ps", "--all"],
        "logs": ["logs", "--tail", "100"],
    }
    subprocess.run(command + actions[args.action], cwd=ROOT, check=True)
    if args.action == "start":
        print("\nPreview: http://localhost:51891   API docs: http://localhost:51800/docs")
        print("Default bind: 0.0.0.0. For LAN access, add the exact frontend URL to PREVIEW_ALLOWED_ORIGINS in .local-preview/preview.env.")
        print("Super administrator: super01 / 123456   Doctor: doctor1 / doctor123")
        print("AI uses synthetic simulator replies. Clinical features stay unvalidated; use super-admin preview.")
        print("Stop without deleting demo data: python scripts/local_preview.py stop")


if __name__ == "__main__":
    main()
