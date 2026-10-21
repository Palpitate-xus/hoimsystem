"""Actual governed Source and SQL task artifacts, not a worker or provider call."""

import copy
import hashlib
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, func, text
from sqlalchemy.dialects import mysql

from app.ai import document_evidence_contract as d
from app.ai import drug_label_sources as sources
from app.ai import drug_label_storage as storage
from app.ai.context import context_metadata
from app.ai.drug_label_context import prepare_context
from app.ai.drug_label_draft import SYSTEM_PROMPT, TASK_PROMPT, build_draft
from app.ai.drug_label_result import result_for_draft
from app.ai.drug_label_run_contract import ACCEPT_ACTION, CREATE_ACTION, USAGE_ACTION
from app.ai.drug_label_run_models import HASH_FIELDS, AIDrugLabelRunArtifact
from app.ai.models import AIAuditEvent, AIFeatureConfig, AIPromptVersion, AIProvider, AIRun
from app.models import User
from tests.test_ai_drug_label_sources import NOTE, cas, publish
from tests.test_ai_drug_label_sources import label_case as _label_case

label_case = _label_case
SEED = "b7" * 32


def make_task(case, kind="chat", stage=True):
    db, users, *_ = case
    source = publish(case)
    actor = users["pharmacist_user"]
    provider = AIProvider(
        name="leaflet-storage-" + str(uuid.uuid4()),
        kind=kind,
        api_base="https://synthetic.invalid/v1",
        model="synthetic-label-model",
        enabled=1,
        allows_patient_data=1,
        timeout_seconds=30,
        max_output_tokens=2000,
        temperature=0.2,
        validation_report=NOTE,
        created_by=users["super_admin_user"].user_id,
    )
    version = (db.query(func.max(AIPromptVersion.version)).filter_by(feature_key=storage.FEATURE_KEY).scalar() or 0) + 1
    prompt = AIPromptVersion(feature_key=storage.FEATURE_KEY, version=version, task_prompt=TASK_PROMPT, change_note=NOTE, created_by=users["super_admin_user"].user_id)
    db.add_all([provider, prompt])
    db.flush()
    config = db.get(AIFeatureConfig, storage.FEATURE_KEY)
    if config is None:
        config = AIFeatureConfig(feature_key=storage.FEATURE_KEY)
        db.add(config)
    config.enabled = 1
    config.provider_id = provider.provider_id
    config.allowed_roles_json = '["pharmacist","super_admin"]'
    config.validation_status = "pilot"
    config.validation_note = NOTE
    config.validated_by = users["super_admin_user"].user_id
    config.validated_at = sources.utcnow()
    config.active_prompt_id = prompt.prompt_id
    config.updated_by = users["super_admin_user"].user_id
    config.revision = 3
    db.commit()
    values = {"drug_label_source_binding_id": source.snapshot.source_binding_id, "question": " \t\r\n\u2003"}
    bundle, record, public, seed = prepare_context(db, actor, values, mapping_seed=SEED)
    snapshot = {
        "catalog_version": "synthetic-current-label-catalog",
        "system_prompt": SYSTEM_PROMPT,
        "task_prompt": prompt.task_prompt,
        "payload": {"input": values, "context": bundle.data, "tools": {}, "evidence": bundle.evidence},
        "provider_snapshot": {
            "provider_id": provider.provider_id,
            "revision": provider.revision,
            "name": provider.name,
            "kind": provider.kind,
            "api_base": provider.api_base,
            "model": provider.model,
            "timeout_seconds": provider.timeout_seconds,
            "max_output_tokens": provider.max_output_tokens,
            "validation_report": provider.validation_report,
            "temperature": float(provider.temperature),
            "allows_patient_data": True,
            "effective_output_limit": provider.max_output_tokens,
        },
        "feature_validation": {
            "status": config.validation_status,
            "note": config.validation_note,
            "validated_by": config.validated_by,
            "validated_at": str(config.validated_at),
            "feature_revision": config.revision,
        },
    }
    instruction = hashlib.sha256((SYSTEM_PROMPT + "\n\n" + prompt.task_prompt).encode()).hexdigest()
    metadata = {
        **context_metadata(bundle),
        "feature_revision": config.revision,
        "validation_status": config.validation_status,
        "tool_fingerprint": d.digest({}),
        "instructions_digest": instruction,
        "model_version": provider.model,
    }
    run = AIRun(
        feature_key=storage.FEATURE_KEY,
        provider_id=provider.provider_id,
        provider_revision=provider.revision,
        prompt_version=prompt.version,
        prompt_hash=d.digest([SYSTEM_PROMPT, prompt.task_prompt]),
        context_digest=d.digest(bundle.data),
        requested_by=actor.user_id,
        status="queued",
        input_json=d.canonical_json(snapshot),
        evidence_json=d.canonical_json(bundle.evidence),
        context_metadata_json=d.canonical_json(metadata),
        result_json="{}",
    )
    db.add(run)
    db.flush()
    binding = storage._task(run)[1]
    audit = AIAuditEvent(actor_id=actor.user_id, action=CREATE_ACTION, target=run.run_id, detail_json=storage.create_audit_detail(run, binding))
    db.add(audit)
    db.flush()
    if stage:
        storage.stage_artifact(db, run, mapping_seed=seed, create_event_id=audit.event_id)
        db.commit()
    return SimpleNamespace(
        db=db,
        users=users,
        actor=actor,
        source=source,
        public=public,
        seed=seed,
        bundle=bundle,
        snapshot=snapshot,
        metadata=metadata,
        run=run,
        audit=audit,
        provider=provider,
        config=config,
        prompt=prompt,
    )


@pytest.fixture
def task(label_case):
    return make_task(label_case)


def refused(operation, status=409):
    with pytest.raises(HTTPException) as caught:
        operation()
    assert caught.value.status_code == status


def complete(case, *, status="succeeded", counts=(13, 7), attempted=True):
    stored = storage.load_snapshot(case.db, case.run)
    run, artifact = stored.run, stored.artifact
    run.status = status
    run.lease_token = str(uuid.uuid4())
    run.input_tokens = counts[0] or 0
    run.output_tokens = counts[1] or 0
    raw = None
    if status == "succeeded":
        start = stored.public_source.text.index("合成成分")
        draft = build_draft(
            {"fields": [{"field": "composition", "spans": [{"start": start, "end": start + 4, "quote": "合成成分"}], "review_question": "请药师逐字核对该字段条件和类别；未作医学验证。"}]},
            stored.public_source,
            stored.metadata["instructions_digest"],
        )
        raw = d.canonical_json(result_for_draft(draft, stored.public_source, stored.metadata["instructions_digest"]))
    result_hash = hashlib.sha256(raw.encode()).hexdigest() if raw else None
    receipt = {
        "schema_version": "drug_label_usage_receipt_v1",
        "run_id": run.run_id,
        "source_binding_hash": artifact.source_binding_hash,
        "input_hash": artifact.input_hash,
        "evidence_hash": artifact.evidence_hash,
        "metadata_hash": artifact.metadata_hash,
        "lease_token": run.lease_token,
        "model_call_attempted": attempted,
        "input_tokens": counts[0],
        "output_tokens": counts[1],
        "result_hash": result_hash,
        "status": status,
    }
    usage = AIAuditEvent(actor_id=run.requested_by, action=USAGE_ACTION, target=run.run_id, detail_json=d.canonical_json(receipt))
    case.db.add(usage)
    case.db.flush()
    if raw:
        planned = replace(
            stored, artifact=SimpleNamespace(result_hash=result_hash, result_bytes=len(raw.encode()), accepted_at=sources.utcnow(), accepted_lease=run.lease_token, receipt_event_id=usage.event_id)
        )
        accept = AIAuditEvent(actor_id=run.requested_by, action=ACCEPT_ACTION, target=run.run_id, detail_json=storage.accept_audit_detail(planned))
        case.db.add(accept)
        case.db.flush()
        artifact.result_json = raw
        artifact.result_hash = result_hash
        artifact.result_bytes = len(raw.encode())
        artifact.accepted_at = planned.artifact.accepted_at
        artifact.accepted_lease = run.lease_token
        artifact.accept_event_id = accept.event_id
        run.result_json = d.canonical_json(storage.result_pointer(run.run_id, result_hash, len(raw.encode())))
    artifact.receipt_event_id = usage.event_id
    case.db.commit()
    return d.parse_json(raw) if raw else None


@pytest.mark.parametrize("kind", ["chat", "responses"])
def test_real_sql_queue_full_result_private_seed_and_distinct_prompt_digests(label_case, kind):
    case = make_task(label_case, kind)
    stored = storage.authorize_drug_label_run(case.db, case.actor, case.run)
    assert stored.public_source == case.public and stored.artifact.mapping_seed == SEED
    assert storage.verify_artifact_result(case.db, stored) is None
    assert case.run.prompt_hash == hashlib.sha256(d.canonical_json([SYSTEM_PROMPT, TASK_PROMPT]).encode()).hexdigest()
    assert stored.metadata["instructions_digest"] == hashlib.sha256((SYSTEM_PROMPT + "\n\n" + TASK_PROMPT).encode()).hexdigest() != case.run.prompt_hash
    assert SEED not in case.run.input_json + case.run.evidence_json + case.run.context_metadata_json
    assert '"text":' not in case.run.input_json and stored.snapshot["payload"]["input"]["question"] == " \t\r\n\u2003"
    assert stored.artifact.input_hash == hashlib.sha256(case.run.input_json.encode()).hexdigest()
    expected = complete(case)
    assert storage.load_result(case.db, case.actor, case.run) == expected
    stored = storage.load_snapshot(case.db, case.run)
    assert len({stored.artifact.create_event_id, stored.artifact.receipt_event_id, stored.artifact.accept_event_id}) == 3
    assert "drug_label_result_pointer_v1" in case.run.result_json and '"fields":' not in case.run.result_json


@pytest.mark.parametrize("field", [*HASH_FIELDS, "mapping_seed"])
def test_each_actual_artifact_anchor_and_seed_is_necessary(task, field):
    row = task.db.get(AIDrugLabelRunArtifact, task.run.run_id)
    setattr(row, field, "ef" * 32)
    task.db.commit()
    refused(lambda: storage.load_snapshot(task.db, task.run))


@pytest.mark.parametrize(
    "group,key",
    [
        ("provider_snapshot", k)
        for k in (
            "provider_id",
            "revision",
            "name",
            "kind",
            "api_base",
            "model",
            "timeout_seconds",
            "max_output_tokens",
            "validation_report",
            "temperature",
            "allows_patient_data",
            "effective_output_limit",
        )
    ]
    + [("feature_validation", k) for k in ("status", "note", "validated_by", "validated_at", "feature_revision")],
)
def test_missing_frozen_fields_cannot_be_repaired_by_self_rehash(task, group, key):
    snapshot = copy.deepcopy(task.snapshot)
    del snapshot[group][key]
    task.run.input_json = d.canonical_json(snapshot)
    task.db.get(AIDrugLabelRunArtifact, task.run.run_id).input_hash = hashlib.sha256(task.run.input_json.encode()).hexdigest()
    task.db.commit()
    refused(lambda: storage.load_snapshot(task.db, task.run))


@pytest.mark.parametrize("status,counts,attempted", [("failed", (None, None), True), ("failed", (13, None), True), ("cancelled", (13, 7), True), ("cancelled", (None, None), None)])
def test_actual_unsuccessful_receipts_keep_independent_unknown_without_accepted_result(task, status, counts, attempted):
    assert complete(task, status=status, counts=counts, attempted=attempted) is None
    assert storage.load_result(task.db, task.actor, task.run) is None
    receipt = storage.usage_receipt(task.db, storage.load_snapshot(task.db, task.run))
    assert (receipt.input_tokens, receipt.output_tokens, receipt.model_call_attempted) == (*counts, attempted)
    assert task.run.result_json == "{}"


def test_strip_all_json_and_feature_markers_still_classifies_by_current_real_fk(task):
    task.run.feature_key = "generic"
    task.run.input_json = "{}"
    task.run.evidence_json = "[]"
    task.run.context_metadata_json = "{}"
    task.run.result_json = "{}"
    task.db.commit()
    assert storage.is_drug_label_run(task.db, task.run)
    refused(lambda: storage.load_snapshot(task.db, task.run))
    assert not storage.is_drug_label_run(None, SimpleNamespace(run_id=None, feature_key="generic", input_json="{}", result_json="{}"))


@pytest.mark.parametrize("field", ["create_event_id", "receipt_event_id", "accept_event_id"])
def test_specific_audit_is_mandatory_not_other_same_action_or_target(task, field):
    complete(task)
    row = task.db.get(AIDrugLabelRunArtifact, task.run.run_id)
    task.db.query(AIAuditEvent).filter_by(event_id=getattr(row, field)).delete(synchronize_session=False)
    task.db.commit()
    refused(lambda: storage.load_result(task.db, task.actor, task.run))


def test_self_rehash_cannot_change_literal_result_or_server_explanation(task):
    complete(task)
    stored = storage.load_snapshot(task.db, task.run)
    artifact = stored.artifact
    value = d.parse_json(artifact.result_json)
    value["summary"] = "伪造全部字段已核实并可自动改写临床规则。"
    artifact.result_json = d.canonical_json(value)
    artifact.result_bytes = len(artifact.result_json.encode())
    artifact.result_hash = hashlib.sha256(artifact.result_json.encode()).hexdigest()
    task.run.result_json = d.canonical_json(storage.result_pointer(task.run.run_id, artifact.result_hash, artifact.result_bytes))
    receipt = task.db.get(AIAuditEvent, artifact.receipt_event_id)
    body = d.parse_json(receipt.detail_json)
    body["result_hash"] = artifact.result_hash
    receipt.detail_json = d.canonical_json(body)
    task.db.get(AIAuditEvent, artifact.accept_event_id).detail_json = storage.accept_audit_detail(stored)
    task.db.commit()
    refused(lambda: storage.load_result(task.db, task.actor, task.run))


def test_source_withdrawal_blocks_ordinary_but_current_super_explicit_frozen_preserves_result(task):
    expected = complete(task)
    sources.revoke_source(task.db, task.users["super_admin_user"], task.source.snapshot.source_binding_id, {**cas(task.source), "basis_note": NOTE})
    task.db.commit()
    refused(lambda: storage.load_result(task.db, task.actor, task.run))
    assert storage.load_result(task.db, task.users["super_admin_user"], task.run, frozen_audit=True) == expected
    refused(lambda: storage.load_result(task.db, task.actor, task.run, frozen_audit=True), 403)


def test_nonowner_pharmacist_and_demoted_actor_denied_before_private_source_or_task_text(task):
    stranger = User(username="other-pharm-" + str(uuid.uuid4()), user_role="pharmacist")
    task.db.add(stranger)
    task.db.commit()
    refused(lambda: storage.load_result(task.db, stranger, task.run), 403)
    actor_id = task.actor.user_id
    task.db.execute(text("UPDATE hoimsystem_users SET user_role='patient' WHERE user_id=:id"), {"id": actor_id})
    task.db.commit()
    sql = []

    def observe(conn, cursor, statement, parameters, context, many):
        sql.append(statement)

    event.listen(task.db.bind, "before_cursor_execute", observe)
    try:
        refused(lambda: storage.load_result(task.db, task.actor, task.run), 403)
    finally:
        event.remove(task.db.bind, "before_cursor_execute", observe)
    assert not any("snapshot_json" in query or "input_json" in query for query in sql)
    # Internal immutable proof can support a trusted already-claimed usage
    # receipt after lost rights; it does not authorize a public read or call.
    assert storage.load_snapshot(task.db, task.run).public_source == task.public


def test_locator_share_exception_contains_only_opaque_columns_and_gate_first(task):
    statements = []

    def observe(state):
        if state.is_select:
            statements.append(str(state.statement.compile(dialect=mysql.dialect())))

    event.listen(task.db, "do_orm_execute", observe)
    try:
        storage.load_snapshot(task.db, task.run)
    finally:
        event.remove(task.db, "do_orm_execute", observe)
    locator = next(sql for sql in statements if "hoimsystem_ai_drug_label_run_artifact" in sql)
    assert "LOCK IN SHARE MODE" in locator
    assert all(name not in locator for name in ("mapping_seed", "input_hash", "result_json"))
    assert locator.index("source_binding_id") < locator.index("FROM")
    first_full_run = next(i for i, s in enumerate(statements) if "hoimsystem_ai_run.input_json" in s)
    source = next(i for i, s in enumerate(statements) if "hoimsystem_ai_drug_label_source.snapshot_json" in s)
    users = next(i for i, s in enumerate(statements) if "hoimsystem_users.user_role" in s)
    assert users < source < first_full_run


@pytest.mark.parametrize("assignment", ["mapping_seed='" + "ef" * 32 + "'", "created_at='2026-10-22 12:00:00.123456'"])
def test_artifact_trigger_cannot_change_the_staged_seed_or_creation_clock(label_case, assignment):
    case = make_task(label_case, stage=False)
    case.db.commit()
    case.db.execute(
        text(
            "CREATE TRIGGER label_seed_fault AFTER INSERT ON hoimsystem_ai_drug_label_run_artifact BEGIN UPDATE hoimsystem_ai_drug_label_run_artifact SET "
            + assignment
            + " WHERE run_id=NEW.run_id; END"
        )
    )
    case.db.commit()
    try:
        refused(lambda: storage.stage_artifact(case.db, case.run, mapping_seed=case.seed, create_event_id=case.audit.event_id))
        case.db.rollback()
        assert case.db.get(AIDrugLabelRunArtifact, case.run.run_id) is None
    finally:
        case.db.execute(text("DROP TRIGGER label_seed_fault"))
        case.db.commit()


@pytest.mark.parametrize("axis", ["public_context", "tools", "foreign_input", "false_permission", "instructions_digest"])
def test_closed_task_rejects_mixed_modes_permission_and_wrong_digest_after_input_self_rehash(task, axis):
    snapshot = copy.deepcopy(task.snapshot)
    if axis == "public_context":
        snapshot["payload"]["context"]["drug_label_source"] = task.public.model_dump(mode="json")
    elif axis == "tools":
        snapshot["payload"]["tools"] = {"write_catalog": {}}
    elif axis == "foreign_input":
        snapshot["payload"]["input"]["document_original_id"] = task.source.snapshot.original.snapshot.original_id
    elif axis == "false_permission":
        snapshot["provider_snapshot"]["allows_patient_data"] = False
    else:
        metadata = copy.deepcopy(task.metadata)
        metadata["instructions_digest"] = task.run.prompt_hash
        task.run.context_metadata_json = d.canonical_json(metadata)
    task.run.input_json = d.canonical_json(snapshot)
    artifact = task.db.get(AIDrugLabelRunArtifact, task.run.run_id)
    artifact.input_hash = hashlib.sha256(task.run.input_json.encode()).hexdigest()
    artifact.metadata_hash = hashlib.sha256(task.run.context_metadata_json.encode()).hexdigest()
    task.db.commit()
    refused(lambda: storage.load_snapshot(task.db, task.run))


def test_private_seed_and_claim_lease_never_enter_the_authorized_artifact_view(task):
    complete(task)
    stored = storage.authorize_drug_label_run(task.db, task.actor, task.run)
    view = storage.artifact_view(stored)
    assert "mapping_seed" not in view and "accepted_lease" not in view
    assert SEED not in d.canonical_json(view) and task.run.lease_token not in d.canonical_json(view)
    assert view["accepted_at"].endswith(".123456Z")
    assert view["result_hash"] == hashlib.sha256(stored.artifact.result_json.encode()).hexdigest()


@pytest.mark.parametrize("axis", ["nonterminal_pointer", "result_without_pointer", "run_counter", "usage_actor", "usage_lease"])
def test_full_result_receipt_and_pointer_are_independently_bound(task, axis):
    complete(task)
    stored = storage.load_snapshot(task.db, task.run)
    if axis == "nonterminal_pointer":
        task.run.status = "running"
    elif axis == "result_without_pointer":
        task.run.result_json = "{}"
    elif axis == "run_counter":
        task.run.input_tokens += 1
    elif axis == "usage_actor":
        task.db.get(AIAuditEvent, stored.artifact.receipt_event_id).actor_id = task.users["super_admin_user"].user_id
    else:
        audit = task.db.get(AIAuditEvent, stored.artifact.receipt_event_id)
        value = d.parse_json(audit.detail_json)
        value["lease_token"] = str(uuid.uuid4())
        audit.detail_json = d.canonical_json(value)
    task.db.commit()
    refused(lambda: storage.load_result(task.db, task.actor, task.run))


def test_original_task_text_utf8_limit_not_codepoint_or_truncated_parse(task):
    assert storage.text_hash("a" * 65535) == hashlib.sha256(("a" * 65535).encode()).hexdigest()
    for value in ("a" * 65536, "😀" * 16384, "\ud800"):
        with pytest.raises((ValueError, UnicodeError)):
            storage.text_hash(value)
    task.run.input_json = " " * 65536
    task.db.commit()
    refused(lambda: storage.load_snapshot(task.db, task.run))


@pytest.mark.parametrize("axis", ["source", "professional", "role", "signer_role"])
def test_public_source_permission_precedes_every_task_text_even_when_immutable_internal_proof_still_exists(label_case, axis, monkeypatch):
    from app.ai import drug_label_runtime as runtime
    from app.ai.schemas import RunRequest
    from app.config import settings

    monkeypatch.setattr(settings, "AI_PROVIDER_ALLOWED_HOSTS", "synthetic.invalid")
    case = make_task(label_case)
    actor = case.actor
    identifier = case.run.run_id
    if axis == "signer_role":
        actor = case.users["super_admin_user"]
        created = runtime.create_drug_label_run(case.db, actor, RunRequest(feature_key=storage.FEATURE_KEY, input={"drug_label_source_binding_id": case.source.snapshot.source_binding_id}))
        identifier = created.run_id
    if axis == "source":
        sources.revoke_source(case.db, case.users["super_admin_user"], case.source.snapshot.source_binding_id, {**cas(case.source), "basis_note": NOTE})
    elif axis == "professional":
        sources.revoke_professional(case.db, case.actor, case.source.snapshot.source_binding_id, {**cas(case.source.professional_review), "basis_note": NOTE})
    else:
        case.db.query(User).filter_by(user_id=case.actor.user_id).update({"user_role": "patient"}, synchronize_session=False)
    case.db.commit()
    selected = []

    def observe(conn, cursor, statement, parameters, context, many):
        if "hoimsystem_ai_run.input_json" in statement:
            selected.append(statement)

    event.listen(case.db.get_bind(), "before_cursor_execute", observe)
    try:
        with pytest.raises(HTTPException) as denied:
            storage.load_snapshot(case.db, identifier, user=actor)
        assert denied.value.status_code in {403, 409}
        assert selected == []
        case.db.rollback()
        # Trusted terminal accounting retains the complete immutable proof;
        # no current execution authority is conferred by this internal read.
        assert storage.load_snapshot(case.db, identifier).run.run_id == identifier
        assert selected
        case.db.rollback()
        selected.clear()
        frozen = storage.load_snapshot(case.db, identifier, user=case.users["super_admin_user"], frozen_audit=True)
        assert selected and frozen.source_record.audit_only and not frozen.source_record.eligible
    finally:
        event.remove(case.db.get_bind(), "before_cursor_execute", observe)


@pytest.mark.parametrize(
    "raw,expected",
    [('["super_admin"]', 403), ("{invalid-json", 409), ("null", 409), ('"pharmacist"', 409), ("[true]", 409), ("[1]", 409), ('["pharmacist","pharmacist"]', 409), ("[]", 403), (None, 409)],
)
def test_current_feature_role_scope_rejects_cached_revoked_or_broken_configuration_before_task_text_but_frozen_super_bypasses(task, raw, expected):
    db, identifier = task.db, task.run.run_id
    # Populate the old identity-map config deliberately, then mutate SQL only.
    assert db.get(AIFeatureConfig, storage.FEATURE_KEY).allowed_roles_json == '["pharmacist","super_admin"]'
    if raw is None:
        db.query(AIFeatureConfig).filter_by(feature_key=storage.FEATURE_KEY).delete(synchronize_session=False)
    else:
        db.query(AIFeatureConfig).filter_by(feature_key=storage.FEATURE_KEY).update({"allowed_roles_json": raw}, synchronize_session=False)
    db.flush()
    selected = []

    def observe(conn, cursor, statement, parameters, context, many):
        if "hoimsystem_ai_run.input_json" in statement:
            selected.append(statement)

    event.listen(db.get_bind(), "before_cursor_execute", observe)
    try:
        with pytest.raises(HTTPException) as failure:
            storage.load_snapshot(db, identifier, user=task.actor)
        assert failure.value.status_code == expected and selected == []
        internal = storage.load_snapshot(db, identifier)
        assert internal.run.run_id == identifier
        selected.clear()
        frozen = storage.load_snapshot(db, identifier, user=task.users["super_admin_user"], frozen_audit=True)
        assert selected and frozen.source_record.audit_only and not frozen.source_record.eligible
    finally:
        event.remove(db.get_bind(), "before_cursor_execute", observe)
        db.rollback()
