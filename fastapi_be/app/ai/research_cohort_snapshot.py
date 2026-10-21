"""Frozen recorded criteria and per-Case identity minimization.

Neither the public projection nor its SHA is proof of anonymity or authority.
Protected originals remain readable only through current project/patient access.
"""

import hashlib
import hmac
import json
import secrets
from pathlib import Path

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai.research_cohort_collection import MAX_BYTES, verify_capture
from app.ai.research_cohort_contract import SHA, UTC, UUID, Basis, CaptureRequest, Positive, canonical_json
from app.ai.research_cohort_evaluator import evaluate_criteria
from app.ai.research_cohort_sources import hash_content

RULE_ID = "research_recorded_predicates_kleene_v1"


def current_recipe():
    root = Path(__file__).parent
    return {
        "rule_id": RULE_ID,
        "implementation_sha256": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in ("research_cohort_contract.py", "research_cohort_collection.py", "research_cohort_evaluator.py", "research_cohort_snapshot.py")
        },
    }


def opaque(snapshot, namespace, raw):
    return hmac.new(bytes.fromhex(snapshot["identity_secret"]), canonical_json([namespace, raw]).encode("utf-8"), hashlib.sha256).hexdigest()


def make_snapshot(case_id, actor_id, request, captured, basis_note):
    request = request if isinstance(request, CaptureRequest) else CaptureRequest.model_validate(request)
    captured = verify_capture(captured)
    if request.model_dump(exclude={"criteria"}) != captured["request"] or actor_id != captured["actor_id"]:
        raise HTTPException(409, "病例捕获与原项目请求/实际操作者不一致")
    body = {
        "schema_version": "research_cohort_case_v1",
        "case_id": case_id,
        "scope_id": request.scope_id,
        "created_by": actor_id,
        "captured_at": captured["captured_at"],
        "identity_secret": secrets.token_hex(32),
        "creation_basis_note": basis_note,
        "request": request.model_dump(),
        "capture": captured,
        "collection_digest": captured["collection_digest"],
        "scope_binding_hash": hash_content({"scope": captured["scope_original"], "acl": captured["actor_acl"], "patient_authorizations": captured["patient_authorizations"]}),
        "member_manifest_hash": captured["manifest_hash"],
        "recipe": current_recipe(),
        "evaluation": evaluate_criteria(captured, request.criteria),
    }
    if len(canonical_json(body).encode("utf-8")) > MAX_BYTES:
        raise HTTPException(413, "完整研究病例原件超过8MiB，未裁剪证据或成员")
    return verify_snapshot(body)


def verify_snapshot(value, *, validate_current_recipe=True):
    try:
        expected = {
            "schema_version",
            "case_id",
            "scope_id",
            "created_by",
            "captured_at",
            "identity_secret",
            "creation_basis_note",
            "request",
            "capture",
            "collection_digest",
            "scope_binding_hash",
            "member_manifest_hash",
            "recipe",
            "evaluation",
        }
        if type(value) is not dict or set(value) != expected or value["schema_version"] != "research_cohort_case_v1" or len(canonical_json(value).encode("utf-8")) > MAX_BYTES:
            raise ValueError("Closed whole snapshot required")
        for field in ("case_id", "scope_id"):
            TypeAdapter(UUID).validate_python(value[field], strict=True)
        for field in ("identity_secret", "collection_digest", "scope_binding_hash", "member_manifest_hash"):
            TypeAdapter(SHA).validate_python(value[field], strict=True)
        TypeAdapter(Positive).validate_python(value["created_by"], strict=True)
        TypeAdapter(UTC).validate_python(value["captured_at"], strict=True)
        TypeAdapter(Basis).validate_python(value["creation_basis_note"], strict=True)
        request = CaptureRequest.model_validate(value["request"])
        captured = verify_capture(value["capture"])
        if (
            request.model_dump(exclude={"criteria"}) != captured["request"]
            or value["scope_id"] != request.scope_id
            or value["created_by"] != captured["actor_id"]
            or value["captured_at"] != captured["captured_at"]
        ):
            raise ValueError("Complete private identity/request differs")
        if (
            value["collection_digest"] != captured["collection_digest"]
            or value["member_manifest_hash"] != captured["manifest_hash"]
            or value["scope_binding_hash"] != hash_content({"scope": captured["scope_original"], "acl": captured["actor_acl"], "patient_authorizations": captured["patient_authorizations"]})
        ):
            raise ValueError("All original authorization and member anchors differ")
        recipe = value["recipe"]
        if (
            type(recipe) is not dict
            or set(recipe) != {"rule_id", "implementation_sha256"}
            or recipe["rule_id"] != RULE_ID
            or set(recipe["implementation_sha256"]) != set(current_recipe()["implementation_sha256"])
        ):
            raise ValueError("Frozen exact recipe required")
        for digest in recipe["implementation_sha256"].values():
            TypeAdapter(SHA).validate_python(digest, strict=True)
        current = recipe == current_recipe()
        if validate_current_recipe and not current:
            raise ValueError("Current implementation differs from frozen original")
        # An older own original can be integrity-audited without pretending the
        # current evaluator has independently reproduced an old algorithm.
        if current and value["evaluation"] != evaluate_criteria(captured, request.criteria):
            raise ValueError("Deterministic original three-valued evidence differs")
        if not current:
            _closed_evaluation(value["evaluation"], captured)
        return json.loads(canonical_json(value))
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "完整研究病例的原件、逐患者授权或三值证据证明已损坏/版本不匹配") from exc


def _closed_evaluation(value, captured):
    # This branch describes historical own integrity only, not a new execution.
    if type(value) is not dict or set(value) != {"schema_version", "criteria_hash", "outcomes", "limitations"} or value["schema_version"] != "research_recorded_evaluation_v1":
        raise ValueError("Closed frozen evaluation required")
    TypeAdapter(SHA).validate_python(value["criteria_hash"], strict=True)
    if [o["patient_id"] for o in value["outcomes"]] != captured["scope_original"]["payload"]["patient_ids"]:
        raise ValueError("Historical full declared patient set differs")
    for outcome in value["outcomes"]:
        if set(outcome) != {"patient_id", "truth", "interpretation", "leaves"} or outcome["truth"] not in {"true", "false", "unknown"}:
            raise ValueError("Closed own frozen outcome required")


def project_snapshot(snapshot, publication_governance_hash, *, validate_current_recipe=True):
    snapshot = verify_snapshot(snapshot, validate_current_recipe=validate_current_recipe)
    TypeAdapter(SHA).validate_python(publication_governance_hash, strict=True)
    captured = snapshot["capture"]
    manifest = [
        {
            "family": member["family"],
            "patient_token": opaque(snapshot, "patient", member["patient_id"]),
            "record_token": opaque(snapshot, "record", [member["family"], member["record_id"]]),
            "original_hash": opaque(snapshot, "original_hash", member["content_hash"]),
            "parent_binding_hash": opaque(snapshot, "parent_binding_hash", member["parent_binding_hash"]),
            "window_status": member["window_status"],
        }
        for member in captured["member_manifest"]
    ]
    outcomes = []
    for outcome in snapshot["evaluation"]["outcomes"]:
        leaves = []
        for leaf in outcome["leaves"]:
            evidence = []
            for proof in leaf["evidence"]:
                evidence.append(
                    {
                        **{k: v for k, v in proof.items() if k not in {"record_id", "original_hash", "field_hash"}},
                        "record_token": opaque(snapshot, "record", [proof["family"], proof["record_id"]]),
                        "original_hash": opaque(snapshot, "original_hash", proof["original_hash"]),
                        "field_hash": opaque(snapshot, "field_hash", proof["field_hash"]),
                    }
                )
            leaves.append({**{k: v for k, v in leaf.items() if k != "evidence"}, "evidence": evidence})
        outcomes.append({"patient_token": opaque(snapshot, "patient", outcome["patient_id"]), "truth": outcome["truth"], "interpretation": outcome["interpretation"], "leaves": leaves})
    counts = {truth: sum(o["truth"] == truth for o in outcomes) for truth in ("true", "false", "unknown")}
    result = {
        "schema_version": "research_cohort_source_v1",
        "source_id": f"research_cohort:{snapshot['case_id']}:{hash_content(snapshot)[:12]}",
        "content_hash": hash_content(snapshot),
        "governance_hash": publication_governance_hash,
        "captured_at": snapshot["captured_at"],
        "scope_token": opaque(snapshot, "scope", snapshot["scope_id"]),
        "authorization_binding_hash": opaque(snapshot, "authorization_binding", snapshot["scope_binding_hash"]),
        "collection_digest": opaque(snapshot, "collection", snapshot["collection_digest"]),
        "member_manifest": manifest,
        "member_manifest_hash": hash_content(manifest),
        "recipe": snapshot["recipe"],
        "criteria": snapshot["request"]["criteria"],
        "outcomes": outcomes,
        "counts": {"declared_patients": len(outcomes), "recorded_true": counts["true"], "recorded_false": counts["false"], "unknown": counts["unknown"]},
        "limitations": list(snapshot["evaluation"]["limitations"]),
        "privacy_basis": "project_authorized_identifier_minimization_not_anonymity",
        "external_model_use": captured["scope_original"]["payload"]["external_model_use"],
    }
    if len(canonical_json(result).encode("utf-8")) > MAX_BYTES:
        raise HTTPException(413, "完整研究最小化证据投影超过8MiB，未删除不利结果")
    return result
