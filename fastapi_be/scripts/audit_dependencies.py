"""Audit every hashed Python environment and the frontend without installing application packages."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pins(path):
    entries, aliases = [], []
    for line in path.read_text().splitlines():
        value = line.strip()
        if not value or value.startswith(("#", "--hash=")):
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)", value)
        if not match:
            raise ValueError(f"Unsupported lock record in {path.name}; refusing a partial audit")
        name, version = match.groups()
        # Official CPU wheels use a local version suffix. Query advisories for
        # the corresponding public PyTorch release; keep the installed pin intact.
        if name.lower() == "torch" and version.endswith("+cpu"):
            aliases.append({"name": name, "installed_version": version, "advisory_version": version[:-4]})
            version = version[:-4]
        entries.append(f"{name}=={version}")
    if not entries:
        raise ValueError(f"No package pins in {path.name}")
    return entries, aliases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory")
    args = parser.parse_args()
    subprocess.run([sys.executable, str(ROOT / "scripts/lock_dependencies.py")], check=True)
    args.output.mkdir(parents=True, exist_ok=False)
    auditor = ["pip-audit"] if shutil.which("pip-audit") else ["uvx", "--from", "pip-audit==2.10.0", "pip-audit"]
    if not shutil.which(auditor[0]):
        raise SystemExit("Install pip-audit or uv before running the audit")
    groups = defaultdict(list)
    for path in sorted(ROOT.glob("requirements*.lock")):
        groups[hashlib.sha256(path.read_bytes()).hexdigest()].append(path)
    results = []
    for digest, group in groups.items():
        path = group[0]
        entries, aliases = pins(path)
        request = args.output / (path.name + ".txt")
        request.write_text("\n".join(entries) + "\n")
        report = args.output / (path.name + ".json")
        with (args.output / (path.name + ".log")).open("w") as log:
            completed = subprocess.run([*auditor, "-r", str(request), "--no-deps", "--disable-pip", "--progress-spinner", "off", "--format", "json", "--output", str(report)], stdout=log, stderr=subprocess.STDOUT)
        data = json.loads(report.read_text()) if report.is_file() else {}
        skips = [item for item in data.get("dependencies", []) if item.get("skip_reason")]
        results.append({"locks": [item.name for item in group], "lock_sha256": digest, "packages": len(entries),
                        "advisory_aliases": aliases, "exit_code": completed.returncode, "skipped": skips,
                        "vulnerabilities": sum(len(item.get("vulns", [])) for item in data.get("dependencies", []))})
    with (args.output / "npm-audit.json").open("w") as stream:
        npm = subprocess.run(["npm", "audit", "--json"], cwd=ROOT.parent / "vue3-new-ui", stdout=stream, stderr=subprocess.PIPE, text=True)
    failed = npm.returncode != 0 or any(row["exit_code"] or row["skipped"] or row["vulnerabilities"] for row in results)
    summary = {"status": "failed" if failed else "passed", "python_locks": sum(len(row["locks"]) for row in results), "python": results, "npm_exit_code": npm.returncode}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"{summary['status']}: {summary['python_locks']} Python locks and npm; evidence: {args.output}")
    raise SystemExit(int(failed))


if __name__ == "__main__":
    main()
