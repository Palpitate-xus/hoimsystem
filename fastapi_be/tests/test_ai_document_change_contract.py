"""Pure finite comparison-source policies, without hospital configuration or SQL."""

import copy
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.ai import document_change_contract as c
from app.ai import document_evidence_contract as e
from tests.test_ai_document_extraction_contract import NOTE, NOW, governed_original


def original(index):
    value = governed_original().model_dump(mode="json")
    value["snapshot"]["original_id"] = f"00000000-0000-0000-0000-{index:012}"
    value["content_hash"] = e.digest(value["snapshot"])
    value["source_id"] = f"document_original:{value['snapshot']['original_id']}:{value['content_hash'][:12]}"
    return e.OriginalRecord.model_validate(value)


def reference(value):
    return {"original_id": value.snapshot.original_id, "content_hash": value.content_hash, "governance_hash": value.governance_hash}


def request():
    return {
        "baseline_original": reference(original(71)),
        "candidate_original": reference(original(72)),
        "relationship": {"kind": "comparison_only", "same_guideline_family": "unknown", "basis_note": NOTE},
        "declared_targets": [],
        "rule_link_coverage": "unknown",
        "declaration_basis_note": NOTE,
    }


def governance(published=False):
    return c.Governance(
        status="published" if published else "draft",
        revision=2 if published else 1,
        privacy_review="confirmed" if published else "unknown",
        faithfulness_review="confirmed" if published else "unknown",
        dependency_review="confirmed" if published else "unknown",
        reviewed_by=1 if published else None,
        reviewed_at=NOW if published else None,
        review_basis_note=NOTE if published else "",
        revoked_by=None,
        revoked_at=None,
        revoke_reason="",
    )


def inventory():
    return c.Inventory(schema_version="document_change_inventory_v1", baseline_original=original(71), candidate_original=original(72), targets=[], rule_links=[], publications=[], member_count=2)


def scope():
    captured = inventory()
    snap = c.ScopeImmutable(
        schema_version="document_change_scope_immutable_v1",
        scope_id="00000000-0000-0000-0000-000000000172",
        created_by=1,
        recorded_at=NOW,
        request=c.ScopeCaptureRequest.model_validate(request()),
        inventory_hash=e.digest(captured),
        inventory=captured,
    )
    review = governance()
    return c.ScopeRecord(
        schema_version="document_change_scope_record_v1",
        snapshot=snap,
        content_hash=e.digest(snap),
        governance=review,
        governance_hash=e.digest(review),
        inventory_current=True,
        audit_event_ids={"created": 1, "reviewed": None, "revoked": None},
        eligible=False,
        ineligibility_reasons=["scope_not_published"],
        hospital_wide_rule_inventory="not_provided",
        automatic_supersession=False,
        clinical_validation="not_provided",
    )


def pathway():
    cols = dict.fromkeys(c.PATHWAY_COLUMNS)
    cols.update(pathway_id=1, steps='[{"raw":"unchanged private text"}]', source_revision=1)
    return c.TargetSnapshot(
        schema_version="document_change_target_snapshot_v1", target={"kind": "clinical_pathway", "target_id": 1}, exists=True, columns=cols, state="unknown", state_reasons=["target_state_unknown"]
    )


def test_no_hospital_modules_or_sql_imported_by_contract():
    code = "import sys;import app.ai.document_change_contract;assert not any(n in sys.modules for n in ('app.config','app.database','app.models','sqlalchemy'))"
    checked = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr


def test_same_complete_bytes_with_two_real_original_ids_is_not_forced_to_be_a_change():
    value = scope()
    assert value.snapshot.inventory.baseline_original.snapshot.text == value.snapshot.inventory.candidate_original.snapshot.text
    assert value.snapshot.request.relationship.same_guideline_family == "unknown"
    assert value.hospital_wide_rule_inventory == "not_provided" and value.automatic_supersession is False
    assert c.ScopeRecord.model_validate_json(value.model_dump_json()) == value


@pytest.mark.parametrize("bad", [None, True, 1.0, "1", -1, 0])
def test_target_reference_is_actual_typed_identity_without_bool_or_generic_sql_table(bad):
    body = request()
    body["declared_targets"] = [{"kind": "clinical_pathway", "target_id": bad}]
    with pytest.raises(ValidationError):
        c.ScopeCaptureRequest.model_validate(body)


def test_target_set_is_explicit_canonical_and_cannot_be_duplicates_or_arbitrary_kinds():
    body = request()
    for values in (
        [{"kind": "users", "target_id": 1}],
        [{"kind": "clinical_pathway", "target_id": 1}] * 2,
        [{"kind": "clinical_pathway", "target_id": 2}, {"kind": "clinical_pathway", "target_id": 1}],
    ):
        with pytest.raises(ValidationError):
            c.ScopeCaptureRequest.model_validate({**body, "declared_targets": values})


def test_same_original_cannot_be_both_sides_and_family_is_never_inferred_from_version():
    body = request()
    body["candidate_original"] = body["baseline_original"]
    with pytest.raises(ValidationError):
        c.ScopeCaptureRequest.model_validate(body)
    with pytest.raises(ValidationError):
        c.Relationship(kind="declared_successor", same_guideline_family="unknown", basis_note=NOTE)


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", -1])
def test_exact_span_rejects_coerced_index(bad):
    with pytest.raises(ValidationError):
        c.ExactSpan(start=bad, end=2, quote="字")


def test_span_keeps_bom_crlf_emoji_combining_bytes_and_does_not_imply_semantic_review():
    raw = "\ufeff甲\r\n😀e\u0301"
    value = c.ExactSpan(start=0, end=len(raw), quote=raw)
    assert value.quote == raw and len(e.utf8(value.quote)) > value.end
    with pytest.raises(ValidationError):
        c.ExactSpan(start=0, end=2, quote="😀")


def test_dependency_review_can_reject_even_when_original_privacy_and_literal_fidelity_confirmed():
    body = {
        "expected_revision": 1,
        "expected_content_hash": "a" * 64,
        "expected_governance_hash": "b" * 64,
        "decision": "reject",
        "privacy_review": "confirmed",
        "faithfulness_review": "confirmed",
        "dependency_review": "not_confirmed",
        "basis_note": NOTE,
    }
    assert c.ReviewRequest.model_validate(body).dependency_review == "not_confirmed"
    with pytest.raises(ValidationError):
        c.ReviewRequest.model_validate({**body, "decision": "approve"})


def test_target_snapshot_retains_private_null_zero_and_original_clock_text():
    value = pathway().model_dump(mode="json")
    value["columns"].update(expected_days=0, create_time="2020-01-01 00:00:00", status=None)
    checked = c.TargetSnapshot.model_validate(value)
    assert checked.columns["expected_days"] == 0 and checked.columns["status"] is None
    assert checked.columns["create_time"] == "2020-01-01 00:00:00"
    for name, val in [("status", False), ("source_revision", "1"), ("private_unknown_column", "sentinel")]:
        changed = copy.deepcopy(value)
        changed["columns"][name] = val
        with pytest.raises(ValidationError):
            c.TargetSnapshot.model_validate(changed)


def test_one_inventory_count_cannot_be_per_collection_or_ignore_unique_identity():
    value = inventory().model_dump(mode="json")
    with pytest.raises(ValidationError):
        c.Inventory.model_validate({**value, "member_count": 1})
    value["targets"] = [pathway().model_dump(mode="json")] * 2
    with pytest.raises(ValidationError):
        c.Inventory.model_validate({**value, "member_count": 4})
    assert c.MAX_MEMBERS == 8192


@pytest.mark.parametrize("bad", [0, None, "false", True])
def test_no_automatic_supersession_is_actual_false_not_false_like(bad):
    body = scope().model_dump(mode="json")
    body["automatic_supersession"] = bad
    with pytest.raises(ValidationError):
        c.ScopeRecord.model_validate(body)


def test_immutable_scope_and_governance_digests_cannot_be_self_inconsistent():
    for name in ("content_hash", "governance_hash"):
        body = scope().model_dump(mode="json")
        body[name] = "f" * 64
        with pytest.raises(ValidationError):
            c.ScopeRecord.model_validate(body)
    body = scope().model_dump(mode="json")
    body["audit_event_ids"]["reviewed"] = 2
    with pytest.raises(ValidationError):
        c.ScopeRecord.model_validate(body)


def test_whole_utf8_budget_counts_escaped_json_and_never_truncates():
    with pytest.raises(ValueError, match="byte budget"):
        c.byte_bound({"text": "\0" * 30}, maximum=100)
    original = "😀" * 25
    assert c.byte_bound({"text": original}, maximum=120) is None
    assert len(original) == 25


def test_comparison_original_has_independent_four_mib_registration_limit_not_the_old_65k_task_type():
    text = "字" * 24000
    value = c.DocumentChangeOriginal(
        schema_version="document_change_original_source_v1",
        original=reference(original(71)),
        raw_bytes_hash=e.bytes_hash(text),
        raw_bytes_length=len(text.encode()),
        codepoint_length=len(text),
        text=text,
    )
    assert value.raw_bytes_length == 72000 and value.text == text
    with pytest.raises(ValidationError):
        c.DocumentChangeOriginal.model_validate({**value.model_dump(), "raw_bytes_hash": "f" * 64})
