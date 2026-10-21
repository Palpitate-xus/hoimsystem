"""Actual SQL permission precedes one seeded complete literal model payload."""

import copy
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.ai import document_evidence_contract as d
from app.ai import drug_label_sources as sources
from app.ai.drug_label_context import expand_context, prepare_context
from app.ai.drug_label_context_contract import binding_for_projection, evidence_for_binding, expand_public_context, public_payload, short_context
from app.ai.drug_label_projection import projection_hash
from tests.test_ai_drug_label_sources import NOTE, cas, publish
from tests.test_ai_drug_label_sources import label_case as _label_case

label_case = _label_case
SEED = "7e" * 32


@pytest.fixture
def prepared(label_case):
    record = publish(label_case)
    bundle, record, source, seed = prepare_context(label_case[0], label_case[1]["pharmacist_user"], {"drug_label_source_binding_id": record.snapshot.source_binding_id}, mapping_seed=SEED)
    return label_case, bundle, record, source, seed


def payload(bundle, source, values=None):
    return {
        "input": {"drug_label_source_binding_id": source.binding.source_binding_id} if values is None else values,
        "context": expand_public_context(bundle.data, source),
        "tools": {},
        "evidence": bundle.evidence,
    }


def test_actual_current_role_scope_full_source_and_private_seed_are_separate(prepared):
    case, bundle, record, source, seed = prepared
    assert record.eligible and not record.audit_only
    assert seed == SEED and seed not in d.canonical_json(bundle.data)
    assert seed not in d.canonical_json(bundle.evidence) and seed not in d.canonical_json(source)
    assert source.text == record.snapshot.original.snapshot.text
    assert bundle.data == short_context(binding_for_projection(source), bundle.data["snapshot_time"])
    assert bundle.evidence == evidence_for_binding(binding_for_projection(source)) and len(bundle.evidence) == 2
    assert bundle.department_ids == set()
    visible = public_payload(payload(bundle, source))
    assert visible == {"drug_label_source": source.model_dump(mode="json"), "question": None}
    assert '"pharmaceutical_id":' not in d.canonical_json(visible)
    assert '"basis_note":' not in d.canonical_json(visible)
    expanded, current, verified = expand_context(case[0], case[1]["pharmacist_user"], bundle.data, mapping_seed=seed)
    assert current.eligible and verified == source and expanded == payload(bundle, source)["context"]


@pytest.mark.parametrize("question", [None, "", " \t\r\n\u2003", "\ufeff", "😀" * 2000])
def test_actual_prepare_and_public_payload_preserve_optional_question_exactly(label_case, question):
    original = publish(label_case)
    values = {"drug_label_source_binding_id": original.snapshot.source_binding_id, "question": question}
    bundle, _, source, _ = prepare_context(label_case[0], label_case[1]["super_admin_user"], values, mapping_seed=SEED)
    assert public_payload(payload(bundle, source, values))["question"] == question
    assert values["question"] == question


def test_new_tasks_receive_distinct_private_mapping_seeds_and_bound_public_hashes(prepared):
    case, _, record, _, _ = prepared
    values = {"drug_label_source_binding_id": record.snapshot.source_binding_id}
    first = prepare_context(case[0], case[1]["super_admin_user"], values)
    second = prepare_context(case[0], case[1]["super_admin_user"], values)
    assert len(first[3]) == len(second[3]) == 64 and first[3] != second[3]
    assert first[2].source_id == second[2].source_id
    assert first[2].sku.sku_token != second[2].sku.sku_token
    assert first[0].data["drug_label_binding"]["source_projection_hash"] == projection_hash(first[2])
    assert second[0].data["drug_label_binding"]["source_projection_hash"] == projection_hash(second[2])


@pytest.mark.parametrize("axis", ["missing_id", "wrong_id", "numeric_id", "patient", "department", "private_seed", "question_bool", "question_large", "surrogate"])
def test_invalid_selection_refused_before_any_source_sql(prepared, axis):
    case, _, record, _, _ = prepared
    values = {"drug_label_source_binding_id": record.snapshot.source_binding_id}
    if axis == "missing_id":
        values = {}
    elif axis == "wrong_id":
        values["drug_label_source_binding_id"] = "not-a-canonical-uuid"
    elif axis == "numeric_id":
        values["drug_label_source_binding_id"] = True
    elif axis == "patient":
        values["patient_id"] = 1
    elif axis == "department":
        values["department_id"] = 1
    elif axis == "private_seed":
        values["mapping_seed"] = SEED
    elif axis == "question_bool":
        values["question"] = False
    elif axis == "question_large":
        values["question"] = "😀" * 2001
    else:
        values["question"] = "\ud800"
    statements = []
    with _Observe(case[0], statements):
        with pytest.raises(HTTPException) as refused:
            prepare_context(case[0], case[1]["super_admin_user"], values)
    assert refused.value.status_code == 422 and statements == []


class _Observe:
    def __init__(self, db, statements):
        self.engine = db.bind
        self.listener = lambda *args: statements.append(args[2])

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self.listener)

    def __exit__(self, *args):
        event.remove(self.engine, "before_cursor_execute", self.listener)


def test_denied_current_role_reads_no_protected_original_or_binding_body(prepared):
    case, _, record, _, _ = prepared
    statements = []
    with _Observe(case[0], statements):
        with pytest.raises(HTTPException) as refused:
            prepare_context(case[0], case[1]["doctor_user"], {"drug_label_source_binding_id": record.snapshot.source_binding_id}, mapping_seed=SEED)
    assert refused.value.status_code == 403
    assert not any("snapshot_json" in sql.lower() and "hoimsystem_ai_drug_label_source" in sql.lower() for sql in statements)
    assert not any("hoimsystem_ai_document_original" in sql.lower() for sql in statements)


@pytest.mark.parametrize("axis", ["source", "signature", "original", "identity", "signer"])
def test_current_changes_block_existing_projection_and_new_tasks_but_super_explicit_frozen_audit_preserves_seeded_bytes(prepared, axis):
    case, bundle, record, source, seed = prepared
    db, users, sku, original = case
    if axis == "source":
        sources.revoke_source(db, users["super_admin_user"], record.snapshot.source_binding_id, {**cas(record), "basis_note": NOTE})
    elif axis == "signature":
        professional = record.professional_review
        sources.revoke_professional(db, users["pharmacist_user"], record.snapshot.source_binding_id, {**cas(professional), "basis_note": NOTE})
    elif axis == "original":
        from app.ai import document_evidence_sources as documents

        documents.revoke_original(db, users["super_admin_user"], original.snapshot.original_id, {**cas(original), "basis_note": NOTE})
    elif axis == "identity":
        sku.barcode = "synthetic-changed-identity"
    else:
        users["pharmacist_user"].user_role = "doctor"
    db.commit()
    with pytest.raises(HTTPException) as stale:
        expand_context(db, users["super_admin_user"], bundle.data, mapping_seed=seed)
    assert stale.value.status_code == 409
    db.rollback()
    expanded, frozen, actual = expand_context(db, users["super_admin_user"], bundle.data, mapping_seed=seed, frozen_audit=True)
    assert frozen.audit_only and not frozen.eligible and actual == source
    assert expanded == payload(bundle, source)["context"]
    db.rollback()
    if axis == "signer":
        users["pharmacist_user"].user_role = "pharmacist"
        db.commit()
    with pytest.raises(HTTPException) as denied:
        expand_context(db, users["pharmacist_user"], bundle.data, mapping_seed=seed, frozen_audit=True)
    assert denied.value.status_code == 403


@pytest.mark.parametrize("axis", ["seed", "clock_before_publication", "short_extra", "different_scope", "invalid_audit_scalar"])
def test_original_seed_and_complete_short_context_required_on_current_read(prepared, axis):
    case, bundle, _, _, seed = prepared
    context = copy.deepcopy(bundle.data)
    kwargs = {"mapping_seed": seed}
    if axis == "seed":
        kwargs["mapping_seed"] = "a4" * 32
    elif axis == "clock_before_publication":
        context["snapshot_time"] = "2000-01-01T00:00:00.000000Z"
    elif axis == "short_extra":
        context["patient_id"] = 1
    elif axis == "different_scope":
        context["scope"] = "hospital"
    else:
        kwargs["frozen_audit"] = 0
    with pytest.raises(HTTPException) as refused:
        expand_context(case[0], case[1]["super_admin_user"], context, **kwargs)
    assert refused.value.status_code == 409


@pytest.mark.parametrize("axis", ["top_extra", "tools", "private_context", "changed_quote", "changed_seed_token", "changed_binding", "extra_evidence", "missing_evidence", "mixed_input"])
def test_only_unique_complete_public_source_and_exact_short_evidence_can_leave(prepared, axis):
    _, bundle, _, source, _ = prepared
    value = payload(bundle, source)
    if axis == "top_extra":
        value["provider"] = "untrusted"
    elif axis == "tools":
        value["tools"] = {"catalog_update": {}}
    elif axis == "private_context":
        value["context"]["private_original"] = {"basis_note": NOTE}
    elif axis == "changed_quote":
        value["context"]["drug_label_source"]["text"] += "changed"
    elif axis == "changed_seed_token":
        value["context"]["drug_label_source"]["sku"]["sku_token"] = "drug_label_sku:" + "0" * 64
    elif axis == "changed_binding":
        value["context"]["drug_label_binding"]["source_projection_hash"] = "0" * 64
    elif axis == "extra_evidence":
        value["evidence"] = [*value["evidence"], value["evidence"][0]]
    elif axis == "missing_evidence":
        value["evidence"] = []
    else:
        value["input"]["satisfaction_case_id"] = source.binding.source_binding_id
    with pytest.raises((ValueError, KeyError)):
        public_payload(value)


def test_private_seed_not_in_any_serialized_task_part_and_public_body_stays_complete(prepared):
    _, bundle, record, source, seed = prepared
    value = payload(bundle, source)
    wire = json.loads(d.canonical_json(public_payload(value)))
    assert set(wire) == {"drug_label_source", "question"}
    assert wire["drug_label_source"]["text"] == record.snapshot.original.snapshot.text
    assert seed not in d.canonical_json(value)
    assert len(d.utf8(d.canonical_json(bundle.data))) < 65535
    assert len(d.utf8(d.canonical_json(bundle.evidence))) < 65535
