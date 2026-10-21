"""Pure public closure from actual governed Source SQL, not clinical interpretation."""

import copy
import hashlib
import hmac

import pytest
from fastapi import HTTPException

from app.ai import document_evidence_contract as d
from app.ai import drug_label_sources as sources
from app.ai.drug_label_projection import DrugLabelPublicSource, project_source, projection_hash, verify_projection
from tests.test_ai_drug_label_sources import NOTE, cas, create, publish
from tests.test_ai_drug_label_sources import label_case as _label_case

label_case = _label_case
SECRET = "7e" * 32


def test_unique_projection_binds_full_literal_bytes_scoped_identity_and_private_hashes(label_case):
    source = publish(label_case)
    public = project_source(source, secret=SECRET)
    expected_token = (
        "drug_label_sku:"
        + hmac.new(bytes.fromhex(SECRET), d.canonical_json(["drug_label_sku_v1", source.snapshot.source_binding_id, source.snapshot.identity.pharmaceutical_id]).encode(), hashlib.sha256).hexdigest()
    )
    assert public.sku.sku_token == expected_token
    assert public.text == source.snapshot.original.snapshot.text
    assert public.raw_bytes_hash == hashlib.sha256(public.text.encode()).hexdigest()
    assert public.codepoint_length == len(public.text) and public.raw_bytes_length == len(public.text.encode())
    assert "\ufeff" in public.text and "\r\n" in public.text and "😀e\u0301" in public.text
    assert public.binding.content_hash == source.content_hash
    assert public.binding.governance_hash == source.governance_hash
    assert public.binding.original.governance_hash == source.snapshot.original.governance_hash
    assert public.binding.professional == source.governance.professional
    assert public.declared_version == source.snapshot.original.snapshot.metadata.version
    assert public.professional_scope.licensure_status == "unknown" and public.clinical_validation == "not_provided"
    assert public.version_basis == "submitter_declared_not_independently_verified"
    assert public.missing_catalog_or_authority_evidence == source.missing_evidence
    assert not public.automatic_clinical_rule
    assert verify_projection(public, source, secret=SECRET)


def test_projection_excludes_actor_private_notes_and_inventory_fields_by_structure(label_case):
    source = publish(label_case)
    public = project_source(source, secret=SECRET).model_dump(mode="json")
    keys = set()

    def collect(value):
        if isinstance(value, dict):
            keys.update(value)
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(public)
    assert (
        not {
            "pharmaceutical_id",
            "created_by",
            "reviewed_by",
            "signed_by",
            "revoked_by",
            "user_id",
            "username",
            "basis_note",
            "review_basis_note",
            "revoke_reason",
            "supplier",
            "stock",
            "price",
            "patient_id",
            "admission_id",
        }
        & keys
    )
    assert NOTE not in d.canonical_json(public)
    assert public["release_basis_digest"] == hashlib.sha256(NOTE.encode()).hexdigest()
    assert public["sku"]["comparison_fields"] == ["name", "barcode", "status"]


@pytest.mark.parametrize("axis", ["source", "professional", "identity", "signer"])
def test_real_current_withdrawal_freezes_exact_original_projection_without_restoring_eligibility(label_case, axis):
    db, users, sku, _ = label_case
    source = publish(label_case)
    before = project_source(source, secret=SECRET)
    if axis == "source":
        sources.revoke_source(db, users["super_admin_user"], source.snapshot.source_binding_id, {**cas(source), "basis_note": NOTE})
    elif axis == "professional":
        sources.revoke_professional(db, users["pharmacist_user"], source.snapshot.source_binding_id, {**cas(source.professional_review), "basis_note": NOTE})
    elif axis == "identity":
        sku.barcode = "actual-changed-barcode"
    else:
        users["pharmacist_user"].user_role = "patient"
    db.commit()
    frozen = sources.source_current(db, users["super_admin_user"], source.snapshot.source_binding_id, audit_only=True)
    assert not frozen.eligible and not frozen.can_review and not frozen.can_revoke
    with pytest.raises(ValueError):
        project_source(frozen, secret=SECRET)
    assert project_source(frozen, secret=SECRET, frozen=True) == before
    with pytest.raises(HTTPException):
        sources.source_current(db, users["pharmacist_user"], source.snapshot.source_binding_id, execution=True)
    if axis == "signer":
        users["pharmacist_user"].user_role = "pharmacist"
        db.commit()


@pytest.mark.parametrize("mode", ["draft", "rejected", "draft_revoked"])
def test_never_published_source_cannot_be_turned_into_frozen_publication(label_case, mode):
    db, users, _, _ = label_case
    source = create(label_case)
    if mode == "rejected":
        source = sources.review_source(db, users["super_admin_user"], source.snapshot.source_binding_id, {**cas(source), "decision": "reject", "professional": None, "basis_note": NOTE})
    elif mode == "draft_revoked":
        source = sources.revoke_source(db, users["super_admin_user"], source.snapshot.source_binding_id, {**cas(source), "basis_note": NOTE})
    db.commit()
    with pytest.raises(ValueError):
        project_source(source, secret=SECRET, frozen=True)


@pytest.mark.parametrize("secret", [None, "", "7" * 63, "A" * 64, b"7e" * 32])
def test_private_hmac_secret_is_not_defaulted_or_coerced(label_case, secret):
    source = publish(label_case)
    with pytest.raises(ValueError):
        project_source(source, secret=secret)


def test_same_sku_different_binding_has_different_technical_token(label_case):
    first = project_source(publish(label_case), secret=SECRET)
    second = project_source(publish(label_case), secret=SECRET)
    assert first.sku.name == second.sku.name and first.sku.sku_token != second.sku.sku_token


def test_self_rehash_of_valid_public_text_does_not_establish_private_source_binding(label_case):
    source = publish(label_case)
    public = project_source(source, secret=SECRET).model_dump(mode="json")
    public["text"] += "伪造但可自哈希"
    public["raw_bytes_hash"] = d.bytes_hash(public["text"])
    public["raw_bytes_length"] = len(public["text"].encode())
    public["codepoint_length"] = len(public["text"])
    assert DrugLabelPublicSource.model_validate(public)
    assert not verify_projection(public, source, secret=SECRET)


@pytest.mark.parametrize("mutation", ["actor", "note", "missing", "unit", "bool_false"])
def test_public_closed_shape_and_declared_unknowns_cannot_be_relaxed(label_case, mutation):
    source = publish(label_case)
    public = copy.deepcopy(project_source(source, secret=SECRET).model_dump(mode="json"))
    if mutation == "actor":
        public["professional_scope"]["signed_by"] = 1
    elif mutation == "note":
        public["basis_note"] = NOTE
    elif mutation == "missing":
        public["missing_catalog_or_authority_evidence"] = []
    elif mutation == "unit":
        public["sku"]["unit"] = "片"
    else:
        public["automatic_clinical_rule"] = 0
    assert not verify_projection(public, source, secret=SECRET)


def test_same_source_id_distinct_immutable_task_seeds_have_distinct_full_projection_hashes(label_case):
    source = publish(label_case)
    first = project_source(source, secret=SECRET)
    replay = project_source(source, secret=SECRET)
    other = project_source(source, secret="91" * 32)
    assert first == replay and projection_hash(first) == projection_hash(replay)
    assert first.source_id == other.source_id and first.binding == other.binding
    assert first.sku.sku_token != other.sku.sku_token and projection_hash(first) != projection_hash(other)
    assert projection_hash(first) == hashlib.sha256(d.canonical_json(first).encode()).hexdigest()


def test_previously_valid_source_model_mutation_does_not_bypass_full_source_revalidation(label_case):
    source = publish(label_case).model_copy(deep=True)
    source.snapshot.identity.name = "未绑定的新名称"
    with pytest.raises(ValueError):
        project_source(source, secret=SECRET)
