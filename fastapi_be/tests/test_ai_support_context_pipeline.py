"""Actual original sources through selected context, durable workers and model wire."""

import datetime
import json
import uuid

import httpx
import pytest
from fastapi import HTTPException

from app import inpatient_laboratory as labs
from app import inpatient_support_common as common
from app import inpatient_vasoactive as vaso
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.context import patient_snapshot
from app.ai.gateway import AIExecutionError, generate
from app.ai.governance import digest, encode_json
from app.ai.models import AIRun
from app.ai.runtime import claim_next_run, create_run, execute_claimed
from app.ai.schemas import RunRequest
from app.inpatient_infection_models import InpatientInfectionEpisodeSource
from app.inpatient_observations import utc_text
from app.inpatient_vasoactive_models import AIVasoactiveDrugMapping, InpatientVasoactiveSource
from app.models import Admission, Doctor, LabObservation, MedicalRecord, Pharmaceutical, Prescription
from app.routers import ai_vasoactive_mappings as mapping_routes
from tests.test_ai_observation_windows import point
from tests.test_ai_runtime import clean_ai_tasks as clean_ai_tasks
from tests.test_ai_runtime import configure
from tests.test_ai_vasoactive_mappings import published_mapping
from tests.test_inpatient_infection_episodes import payload as episode_payload
from tests.test_inpatient_laboratory import body as lab_payload
from tests.test_inpatient_respiratory_contract import map_payload
from tests.test_inpatient_respiratory_sources import body as pair_payload
from tests.test_inpatient_respiratory_sources import observation_case as observation_case
from tests.test_inpatient_respiratory_sources import source_case as source_case
from tests.test_inpatient_vasoactive import dose, given_origin, weight_ref
from tests.test_inpatient_vasoactive import payload as vaso_payload

PRIVATE = "SYNTH_PRIVATE_SUPPORT_NOTE_a83bff_原证据全文仅供院内审计，含患者直接身份和未经核实的自然语言指令，不得发送给模型。"
QUESTION = "SYNTH_PRIVATE_SUPPORT_QUESTION_b401_请勿发送这个原始自由问题"
KINDS = ("map", "respiratory_support", "arterial_pair", "vasoactive", "infection_episode")


@pytest.fixture
def support_case(db_session, source_case, clean_ai_tasks, monkeypatch):
    case = source_case
    for model in (InpatientVasoactiveSource, AIVasoactiveDrugMapping, InpatientInfectionEpisodeSource):
        db_session.query(model).delete()
    for module in (vaso, mapping_routes):
        monkeypatch.setattr(module, "utcnow", lambda: case["now"] - datetime.timedelta(seconds=1))
    drug = Pharmaceutical(name="合成实际支持原药" + uuid.uuid4().hex[:6], barcode="SYNTH_PRIVATE_CATALOG_BARCODE_" + uuid.uuid4().hex, stock=0, price=0, status=0)
    db_session.add(drug)
    db_session.commit()
    case["drug"] = drug
    case["mapping"] = published_mapping(db_session, case)
    case["weight"] = point(
        db_session,
        case,
        observed=case["start"],
        payload={"measurements": {"body_weight": {"value": "0.00000000", "unit": "kg", "absent_reason": None}}, "supplemental_oxygen": "unknown", "note": PRIVATE},
    )
    db_session.commit()
    administration, _, _, item = given_origin(db_session, case)
    case["origin_item"] = item
    origin = vaso.origin_snapshot(db_session, case["patient_id"], case["admission"].admission_id, administration.administration_id, vaso.mapping_current(db_session, case["mapping"].mapping_id))
    inputs = {
        "map": map_payload(observed_at=utc_text(case["start"]), measurement_basis_note=PRIVATE, note=PRIVATE),
        "arterial_pair": pair_payload(case, review_note=PRIVATE, note=PRIVATE),
        "vasoactive": vaso_payload(
            case,
            origin={"administration_id": administration.administration_id, "expected_content_hash": origin["content_hash"]},
            dose_input=dose("pump", None, weight_ref=weight_ref(case), confirmed=True),
            note=PRIVATE,
        ),
        "infection_episode": episode_payload(
            case,
            infection_basis_note=PRIVATE,
            onset_basis_note=PRIVATE,
            note=PRIVATE,
            evidence_refs=[{"kind": "lab_source", "source_id": case["lab"].lab_source_id, "expected_content_hash": case["lab"].content_hash}],
        ),
    }
    case["sources"] = {"respiratory_support": case["support"]}
    for kind, values in inputs.items():
        row = common.create_source(db_session, case["doctor"], kind, {"patient_id": case["patient_id"], "admission_id": case["admission"].admission_id, "payload": values})
        db_session.commit()
        case["sources"][kind] = row
    case["provider"], case["feature"] = configure(db_session, case["seed"], "handover_summary")
    return case


def request_for(case, kind="map"):
    return RunRequest(
        feature_key="handover_summary",
        patient_id=case["patient_id"],
        encounter_ref=case["admission"].admission_id,
        input={"support_source_kind": kind, "support_source_id": case["sources"][kind].support_source_id, "question": QUESTION},
    )


def task_from_wire(kind, value):
    if kind == "chat":
        return json.loads(value["messages"][-1]["content"])
    if kind == "responses":
        return json.loads(value["input"][0]["content"])
    return value["input"]


def wire_transport(case, calls, *, before=None):
    def handle(request):
        value = json.loads(request.content)
        calls.append(value)
        if before:
            before()
        task = task_from_wire(case["provider"].kind, value)
        identifier = task["context"]["support_source"]["source_id"]
        result = {
            "summary": "仅整理所选原始资料，供人工核实",
            "sections": [{"title": "所选原资料", "content": "保留原数量和未知状态；未计算完整评分或概率。", "source_ids": [identifier]}],
            "warnings": ["仅所选一条原资料及明确关联，不能代表完整交班或诊断"],
            "missing_data": ["未提供完整24小时多器官原事实及独立临床核实"],
        }
        kind = case["provider"].kind
        if kind == "chat":
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": encode_json(result)}}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}})
        if kind == "responses":
            return httpx.Response(
                200, json={"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": encode_json(result)}]}], "usage": {"input_tokens": 3, "output_tokens": 4}}
            )
        return httpx.Response(200, json={"schema_version": "1", "feature_key": "handover_summary", "model_version": case["provider"].model, "applicable": True, "result": result})

    return httpx.MockTransport(handle)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("protocol", ["chat", "responses"])
async def test_actual_original_context_queue_wire_and_stored_result_exclude_private_provenance(kind, protocol, async_client, auth_headers, db_session, support_case):
    case = support_case
    case["provider"].kind = protocol
    db_session.commit()
    request = request_for(case, kind)
    before = {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription)}
    response = await async_client.post(
        "/api/ai/context",
        headers=auth_headers(case["doctor"].username),
        json={
            "feature_key": request.feature_key,
            "patient_id": request.patient_id,
            "encounter_ref": request.encounter_ref,
            "source_refs": {key: value for key, value in request.input.items() if key != "question"},
        },
    )
    assert response.status_code == 200, response.text
    context = response.json()["data"]["context"]
    original = common.source_current(db_session, case["sources"][kind], kind)
    assert context["scope"] == "inpatient_support_original"
    assert context["support_source_provenance"] == original
    public = context["support_source"]
    assert context["support_public_hash"] == vaso.hash_content(public)
    assert public["source_id"] == original["source_id"] and public["content_hash"] == original["content_hash"]
    assert public["kind"] == kind and public["historical_prediction"] is False
    for flag in ("quantity_conversion_performed", "sofa_provided", "diagnosis_provided", "probability_provided", "complete_handover_provided"):
        assert public[flag] is False
    assert "patient_id" not in encode_json(public) and "admission_id" not in encode_json(public) and PRIVATE not in encode_json(public)
    if kind == "map":
        assert public["facts"]["map"]["value"] == "0.00000000"
    if kind == "vasoactive":
        assert public["facts"]["dose_input"]["pump_rate"]["value"] is None
        assert public["reference_facts"]["weight"]["measurement"]["value"] == "0.00000000"
        assert original["reference_snapshots"]["origin"]["administration"]["administration_time"] == "2020-01-02T03:04:05.123456"
    if kind == "infection_episode":
        assert public["event_at"] is None and public["facts"]["onset_at"] is None
    run = create_run(db_session, case["doctor"], request)
    frozen = json.loads(run.input_json)["payload"]["context"]
    assert frozen["support_source_provenance"] == original
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=wire_transport(case, calls))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "succeeded", stored.error_message
    assert len(calls) == 1
    task = task_from_wire(protocol, calls[0])
    assert task["context"]["support_source"] == public
    wire = encode_json(task)
    for marker in (
        PRIVATE,
        QUESTION,
        case["drug"].barcode,
        "patient_barcode",
        "medication_barcodes_json",
        "support_source_provenance",
        "patient_id",
        "admission_id",
        "original_drug_identity",
        "author_qualification",
    ):
        assert marker not in wire
    detail = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["requires_human_review"] is True
    assert data["result"]["summary"] == "仅整理所选原始资料，供人工核实"
    assert not {"qsofa_analysis", "news2_analysis", "aki_analysis", "probability"} & data["result"].keys()
    assert data["support_findings"] == {key: frozen[key] for key in ("support_source", "support_source_provenance", "support_public_hash")}
    assert "critical_value_workflow" not in data["tool_findings"]
    assert before == {model.__tablename__: db_session.query(model).count() for model in (Admission, MedicalRecord, Prescription)}


CHANGES = (
    ("map", "source_revoke"),
    ("map", "care"),
    ("infection_episode", "doctor_identity"),
    ("infection_episode", "hidden_source_note"),
    ("infection_episode", "lab_parent"),
    ("arterial_pair", "support_revoke"),
    ("arterial_pair", "fio2_note"),
    ("vasoactive", "mapping_revoke"),
    ("vasoactive", "origin_item"),
    ("vasoactive", "weight_note"),
)


def mutate(db, case, kind, change):
    if change in {"source_revoke", "support_revoke"}:
        row = case["sources"][kind] if change == "source_revoke" else case["support"]
        row.status, row.revision = "revoked", 2
        row.revoked_at, row.revoked_by, row.revoke_reason = case["now"], case["seed"]["super_admin_user"].user_id, PRIVATE
    elif change == "care":
        case["admission"].doctor_id = None
    elif change == "doctor_identity":
        db.get(Doctor, case["seed"]["doctor"].doctor_id).user_id = case["seed"]["nurse_user"].user_id
    elif change in {"hidden_source_note", "fio2_note", "weight_note"}:
        row = case["sources"][kind] if change == "hidden_source_note" else case["fio2"] if change == "fio2_note" else case["weight"]
        data = json.loads(row.payload_json)
        data["note"] = PRIVATE + "正文在排队后变化"
        row.payload_json = vaso.canonical_json(data)
    elif change == "lab_parent":
        case["lab_report"].result += PRIVATE
    elif change == "mapping_revoke":
        mapping_routes.revoke_mapping(case["mapping"].mapping_id, mapping_routes.MappingRevoke(expected_revision=2, reason=PRIVATE), db, case["seed"]["super_admin_user"])
    elif change == "origin_item":
        case["origin_item"].dose += PRIVATE
    else:
        raise AssertionError(change)
    db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["queued", "inflight", "history"])
@pytest.mark.parametrize("kind,change", CHANGES)
async def test_changed_selected_source_dependency_qualification_or_care_stops_queue_reply_and_current_history(kind, change, phase, async_client, auth_headers, db_session, support_case):
    case = support_case
    run = create_run(db_session, case["doctor"], request_for(case, kind))
    frozen = json.loads(run.input_json)["payload"]["context"]
    if phase == "queued":
        mutate(db_session, case, kind, change)
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=wire_transport(case, calls, before=(lambda: mutate(db_session, case, kind, change)) if phase == "inflight" else None))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    if phase != "history":
        assert stored.status == "failed" and stored.result_json == "{}"
        assert len(calls) == (0 if phase == "queued" else 1)
        return
    assert stored.status == "succeeded", stored.error_message
    mutate(db_session, case, kind, change)
    denied = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["doctor"].username))
    assert denied.status_code == 403, denied.text
    audit = await async_client.get(f"/api/ai/runs/{run.run_id}", headers=auth_headers(case["seed"]["super_admin_user"].username))
    assert audit.status_code == 200, audit.text
    assert audit.json()["data"]["support_findings"] == {key: frozen[key] for key in ("support_source", "support_source_provenance", "support_public_hash")}
    assert json.loads(db_session.get(AIRun, run.run_id).input_json)["payload"]["context"] == frozen


@pytest.mark.parametrize("feature", ["patient_summary", "deterioration_risk", "sepsis_risk", "aki_risk"])
def test_selected_support_original_is_exclusive_to_handover(feature, db_session, support_case):
    case = support_case
    request = request_for(case)
    with pytest.raises(HTTPException) as caught:
        patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY[feature], request.patient_id, request.encounter_ref, request.input)
    assert caught.value.status_code == 422


@pytest.mark.parametrize("change", ["missing_kind", "missing_id", "unknown_kind", "other_admission", "extra_original", "question_bool"])
def test_explicit_kind_and_id_cannot_be_guessed_rebound_or_overridden(change, db_session, support_case):
    case = support_case
    request = request_for(case)
    if change == "missing_kind":
        request.input.pop("support_source_kind")
    elif change == "missing_id":
        request.input.pop("support_source_id")
    elif change == "unknown_kind":
        request.input["support_source_kind"] = "hoimsystem_patient"
    elif change == "other_admission":
        request.encounter_ref = case["other"].admission_id
    elif change == "extra_original":
        request.input["source_override"] = {"map": "80"}
    else:
        request.input["question"] = True
    with pytest.raises(HTTPException) as caught:
        create_run(db_session, case["doctor"], request)
    assert caught.value.status_code in {409, 422}


@pytest.mark.asyncio
async def test_specialist_cannot_bypass_text_protocol_gate_or_send_private_originals(db_session, support_case):
    case = support_case
    request = request_for(case, "vasoactive")
    bundle = patient_snapshot(db_session, case["doctor"], FEATURE_BY_KEY["handover_summary"], request.patient_id, request.encounter_ref, request.input)
    case["provider"].kind = "specialist"
    db_session.commit()
    with pytest.raises(HTTPException) as caught:
        create_run(db_session, case["doctor"], request)
    assert caught.value.status_code == 409
    calls = []
    with pytest.raises(AIExecutionError) as caught:
        await generate(
            case["provider"],
            FEATURE_BY_KEY["handover_summary"],
            "原支持资料仅供人工核实，不生成评分、诊断或概率",
            {"input": request.input, "context": bundle.data, "tools": {}, "evidence": bundle.evidence},
            transport=wire_transport(case, calls),
        )
    assert caught.value.code == "SUPPORT_TEXT_ADAPTER_REQUIRED" and calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["public_quantity", "public_hash", "selected_id", "private_body", "scope", "missing_data", "wire_evidence"])
async def test_stored_public_private_or_reference_tampering_never_reaches_model(change, db_session, support_case):
    case = support_case
    run = create_run(db_session, case["doctor"], request_for(case, "map"))
    value = json.loads(run.input_json)
    context = value["payload"]["context"]
    if change == "public_quantity":
        context["support_source"]["facts"]["map"]["value"] = "99"
    elif change == "public_hash":
        context["support_public_hash"] = "0" * 64
    elif change == "selected_id":
        context["selected_sources"]["support_source_id"] = str(uuid.uuid4())
    elif change == "private_body":
        context["support_source_provenance"]["payload"]["note"] += PRIVATE
    elif change == "scope":
        context["scope"] = PRIVATE
    elif change == "missing_data":
        context["missing_data"].append(PRIVATE)
    else:
        value["payload"]["evidence"][0]["content"] = PRIVATE
    # Even a recomputed outer snapshot digest cannot bypass the real original binding.
    run.input_json = encode_json(value)
    run.context_digest = digest(context)
    db_session.commit()
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=wire_transport(case, calls))
    db_session.expire_all()
    stored = db_session.get(AIRun, run.run_id)
    assert stored.status == "failed" and stored.result_json == "{}" and calls == []


@pytest.mark.asyncio
async def test_unbound_extra_knowledge_key_is_removed_from_actual_outbound_payload(db_session, support_case):
    case = support_case
    run = create_run(db_session, case["doctor"], request_for(case, "map"))
    value = json.loads(run.input_json)
    value["payload"]["knowledge"] = [PRIVATE]
    run.input_json = encode_json(value)
    db_session.commit()
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=wire_transport(case, calls))
    db_session.expire_all()
    assert db_session.get(AIRun, run.run_id).status == "succeeded"
    assert len(calls) == 1 and PRIVATE not in encode_json(task_from_wire("chat", calls[0]))
    assert "knowledge" not in task_from_wire("chat", calls[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", KINDS)
async def test_fixed_kind_equal_to_patient_name_is_preserved_during_identifier_minimization(kind, db_session, support_case):
    case = support_case
    case["seed"]["patient"].name = kind
    db_session.commit()
    run = create_run(db_session, case["doctor"], request_for(case, kind))
    assert json.loads(run.input_json)["payload"]["input"]["support_source_kind"] == kind
    calls = []
    await execute_claimed(*claim_next_run(db_session), transport=wire_transport(case, calls))
    db_session.expire_all()
    assert db_session.get(AIRun, run.run_id).status == "succeeded"
    assert task_from_wire("chat", calls[0])["context"]["support_source"]["kind"] == kind


@pytest.mark.parametrize("sampling_earlier", [False, True])
@pytest.mark.parametrize("cutoff_microseconds", [-1, 0])
def test_actual_infection_cannot_retroactively_use_later_registered_or_available_lab(sampling_earlier, cutoff_microseconds, db_session, support_case, monkeypatch):
    case = support_case
    registered = case["now"] + datetime.timedelta(microseconds=2)
    collected = registered - datetime.timedelta(hours=1) if sampling_earlier else registered
    monkeypatch.setattr(labs, "utcnow", lambda: registered)
    original = case["lab_observation"]
    observation = LabObservation(
        **{column.name: getattr(original, column.name) for column in original.__table__.columns if column.name not in {"observation_id", "collected_at"}},
        observation_id="cutoff-" + uuid.uuid4().hex[:20],
        collected_at=original.collected_at + datetime.timedelta(microseconds=1),
    )
    db_session.add(observation)
    db_session.commit()
    lab_case = {
        "patient_id": case["patient_id"],
        "admission_id": case["admission"].admission_id,
        "observation": observation,
        "mapping": json.loads(case["lab"].snapshot_json)["mapping"],
    }
    laboratory = labs.create_source(db_session, case["doctor"], lab_payload(db_session, lab_case, collected_at_utc=utc_text(collected)))
    db_session.commit()
    actual = labs.source_current(db_session, laboratory)
    assert actual["collected_at_utc"] == utc_text(collected)
    assert actual["registered_at"] == actual["available_at"] == utc_text(registered)
    cutoff = registered + datetime.timedelta(microseconds=cutoff_microseconds)
    monkeypatch.setattr(common, "utcnow", lambda: cutoff)
    values = {
        "patient_id": case["patient_id"],
        "admission_id": case["admission"].admission_id,
        "payload": episode_payload(case, evidence_refs=[{"kind": "lab_source", "source_id": laboratory.lab_source_id, "expected_content_hash": laboratory.content_hash}]),
    }
    count = db_session.query(InpatientInfectionEpisodeSource).count()
    if cutoff_microseconds < 0:
        with pytest.raises(HTTPException) as denied:
            common.create_source(db_session, case["doctor"], "infection_episode", values)
        assert denied.value.status_code == 409
        assert db_session.query(InpatientInfectionEpisodeSource).count() == count
    else:
        row = common.create_source(db_session, case["doctor"], "infection_episode", values)
        db_session.commit()
        current = common.source_current(db_session, row, "infection_episode")
        assert current["reference_snapshots"]["evidence"] == [actual]
        assert current["recorded_at"] == actual["registered_at"] == actual["available_at"]
