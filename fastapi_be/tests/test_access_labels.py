"""Permission display labels describe business operations in Chinese."""

import json
import re
from pathlib import Path

import pytest

from app.access_control import permission_catalog
from app.access_labels import MODULE_LABELS, permission_label


@pytest.mark.parametrize("path", ["/api/access/audit", "/api/ai/admin/audit", "/api/research/export/audit"])
def test_get_audit_is_an_audit_log_read(path):
    assert permission_label("permission_management", "GET", path, "get_audit") == "查看审计记录"


def test_post_audit_retains_approval_meaning():
    assert permission_label("medical_record_archive", "POST", "/api/medicalRecord/archive/audit", "audit_record").startswith("审核")


def test_get_review_does_not_look_like_a_review_mutation():
    assert permission_label("emr", "GET", "/api/clinicalDiagnosis/review", "get_diagnosis_review") == "查看复核记录：临床诊断"


def test_protected_surgery_capture_is_labeled_as_creation():
    assert permission_label("ai_surgery_sources", "POST", "/api/ai/surgery-protected-capsules", "protected_capsule") == "新增受保护手术资料"


@pytest.mark.parametrize(
    "module,method,path,function,expected",
    [
        ("ai_bed_series", "POST", "/api/ai/bed-series/{series_id}/revoke", "revoke_series", "撤销：床位需求序列"),
        ("ai_admin", "POST", "/api/ai/admin/providers", "create_provider", "新增：模型服务"),
        ("ops_extension", "POST", "/api/cssd/transition", "cssd_transition", "变更状态：消毒器械包"),
        ("admission", "GET", "/api/admission/getAvailableBeds", "get_available_beds", "查看可用床位"),
    ],
)
def test_operations_have_business_objects(module, method, path, function, expected):
    assert permission_label(module, method, path, function) == expected


def test_all_protected_modules_and_permissions_have_chinese_labels_without_code_changes():
    matrix = json.loads((Path(__file__).resolve().parents[1] / "rbac_matrix.json").read_text())
    rows = [row for row in matrix if row["auth"] != "PUBLIC"]
    catalog = permission_catalog()[0]
    for row in rows:
        module = row["module"].removesuffix(".py")
        code = row["method"] + " " + row["path"]
        item = catalog[code]
        assert module in MODULE_LABELS
        assert item["module_label"] != module
        assert re.search(r"[\u4e00-\u9fff]", item["module_label"])
        assert re.search(r"[\u4e00-\u9fff]", item["label"])
        assert item["label"] != row["function"].replace("_", " ")
        assert (item["method"], item["path"]) == (row["method"], row["path"])
