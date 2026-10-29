"""The security gate must fail on missing, skipped or incomplete audit output."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


audit = load_script("audit_dependencies")
locks = load_script("lock_dependencies")


def python_report():
    return {"dependencies": [{"name": "typing-extensions", "version": "4.16.0", "vulns": []}, {"name": "torch", "version": "2.14.1", "vulns": []}]}


ENTRIES = ["typing_extensions==4.16.0", "torch==2.14.1"]


def test_python_report_covers_the_exact_requested_versions_and_normalized_names():
    assert audit.python_report_errors(ENTRIES, python_report()) == []


@pytest.mark.parametrize("data", [None, {}, [], {"dependencies": {}}, {"dependencies": None}])
def test_missing_or_unusable_python_reports_fail(data):
    assert audit.python_report_errors(ENTRIES, data) == ["missing_or_invalid_python_report"]


@pytest.mark.parametrize("change", ["empty", "missing", "duplicate", "extra", "wrong_version", "skip", "malformed", "missing_vulns", "invalid_vulns"])
def test_zero_exit_cannot_hide_partial_skipped_duplicate_or_wrong_version_coverage(change):
    data = python_report()
    rows = data["dependencies"]
    if change == "empty":
        data["dependencies"] = []
    elif change == "missing":
        rows.pop()
    elif change == "duplicate":
        rows.append(dict(rows[0]))
    elif change == "extra":
        rows.append({"name": "unrequested", "version": "1", "vulns": []})
    elif change == "wrong_version":
        rows[1]["version"] = "2.0.0"
    elif change == "skip":
        rows[1] = {"name": "torch", "skip_reason": "not found"}
    elif change == "malformed":
        rows[1] = None
    elif change == "missing_vulns":
        rows[1].pop("vulns")
    elif change == "invalid_vulns":
        rows[1]["vulns"] = {}
    assert audit.python_report_errors(ENTRIES, data)


def npm_report():
    return {"auditReportVersion": 2, "vulnerabilities": {}, "metadata": {"vulnerabilities": {"total": 0}}}


def test_complete_clean_npm_report_is_accepted():
    assert audit.npm_report_errors(npm_report()) == []


@pytest.mark.parametrize("data", [None, {}, [], {"error": {"code": "E503"}}, {"auditReportVersion": 2, "vulnerabilities": []}])
def test_failed_registry_or_missing_npm_output_is_not_a_clean_audit(data):
    assert audit.npm_report_errors(data) == ["missing_or_invalid_npm_report"]


@pytest.mark.parametrize("total", [None, True, -1, "0", 0.0])
def test_npm_requires_an_actual_nonnegative_integer_total(total):
    data = npm_report()
    data["metadata"]["vulnerabilities"]["total"] = total
    assert audit.npm_report_errors(data) == ["invalid_npm_totals"]


@pytest.mark.parametrize("reported_by", ["details", "total"])
def test_npm_vulnerabilities_fail_even_if_another_part_or_exit_code_claims_clean(reported_by):
    data = npm_report()
    if reported_by == "details":
        data["vulnerabilities"] = {"synthetic": {"severity": "high"}}
    else:
        data["metadata"]["vulnerabilities"]["total"] = 1
    assert audit.npm_report_errors(data) == ["npm_vulnerabilities_found"]


def test_missing_and_truncated_report_files_return_a_failed_report(tmp_path):
    path = tmp_path / "report.json"
    assert audit.read_report(path) is None
    path.write_text('{"dependencies":')
    assert audit.read_report(path) is None
    path.write_text(json.dumps(python_report()))
    assert audit.python_report_errors(ENTRIES, audit.read_report(path)) == []


def test_cpu_alias_queries_the_public_advisory_version_without_changing_the_lock(tmp_path):
    path = tmp_path / "requirements.lock"
    original = "torch==2.14.1+cpu \\\n    --hash=sha256:synthetic\n"
    path.write_text(original)
    entries, aliases = audit.pins(path)
    assert entries == ["torch==2.14.1"]
    assert aliases == [{"name": "torch", "installed_version": "2.14.1+cpu", "advisory_version": "2.14.1"}]
    assert path.read_text() == original


def test_unpinned_or_unrecognized_records_refuse_a_partial_audit(tmp_path):
    path = tmp_path / "requirements.lock"
    path.write_text("valid==1.0\nunknown>=1.0\n")
    with pytest.raises(ValueError, match="refusing a partial audit"):
        audit.pins(path)


@pytest.mark.parametrize("coverage", ["missing", "extra"])
def test_manifest_cannot_omit_or_invent_an_environment_with_valid_input_hashes(tmp_path, monkeypatch, coverage):
    (tmp_path / "requirements.txt").write_text("synthetic==1.0\n")
    (tmp_path / "requirements.lock").write_text("synthetic==1.0\n")
    (tmp_path / "requirements-model-constraints.txt").write_text("# no model\n")
    manifest = {"inputs": {name: locks.sha(tmp_path / name) for name in ("requirements.txt", "requirements-model-constraints.txt")}, "locks": {}}
    if coverage == "extra":
        manifest["locks"] = {"requirements.lock": locks.sha(tmp_path / "requirements.lock"), "nonexistent.lock": "0" * 64}
    path = tmp_path / "dependencies-lock-manifest.json"
    path.write_text(json.dumps(manifest))
    monkeypatch.setattr(locks, "ROOT", tmp_path)
    monkeypatch.setattr(locks, "MANIFEST", path)
    with pytest.raises(SystemExit, match="cover every requirement environment"):
        locks.check()


@pytest.mark.parametrize("outcome", ["clean", "missing_python_report", "partial_python_report", "python_vulnerability", "missing_npm_report", "npm_vulnerability", "tool_failure"])
def test_command_exit_and_saved_summary_follow_real_report_coverage_even_when_scanner_exits_zero(tmp_path, monkeypatch, outcome):
    directory = tmp_path / "backend"
    directory.mkdir()
    (directory / "requirements.lock").write_text("typing_extensions==4.16.0\ntorch==2.14.1\n")
    output = tmp_path / "evidence"
    monkeypatch.setattr(audit, "ROOT", directory)
    monkeypatch.setattr(audit.sys, "argv", ["audit_dependencies.py", "--output", str(output)])
    monkeypatch.setattr(audit.shutil, "which", lambda name: "/synthetic/" + name)

    def run(command, **kwargs):
        if "--progress-spinner" in command:
            path = Path(command[command.index("--output") + 1])
            data = python_report()
            if outcome == "partial_python_report":
                data["dependencies"].pop()
            elif outcome == "python_vulnerability":
                data["dependencies"][0]["vulns"] = [{"id": "SYNTHETIC-ADVISORY"}]
            if outcome != "missing_python_report":
                path.write_text(json.dumps(data))
            return SimpleNamespace(returncode=2 if outcome == "tool_failure" else 0)
        if command[0] == "npm":
            data = npm_report()
            if outcome == "npm_vulnerability":
                data["metadata"]["vulnerabilities"]["total"] = 1
            if outcome != "missing_npm_report":
                kwargs["stdout"].write(json.dumps(data))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(audit.subprocess, "run", run)
    with pytest.raises(SystemExit) as caught:
        audit.main()
    expected = 0 if outcome == "clean" else 1
    assert caught.value.code == expected
    saved = json.loads((output / "summary.json").read_text())
    assert saved["status"] == ("passed" if outcome == "clean" else "failed")
    assert saved["python_locks"] == 1
