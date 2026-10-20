"""Synthetic laboratory members preserve versioned admission-window boundaries."""

import datetime
import json
import uuid

import pytest
from fastapi import HTTPException

from app.ai import observation_windows as windows
from app.ai.models import AIObservationWindow
from tests.test_ai_observation_windows import observation_case as observation_case
from tests.test_ai_observation_windows import values


def legacy_window(db, case):
    fields = {**values(case), "window_id": str(uuid.uuid4()), "created_by": case["doctor"].user_id, "created_at": case["now"]}
    frozen = windows.build_snapshot(db, **fields, schema_version="inpatient_window_v1")
    row = AIObservationWindow(
        **fields,
        schema_version="inpatient_window_v1",
        snapshot_json=windows.canonical_json(frozen),
        content_hash=frozen["content_hash"],
        status="active",
        revision=1,
        revoke_reason="",
    )
    db.add(row)
    db.commit()
    return row


def test_saved_v1_preserves_its_original_shape_text_hash_and_microseconds(db_session, observation_case):
    case = observation_case
    row = legacy_window(db_session, case)
    before = (row.snapshot_json, row.content_hash, row.schema_version)
    snapshot = windows.snapshot_current(db_session, case["doctor"], row)
    assert snapshot == json.loads(before[0])
    assert snapshot["schema_version"] == "inpatient_window_v1"
    assert set(snapshot) == {
        "schema_version",
        "window_id",
        "patient_id",
        "admission_id",
        "created_by",
        "created_at",
        "start_at",
        "end_at",
        "as_of",
        "snapshot_basis",
        "representation",
        "point_interval_semantics",
        "points",
        "urine_intervals",
        "quality",
        "lab_input_status",
        "model_input_validation",
        "limitations",
        "content_hash",
        "source_id",
    }
    assert snapshot["limitations"] == [
        "所选住院和UTC时段内符合截止时点的离散记录，不证明连续监护或采样完整性",
        "未前填、补零、从脉搏替代心率、从设备推测FiO2或自动计算临床评分",
        "当前快照回溯，不是历史数据库as-of重放；已撤销原值不得作为有效测量",
        "旧患者级体征、检验、护理正文和当前诊断医嘱未作为本窗口特征加载",
    ]
    assert snapshot["lab_input_status"] == "not_available_requires_explicit_admission_binding_and_reviewed_mapping"
    assert "laboratory" not in snapshot["quality"] and "lab_observations" not in snapshot
    assert snapshot["start_at"] == windows.iso(case["start"])
    assert (row.snapshot_json, row.content_hash, row.schema_version) == before


def test_saved_v1_still_rejects_changed_original_members(db_session, observation_case):
    case = observation_case
    row = legacy_window(db_session, case)
    case["point"].recorded_at += datetime.timedelta(microseconds=1)
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        windows.snapshot_current(db_session, case["doctor"], row)
    assert caught.value.status_code == 409


def test_saved_unknown_version_is_not_silently_rebuilt_as_latest(db_session, observation_case):
    case = observation_case
    row = legacy_window(db_session, case)
    row.schema_version = "inpatient_window_v999"
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        windows.snapshot_current(db_session, case["doctor"], row)
    assert caught.value.status_code == 409


def test_building_an_unknown_version_is_explicitly_rejected(db_session, observation_case):
    case = observation_case
    with pytest.raises(HTTPException) as caught:
        windows.build_snapshot(db_session, **values(case), window_id=str(uuid.uuid4()), created_by=case["doctor"].user_id, created_at=case["now"], schema_version="inpatient_window_v999")
    assert caught.value.status_code == 422
