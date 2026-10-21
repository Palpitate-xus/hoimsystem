"""Actual complete case originals, minimal projection and independent governance."""

import copy
import datetime
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import event, text

from app.ai import coding_evidence_sources as sources
from app.ai.coding_evidence_input import CaptureRequest, CaseCreate, RulePackageCreate
from app.ai.coding_evidence_models import AICodingCaseSnapshot
from app.ai.coding_evidence_projection import project_snapshot, text_hash
from app.models import DrgGrouping, HomeIcdBinding
from tests.test_coding_evidence_legacy_writes import coding_case  # noqa:F401

NOW = datetime.datetime(2026, 10, 21, 12, 30, 0, 123456)
NOTE = "本条独立合成编码证据依据逐项保留原文和未知不代表医学或官方分组验证"


@pytest.fixture
def case(db_session, coding_case, monkeypatch):  # noqa:F811
    c = coding_case
    h = c["home"]
    h.status = 1
    h.discharge_diagnosis = c["patient"].name + " " + c["patient"].identity + " 合成出院原诊断"
    h.other_diagnosis = None
    db_session.add(
        HomeIcdBinding(
            home_id=h.home_id, kind="diagnosis", icd_code=c["diagnosis"].code, icd_name=c["diagnosis"].name, is_primary=1, coder_id=c["admin_user"].user_id, code_time=NOW, remark="私有编码员备注"
        )
    )
    db_session.add(
        DrgGrouping(
            home_id=h.home_id,
            patient_id=h.patient_id,
            rule_id=c["rule"].rule_id,
            group_code=c["rule"].group_code,
            payment_method="DRG",
            diagnosis=h.discharge_diagnosis,
            expected_amount=999,
            actual_amount=100,
            profit=899,
            create_time=NOW,
        )
    )
    db_session.commit()
    monkeypatch.setattr(sources, "utcnow", lambda: NOW)
    return c


def request(c):
    return {
        "patient_id": c["patient"].patient_id,
        "home_id": c["home"].home_id,
        "admission_id": c["admission"].admission_id,
        "rule_package_id": None,
        "expected_rule_package_content_hash": None,
        "expected_rule_package_governance_hash": None,
    }


def published(db, c):
    req = request(c)
    capture = sources.capture_case(db, c["doctor_user"], req)
    row = sources.create_case(db, c["doctor_user"], {"request": req, "expected_collection_digest": capture["collection_digest"], "note": NOTE})
    db.commit()
    sources.review(db, c["super_admin_user"], "case", row.case_snapshot_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "basis_note": NOTE})
    db.commit()
    return row


def test_actual_complete_snapshot_publish_minimal_utf8_projection_and_frozen_revoke(db_session, case):
    db, c = db_session, case
    row = published(db, c)
    view = sources.case_current(db, c["doctor_user"], row.case_snapshot_id, execution=True)
    assert view["eligible"] and sources.verify_original(sources.original(row))
    p = view["public_source"]
    assert p == project_snapshot(view["snapshot"], sources.published_metadata(view))
    assert p["source_id"] == view["source_id"] and p["code_bindings"][0]["code_token"]
    assert len(p["documents"]) == 2 and p["missing_document_fields"] == ["other_diagnosis", "operation_summary", "complication"]
    assert all(d["text_hash"] == text_hash(d["text"]) for d in p["documents"])
    output = json.dumps(p, ensure_ascii=False)
    for secret in (c["patient"].name, c["patient"].identity, c["home"].home_id, c["admission"].admission_id, "expected_amount", "actual_amount", "profit", "coder_id", "私有编码员备注"):
        assert secret not in output
    assert p["policy"]["historical_group_rule_basis"] == "unknown"
    assert view["created_at"].endswith(".123456Z")
    assert view["snapshot"]["collection"]["home"]["update_time"].endswith("000000") and not view["snapshot"]["collection"]["home"]["update_time"].endswith("Z")
    sources.review(db, c["super_admin_user"], "case", row.case_snapshot_id, {"expected_revision": 2, "expected_content_hash": row.content_hash, "basis_note": NOTE}, revoke=True)
    db.commit()
    ordinary = sources.case_current(db, c["doctor_user"], row.case_snapshot_id)
    assert ordinary["snapshot"] is None and ordinary["public_source"] is None
    audit = sources.case_current(db, c["super_admin_user"], row.case_snapshot_id, audit_only=True)
    assert audit["snapshot"] and audit["public_source"] == p and not audit["eligible"]


def test_complete_membership_and_nonwinner_mutation_stales_old_snapshot(db_session, case):
    db, c = db_session, case
    row = published(db, c)
    old = sources.capture_case(db, c["doctor_user"], request(c))
    db.add(HomeIcdBinding(home_id=c["home"].home_id, kind="operation", icd_code=c["operation"].code, icd_name=c["operation"].name, is_primary=0, coder_id=c["admin_user"].user_id, code_time=NOW))
    db.commit()
    current = sources.capture_case(db, c["doctor_user"], request(c))
    assert current["collection_digest"] != old["collection_digest"] and len(current["code_bindings"]) == 2
    with pytest.raises(HTTPException) as err:
        sources.case_current(db, c["doctor_user"], row.case_snapshot_id, execution=True)
    assert err.value.status_code == 409
    assert sources.case_current(db, c["super_admin_user"], row.case_snapshot_id, audit_only=True)["snapshot"]


def test_case_scope_and_current_role_before_private_source_body(db_session, case):
    db, c = db_session, case
    row = published(db, c)
    req = request(c)
    req["patient_id"] = c["patient2"].patient_id
    with pytest.raises(HTTPException) as err:
        sources.capture_case(db, c["doctor_user"], req)
    assert err.value.status_code == 403
    actor = c["super_admin_user"]
    db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:pk"), {"pk": actor.user_id})
    with pytest.raises(HTTPException) as err:
        sources.case_current(db, actor, row.case_snapshot_id, audit_only=True)
    assert err.value.status_code == 403


def test_local_prefix_package_actual_rules_draft_publish_revoke_and_unknown_authority(db_session, case):
    db, c = db_session, case
    row = sources.create_package(db, c["super_admin_user"], {"package_kind": "local_prefix_snapshot", "rule_ids": [c["rule"].rule_id], "basis_note": NOTE})
    db.commit()
    sources.review(db, c["super_admin_user"], "package", row.package_id, {"expected_revision": 1, "expected_content_hash": row.content_hash, "decision": "publish", "basis_note": NOTE})
    db.commit()
    p = sources.package_current(db, c["doctor_user"], row.package_id)
    assert p["eligible"] and sources.verify_original(sources.original(row, "package"), "package")
    req = request(c)
    req.update(rule_package_id=row.package_id, expected_rule_package_content_hash=p["content_hash"], expected_rule_package_governance_hash=p["governance_hash"])
    assert sources.verify_capture(sources.capture_case(db, c["doctor_user"], req))
    with pytest.raises(HTTPException) as err:
        sources.create_package(db, c["doctor_user"], {"package_kind": "local_prefix_snapshot", "rule_ids": [c["rule"].rule_id], "basis_note": NOTE})
    assert err.value.status_code == 403
    c["rule"].version = "new mutable local version"
    db.commit()
    assert not sources.package_current(db, c["super_admin_user"], row.package_id, audit_only=True)["eligible"]


@pytest.mark.parametrize("attack", ["missing_binding", "extra_dictionary", "wrong_scope", "extra_key"])
def test_rehashed_partial_or_cross_scope_capture_refused(db_session, case, attack):
    c = sources.capture_case(db_session, case["doctor_user"], request(case))
    v = copy.deepcopy(c)
    if attack == "missing_binding":
        v["code_bindings"] = []
    if attack == "extra_dictionary":
        v["dictionary_entries"].append(copy.deepcopy(v["dictionary_entries"][0]))
    if attack == "wrong_scope":
        v["home"]["patient_id"] += 1
    if attack == "extra_key":
        v["extra"] = False
    v["collection_digest"] = sources.hash_content(sources.collection_content(v))
    assert not sources.verify_capture(v)


def test_unchanged_collection_digest_is_stable_across_server_capture_clock(db_session, case, monkeypatch):
    a = sources.capture_case(db_session, case["doctor_user"], request(case))
    monkeypatch.setattr(sources, "utcnow", lambda: NOW + datetime.timedelta(seconds=1))
    b = sources.capture_case(db_session, case["doctor_user"], request(case))
    assert a["captured_at"] != b["captured_at"] and a["collection_digest"] == b["collection_digest"]


@pytest.mark.parametrize(
    "model,value", [(CaptureRequest, {"patient_id": True}), (RulePackageCreate, {"package_kind": "official_drg", "rule_ids": [1], "basis_note": NOTE}), (CaseCreate, {"as_of": "2000-01-01"})]
)
def test_request_is_closed_and_no_historical_or_official_claim(model, value):
    with pytest.raises(ValueError):
        model.model_validate(value)


def rehash_collection(value):
    value["member_manifest"] = sources.member_manifest(value)
    value["manifest_hash"] = sources.hash_content(value["member_manifest"])
    value["collection_digest"] = sources.hash_content(sources.collection_content(value))
    return value


def test_frozen_internal_proof_reconstructs_original_publication_after_revoke(db_session, case):
    db, c = db_session, case
    row = published(db, c)
    before = sources.frozen_case(db, c["doctor_user"], row.case_snapshot_id)
    assert sources.frozen_case_proof(db, row.case_snapshot_id) == before
    sources.review(db, c["super_admin_user"], "case", row.case_snapshot_id, {"expected_revision": 2, "expected_content_hash": row.content_hash, "basis_note": NOTE}, revoke=True)
    db.commit()
    after = sources.frozen_case_proof(db, row.case_snapshot_id)
    assert after["status"] == "revoked" and after["public_source"] == before["public_source"]
    assert sources.verify_frozen_case(after) and after["public_source"]["case_publication_governance_hash"] != after["governance_hash"]
    with pytest.raises(HTTPException) as err:
        sources.frozen_case(db, c["doctor_user"], row.case_snapshot_id)
    assert err.value.status_code == 409


@pytest.mark.parametrize("attack", ["self_hashed_projection", "action_flag", "unknown_key", "review_before_creation", "bad_revision"])
def test_frozen_full_proof_refuses_rehashed_or_governance_corruption(db_session, case, attack):
    row = published(db_session, case)
    value = sources.frozen_case_proof(db_session, row.case_snapshot_id)
    if attack == "self_hashed_projection":
        value["public_source"]["documents"][0]["text"] = "没有原件依据的新文本"
        value["public_source"]["documents"][0]["text_hash"] = text_hash("没有原件依据的新文本")
        value["projection_hash"] = sources.hash_content(value["public_source"])
    elif attack == "action_flag":
        value["can_review"] = True
    elif attack == "unknown_key":
        value["unrecognized"] = False
    elif attack == "review_before_creation":
        value["reviewed_at"] = "2000-01-01T00:00:00.000000Z"
        value["governance_hash"] = sources.hash_content({k: value[k] for k in sources.GOVERNANCE})
    else:
        value["revision"] = 1
        value["governance_hash"] = sources.hash_content({k: value[k] for k in sources.GOVERNANCE})
    assert not sources.verify_frozen_case(value)


@pytest.mark.parametrize("attack", ["wrong_dictionary_table", "invalid_calendar", "unknown_kind_with_dictionary", "raw_extra"])
def test_rehashed_capture_still_checks_actual_row_type_and_real_calendar(db_session, case, attack):
    value = sources.capture_case(db_session, case["doctor_user"], request(case))
    if attack == "wrong_dictionary_table":
        value["dictionary_entries"][0]["entry"] = sources.row_value(case["operation"])
    elif attack == "invalid_calendar":
        value["home"]["create_time"] = "2026-02-30T01:00:00.000000"
    elif attack == "unknown_kind_with_dictionary":
        value["code_bindings"][0]["kind"] = "legacy_unrecognized_kind"
        value["dictionary_entries"][0]["kind"] = "legacy_unrecognized_kind"
    else:
        value["home"]["unrecorded_field"] = 0
    assert not sources.verify_capture(rehash_collection(value))


@pytest.mark.parametrize("raw_status,expected", [(None, "entry_status_unknown"), (-1, "entry_status_unknown"), (0, "entry_inactive"), (1, "matches_current_dictionary")])
def test_null_or_invalid_dictionary_status_preserved_not_silently_inactive(db_session, case, raw_status, expected):
    # Pure projection semantics using one actual capture, not a claim that the
    # legacy NOT NULL SQL column accepted a null write.
    value = sources.capture_case(db_session, case["doctor_user"], request(case))
    value["dictionary_entries"][0]["entry"]["status"] = raw_status
    assert sources.verify_capture(rehash_collection(value))
    row = published(db_session, case)
    snapshot = json.loads(row.snapshot_json)
    snapshot["collection"] = value
    public = project_snapshot(snapshot, sources.metadata(row))
    assert public["code_bindings"][0]["current_dictionary_state"] == expected
    assert public["dictionary_entries"][0]["entry"]["status"] == raw_status


def test_noncare_author_revoke_refused_before_loading_private_json(db_session, case):
    db, c = db_session, case
    row = published(db, c)
    identifier, digest = row.case_snapshot_id, row.content_hash
    c["admission"].doctor_id = None
    db.commit()
    statements = []
    conn = db.connection()

    def record_sql(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(conn, "before_cursor_execute", record_sql)
    try:
        with pytest.raises(HTTPException) as err:
            sources.review(db, c["doctor_user"], "case", identifier, {"expected_revision": 2, "expected_content_hash": digest, "basis_note": NOTE}, revoke=True)
        assert err.value.status_code == 403
    finally:
        event.remove(conn, "before_cursor_execute", record_sql)
    assert not any("snapshot_json" in statement for statement in statements)
    assert db.query(AICodingCaseSnapshot).filter_by(case_snapshot_id=identifier).one().status == "published"


@pytest.mark.parametrize("root,cap", [(HomeIcdBinding, 4096), (DrgGrouping, 256)])
def test_over_cap_members_refused_at_pk_preflight_before_any_body(db_session, case, root, cap):
    primary = root.binding_id if root is HomeIcdBinding else root.grouping_id
    # Existing complete SQL scope is used; LIMIT preflight itself is exercised
    # with a one-member cap and two actual rows, avoiding thousands of duplicates.
    actual = db_session.query(root).filter_by(home_id=case["home"].home_id).one()
    value = {column.name: getattr(actual, column.name) for column in root.__table__.columns if not column.primary_key}
    if root is DrgGrouping:
        # The real legacy unique index permits only one non-null home group.
        # Use an actual unbound group solely for the generic cap preflight.
        value["home_id"] = None
    additional = root(**value)
    db_session.add(additional)
    db_session.commit()
    charged = []
    with pytest.raises(HTTPException) as err:
        sources._rows(db_session, root, db_session.query(root).filter(primary.in_([getattr(actual, primary.key), getattr(additional, primary.key)])), primary, 1, charged.append)
    assert err.value.status_code == 409 and not charged and cap in (4096, 256)
    if root is DrgGrouping:
        assert len(sources.capture_case(db_session, case["doctor_user"], request(case))["recorded_groups"]) == 1
