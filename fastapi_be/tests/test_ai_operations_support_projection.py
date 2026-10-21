"""No private original fields, partial-source acceptance or implicit live-system claims."""

import copy
import json
import uuid

import pytest
from pydantic import ValidationError

from app.ai import operations_support_contract as c
from app.ai import operations_support_projection as p
from tests.test_ai_operations_support_contract import original, review


def member(kind="diagnostic_log", text=None):
    source = original() if text is None else original(text)
    source = c.OperationsOriginal.model_validate(
        {**source.model_dump(), "kind": kind, "title": "PRIVATE_TITLE_SENTINEL", "origin_note": "PRIVATE_PATH_SENTINEL", "declared_component": "PRIVATE_HOST_SENTINEL"}
    )
    declared = review(source) if text is None else review(source, spans=[])
    return {"original": source.model_dump(), "review": declared.model_dump()}


def collection(members=None):
    return {
        "schema_version": "operations_support_collection_v1",
        "collection_id": str(uuid.uuid4()),
        "assembled_at": "2026-10-21T17:05:00.999999Z",
        "requested_by": 3,
        "members": members if members is not None else [member(), member("runbook", "合成手册\ufeff\r\n确认服务状态，不在此处执行任何命令😀")],
    }


def test_public_source_contains_only_complete_reviewed_derivatives_and_explicit_declarations():
    private = collection()
    source = p.project_source(private)
    raw = c.canonical_json(source)
    assert source.counts.model_dump() == {"documents": 2, "diagnostic_logs": 1, "runbooks": 1, "reference_documents": 0}
    assert source.coverage == "explicit_reviewed_derivatives_only_not_live_system_inventory"
    assert source.applicability == "manual_declarations_not_independent_live_compatibility_proof"
    assert source.action_basis == "reviewed_runbook_reference_only"
    assert p.verify_public_source(source, private)
    assert p.projection_digest(source) == c.content_hash(source)
    for private_member in private["members"]:
        assert private_member["review"]["released_text"] in [d.text for d in source.documents]
        for forbidden in [
            "PRIVATE_TITLE_SENTINEL",
            "PRIVATE_PATH_SENTINEL",
            "PRIVATE_HOST_SENTINEL",
            private_member["original"]["original_id"],
            private_member["review"]["review_basis"],
            "password=合成😀SECRET",
        ]:
            assert forbidden not in raw
    assert not {"requested_by", "captured_by", "reviewed_by", "original_full_sha256", "origin_note", "redactions"}.intersection(source.model_dump())


def test_diagnostic_only_source_explicitly_has_no_reviewed_action_basis():
    source = p.project_source(collection([member()]))
    assert source.action_basis == "missing_reviewed_runbook" and source.counts.runbooks == 0
    forged = source.model_dump()
    forged["action_basis"] = "reviewed_runbook_reference_only"
    with pytest.raises(ValidationError):
        p.OperationsSupportSource.model_validate(forged)


@pytest.mark.parametrize("field", ["content_text", "title", "origin_note", "declared_component"])
def test_same_public_derivative_cannot_validate_changed_private_original(field):
    private = collection()
    source = p.project_source(private)
    private["members"][0]["original"][field] = "PRIVATE_CHANGED_SENTINEL"
    with pytest.raises(ValidationError):
        p.verify_public_source(source, private)


@pytest.mark.parametrize("field,value", [("requested_by", True), ("assembled_at", "2026-10-21T17:00:00.000001Z"), ("unknown_context", "unreviewed")])
def test_private_author_and_whole_review_order_are_strict(field, value):
    private = collection()
    private[field] = value
    with pytest.raises(ValidationError):
        p.verify_private_collection(private)


@pytest.mark.parametrize("identity", ["original", "review"])
def test_duplicate_root_or_review_identity_is_rejected_without_deduplication(identity):
    private = collection()
    private["members"][1][identity] = copy.deepcopy(private["members"][0][identity])
    if identity == "original":
        private["members"][1]["review"] = review(c.OperationsOriginal.model_validate(private["members"][1]["original"])).model_dump()
    with pytest.raises(ValidationError):
        p.verify_private_collection(private)


def test_all128_distinct_roots_are_retained_even_when_their_text_is_equal_then129_fails():
    private = collection([member("reference_document", "相同原文也不代表同一原件😀") for _ in range(c.MAX_SOURCES)])
    source = p.project_source(private)
    assert len(source.documents) == 128 and len({d.source_id for d in source.documents}) == 128
    assert source.counts.reference_documents == 128
    private["members"].append(member("reference_document", "第129件必须完整拒绝"))
    with pytest.raises(ValidationError):
        p.project_source(private)


@pytest.mark.parametrize("mutation", ["missing", "wrong_text", "wrong_kind", "extra", "wrong_source_id"])
def test_structurally_rehashed_or_partial_public_source_cannot_pass_private_reprojection(mutation):
    private = collection()
    source = p.project_source(private).model_dump()
    if mutation == "missing":
        source["documents"].pop()
        source["counts"]["documents"] -= 1
    elif mutation == "wrong_text":
        source["documents"][0]["text"] += "可疑补写"
        import hashlib

        source["documents"][0]["text_sha256"] = hashlib.sha256(source["documents"][0]["text"].encode()).hexdigest()
    elif mutation == "wrong_kind":
        source["documents"][0]["kind"] = "reference_document"
    elif mutation == "extra":
        source["private_original"] = "must not be accepted"
    else:
        source["source_id"] = str(uuid.uuid4())
    try:
        assert p.verify_public_source(source, private) is False
    except ValidationError:
        pass


def test_whole_json_loader_rejects_duplicate_names_fractional_coercion_nonfinite_and_invalid_utf8():
    raw = c.canonical_json(collection())
    assert p.verify_private_collection(raw.encode()).members
    duplicate = raw.replace('"requested_by":3', '"requested_by":3,"requested_by":3')
    fractional = raw.replace('"requested_by":3', '"requested_by":3.0')
    nonfinite = raw.replace('"requested_by":3', '"requested_by":NaN')
    for bad in [duplicate, fractional, nonfinite, b"\xff", b"x" * (c.MAX_WHOLE_BYTES + 1)]:
        with pytest.raises(ValueError):
            p.verify_private_collection(bad)


def test_commands_script_like_text_and_repeated_markers_remain_inert_exact_data():
    text = "</script><script>SHOULD_NOT_EXECUTE()</script>\r\n$(synthetic-only) `literal`\ufeff😀"
    private = collection([member("runbook", text)])
    source = p.project_source(private)
    assert source.documents[0].text == text
    assert json.loads(c.canonical_json(source))["documents"][0]["text"] == text
    assert p.verify_public_source(source, private)


def test_null_and_empty_released_declarations_remain_distinct_from_private_values():
    private = collection([member("runbook", "受审原文")])
    private["members"][0]["original"]["declared_version"] = "PRIVATE_VERSION_SENTINEL"
    source_original = c.OperationsOriginal.model_validate(private["members"][0]["original"])
    private["members"][0]["review"]["original_full_sha256"] = c.content_hash(source_original)
    private["members"][0]["review"]["released_component"] = ""
    private["members"][0]["review"]["released_version"] = None
    projected = p.project_source(private)
    assert projected.documents[0].declared_component == ""
    assert projected.documents[0].declared_version is None
    assert "PRIVATE_VERSION_SENTINEL" not in c.canonical_json(projected)


def test_actual_complete_collection_at8m_then_one_byte_more_fails_without_a_partial_projection():
    one = collection([member("runbook", "x")])
    overhead = len(c.canonical_json(one).encode()) - 2
    length, remainder = divmod(c.MAX_WHOLE_BYTES - overhead, 2)
    assert 0 < length < c.MAX_TEXT_BYTES
    private = collection([member("runbook", "x" * length)])
    if remainder:
        private["members"][0]["review"]["review_basis"] += "x"
    assert len(c.canonical_json(private).encode()) == c.MAX_WHOLE_BYTES
    projected = p.project_source(c.canonical_json(private).encode())
    assert projected.documents[0].text == "x" * length
    private["members"][0]["review"]["review_basis"] += "x"
    assert len(c.canonical_json(private).encode()) == c.MAX_WHOLE_BYTES + 1
    for value in [private, c.canonical_json(private).encode()]:
        with pytest.raises(ValueError):
            p.project_source(value)
