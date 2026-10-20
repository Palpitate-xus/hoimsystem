"""Whole private surgery captures and deterministic public scenario projections.

Only the SQL collection service grants current authority. These functions verify
the captured bytes, retain every reviewed root and never infer missing facts.
"""

import copy
import uuid
from typing import Literal

from pydantic import Field

from app.ai.surgery_collection import CaptureRequest
from app.ai.surgery_contract import (
    INPUT_POLICY,
    MAX_BYTES,
    RECIPE,
    RULE_ID,
    SHA256,
    UUID,
    FactKind,
    FactRef,
    StrictModel,
    SurgerySource,
    UtcText,
    canonical_json,
    hash_content,
    input_policy_digest,
    recipe_digest,
)
from app.ai.surgery_projection import PublicIdentity, new_identity_secret, project_case, project_resource, public_fact, public_operational_fact, verified_original, verified_safe_resource
from app.ai.surgery_scenario_input import ScenarioCreate, period_for

DIGEST_FIELDS = ("case_collection_digest", "resource_collection_digest", "busy_collection_digest", "fact_collection_digest", "private_manifest_digest")
COLLECTION_FIELDS = {
    "schema_version",
    "request",
    "pool",
    "period",
    "as_of",
    "captured_at",
    "cases",
    "resources",
    "registry_manifest",
    "source_records",
    "member_manifest",
    "known_gaps",
    "max_available_at",
    "collection_digest",
    *DIGEST_FIELDS,
}


class SourceMetadata(StrictModel):
    source_record_id: UUID
    source_kind: FactKind
    source_id: str
    content_hash: SHA256
    governance_hash: SHA256
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: int = Field(ge=1, le=3)
    recorded_at: UtcText
    reviewed_at: UtcText | None
    revoked_at: UtcText | None
    resource_id: UUID | None
    application_id: UUID | None
    eligible_for_new_use: bool
    exclusion_reasons: list[str]


class CaseMetadata(StrictModel):
    application_id: UUID
    patient_id: int = Field(ge=1, le=2147483647)
    admission_id: UUID | None
    doctor_id: int = Field(ge=1, le=2147483647)
    department_id: int = Field(ge=1, le=2147483647)
    status: int
    admission_status: int | None
    admission_doctor_id: int | None = Field(ge=1, le=2147483647)
    clinical_content_hash: SHA256


class RegistryMetadata(StrictModel):
    registry_kind: Literal["pool", "resource", "pool_membership", "person_account", "room_alias"]
    registry_record_id: UUID
    content_hash: SHA256
    governance_hash: SHA256 | None
    status: Literal["draft", "published", "rejected", "revoked"] | None
    revision: int | None = Field(ge=1, le=3)
    recorded_at: UtcText
    reviewed_at: UtcText | None
    revoked_at: UtcText | None
    eligible_for_new_use: bool
    exclusion_reasons: list[str]
    identity_state_hash: SHA256 | None = None


class PrivateSnapshot(StrictModel):
    schema_version: Literal["surgery_scenario_private_v1"]
    scenario_id: UUID
    pool_id: UUID
    department_id: int = Field(ge=1, le=2147483647)
    created_by: int = Field(ge=1, le=2147483647)
    as_of: UtcText
    captured_at: UtcText
    collection_digest: SHA256
    scope_token: UUID
    identity_secret: str = Field(pattern=r"^[a-f0-9]{64}$")
    rule_profile: dict
    request: ScenarioCreate
    collection: dict


def bounded_json(value):
    serialized = canonical_json(value)
    if not 0 < len(serialized.encode("utf-8")) <= MAX_BYTES:
        raise ValueError("Complete surgery snapshot or public projection exceeds 8MiB; no truncation")
    return serialized


def capture_request(request):
    request = ScenarioCreate.model_validate(request.model_dump(mode="json") if isinstance(request, ScenarioCreate) else request)
    return CaptureRequest(pool_id=request.pool_id, period=request.period, application_ids=sorted(case.application_id for case in request.cases))


def _check_collection(collection):
    bounded_json(collection)
    if type(collection) is not dict or set(collection) != COLLECTION_FIELDS or collection["schema_version"] != "surgery_capture_v1":
        raise ValueError("Complete private capture has a different closed schema")
    request = CaptureRequest.model_validate(collection["request"])
    if collection["period"] != period_for(request.period).model_dump(mode="json") or collection["as_of"] != request.period.as_of:
        raise ValueError("Original capture period differs")
    if collection["captured_at"] < collection["as_of"] or collection["max_available_at"] > collection["as_of"]:
        raise ValueError("Capture cannot backdate related originals or governance")
    if set(collection["pool"]) != {"pool_id", "department_id", "content_hash", "governance_hash"} or collection["pool"]["pool_id"] != request.pool_id:
        raise ValueError("Original pool differs from the explicit cohort")
    cases = {item.application_id: item for item in (CaseMetadata.model_validate(raw) for raw in collection["cases"])}
    if (
        [item["application_id"] for item in collection["cases"]] != request.application_ids
        or len(cases) != len(collection["cases"])
        or any(item.department_id != collection["pool"]["department_id"] for item in cases.values())
    ):
        raise ValueError("Complete actual case cohort differs")
    registry = {}
    registry_order = []
    for raw in collection["registry_manifest"]:
        item = RegistryMetadata.model_validate(raw)
        key = item.registry_kind, item.registry_record_id
        if key in registry or item.model_dump(mode="json", exclude_unset=True) != raw:
            raise ValueError("Original registry manifest must be typed, unique and exact")
        if item.registry_kind != "person_account" and "identity_state_hash" in raw or item.registry_kind == "person_account" and item.identity_state_hash is None:
            raise ValueError("Only actual person accounts have an explicit current identity-state commitment")
        registry[key] = item
        registry_order.append(key)
    if registry_order != sorted(registry_order):
        raise ValueError("Original registry manifest must be canonical")
    pool = registry.get(("pool", request.pool_id))
    if (
        pool is None
        or pool.content_hash != collection["pool"]["content_hash"]
        or pool.governance_hash != collection["pool"]["governance_hash"]
        or not pool.eligible_for_new_use
        or pool.status != "published"
        or pool.exclusion_reasons
    ):
        raise ValueError("Actual original pool is missing from the complete registry manifest")
    resources = collection["resources"]
    if [item["resource_id"] for item in resources] != sorted({item["resource_id"] for item in resources}):
        raise ValueError("Complete physical resources must be unique and canonical")
    for item in resources:
        if hash_content(item["original"]) != item["content_hash"] or hash_content(item["membership"]["original"]) != item["membership"]["content_hash"]:
            raise ValueError("Full captured resource or membership original differs")
        if (
            item["original"]["registry_kind"] != "resource"
            or item["original"]["resource_id"] != item["resource_id"]
            or item["original"]["resource_kind"] != item["resource_kind"]
            or item["membership"]["original"]["registry_kind"] != "pool_membership"
            or item["membership"]["original"]["membership_id"] != item["membership"]["membership_id"]
            or item["membership"]["original"]["resource_id"] != item["resource_id"]
            or item["membership"]["original"]["pool_id"] != request.pool_id
        ):
            raise ValueError("Physical identity or original pool membership differs")
        resource = registry.get(("resource", item["resource_id"]))
        membership = registry.get(("pool_membership", item["membership"]["membership_id"]))
        if (
            resource is None
            or resource.content_hash != item["content_hash"]
            or not resource.eligible_for_new_use
            or resource.exclusion_reasons
            or membership is None
            or membership.content_hash != item["membership"]["content_hash"]
            or membership.governance_hash != item["membership"]["governance_hash"]
            or not membership.eligible_for_new_use
            or membership.status != "published"
            or membership.exclusion_reasons
        ):
            raise ValueError("Full resource and membership originals require their matching current registry roots")
    records = collection["source_records"]
    metadata = [SourceMetadata.model_validate(item["metadata"]).model_dump(mode="json") for item in records]
    if [item["source_record_id"] for item in metadata] != sorted({item["source_record_id"] for item in metadata}) or metadata != collection["member_manifest"]:
        raise ValueError("Every original source root requires its complete canonical metadata")
    for record, meta in zip(records, metadata, strict=True):
        if set(record) != {"representation", "metadata", "original", "governance", "capsule"}:
            raise ValueError("Source record has a different complete representation")
        if meta["source_id"] != f"surgery_fact:{meta['source_record_id']}:{meta['content_hash'][:12]}":
            raise ValueError("Source original identity differs")
        if record["representation"] == "authorized_case_original":
            if record["capsule"] is not None or meta["resource_id"] is not None or meta["application_id"] not in request.application_ids:
                raise ValueError("Case record cannot restore a foreign subject or operational capsule")
            original = record["original"]
            if original is None:
                if meta["eligible_for_new_use"] or record["governance"] is not None:
                    raise ValueError("An eligible case cannot conceal its original")
            else:
                parsed = verified_original(original)
                if any(getattr(parsed, key) != value for key, value in meta.items()) or hash_content(record["governance"]) != meta["governance_hash"]:
                    raise ValueError("Captured actual case original or governance differs from metadata")
                parent = parsed.parent_binding.case
                actual = cases[meta["application_id"]]
                if parent is None or any(getattr(actual, key) != getattr(parent, key) for key in parent.__class__.model_fields):
                    raise ValueError("Full case original differs from the actual captured clinical parent")
        elif record["representation"] == "safe_resource_original":
            capsule = verified_safe_resource(record["capsule"])
            if record["original"] is not None or record["governance"] is not None or meta["application_id"] is not None or meta["resource_id"] not in {item["resource_id"] for item in resources}:
                raise ValueError("Operational record cannot restore foreign raw originals")
            for key in ("source_record_id", "source_kind", "resource_id", "status", "revision", "recorded_at", "reviewed_at", "eligible_for_new_use", "exclusion_reasons"):
                if getattr(capsule, key) != meta[key]:
                    raise ValueError("Safe capsule differs from complete captured metadata")
            if capsule.source_content_hash != meta["content_hash"] or capsule.source_governance_hash != meta["governance_hash"]:
                raise ValueError("Operational original anchors differ")
        else:
            raise ValueError("Unsupported source representation")
    expected = {
        "case_collection_digest": hash_content(collection["cases"]),
        "resource_collection_digest": hash_content({"resources": resources, "registry_manifest": collection["registry_manifest"]}),
        "busy_collection_digest": hash_content({"gaps": collection["known_gaps"], "sources": [item for item in records if item["metadata"]["source_kind"] == "resource_availability_busy"]}),
        "fact_collection_digest": hash_content(records),
        "private_manifest_digest": hash_content(metadata),
    }
    clocks = [
        getattr(item, name)
        for item in [*registry.values(), *(SourceMetadata.model_validate(raw) for raw in metadata)]
        for name in ("recorded_at", "reviewed_at", "revoked_at")
        if getattr(item, name) is not None
    ]
    if not clocks or collection["max_available_at"] != max(clocks):
        raise ValueError("The original maximum availability clock must come from every complete related root")
    if any(collection[key] != value for key, value in expected.items()) or collection["collection_digest"] != hash_content(
        {key: value for key, value in collection.items() if key not in {"captured_at", "collection_digest"}}
    ):
        raise ValueError("Complete actual collection digests differ")
    return request


def _check_selections(request, collection):
    members = {item.source_record_id: item for item in request.members}
    records = {item["metadata"]["source_record_id"]: item for item in collection["source_records"]}
    if set(members) != set(records):
        raise ValueError("Every captured root requires one explicit whole-original review")
    for key, record in records.items():
        meta, member = record["metadata"], members[key]
        if member.source_kind != meta["source_kind"] or member.expected_content_hash != meta["content_hash"] or member.expected_governance_hash != meta["governance_hash"]:
            raise ValueError("Selected source original or governance differs")
        if member.selection == "confirmed" and (not meta["eligible_for_new_use"] or meta["status"] != "published" or meta["exclusion_reasons"]):
            raise ValueError("Review cannot restore an ineligible captured original")
    declarations = {item.resource_id: item for item in request.resources}
    actual = {item["resource_id"]: item for item in collection["resources"]}
    if set(declarations) != set(actual):
        raise ValueError("Every physical pool resource needs its whole declaration, including unselected resources")
    for key, original in actual.items():
        declaration, membership = declarations[key], original["membership"]
        if (
            declaration.expected_resource_hash != original["content_hash"]
            or declaration.expected_membership_id != membership["membership_id"]
            or declaration.expected_membership_hash != membership["content_hash"]
            or declaration.expected_membership_governance_hash != membership["governance_hash"]
        ):
            raise ValueError("Declared resource or whole actual membership changed")
    if request.person_partition.resource_ids != sorted(key for key, item in actual.items() if item["resource_kind"] == "person"):
        raise ValueError("Person distinction review must cover the exact entire actual cohort")
    return members, records


def build_snapshot(request, collection, *, scenario_id, created_by):
    request = ScenarioCreate.model_validate(request.model_dump(mode="json") if isinstance(request, ScenarioCreate) else request)
    _check_collection(collection)
    if capture_request(request).model_dump(mode="json") != collection["request"] or request.expected_capture_digest != collection["collection_digest"]:
        raise ValueError("Original request and complete current preview differ")
    _check_selections(request, collection)
    profile = {
        "schema_version": "surgery_rule_profile_v1",
        "profile_token": str(uuid.uuid4()),
        "rule_id": RULE_ID,
        "rule_version": "1",
        "recipe": copy.deepcopy(RECIPE),
        "recipe_hash": recipe_digest(),
        "input_policy": copy.deepcopy(INPUT_POLICY),
        "input_policy_hash": input_policy_digest(),
    }
    snapshot = PrivateSnapshot(
        schema_version="surgery_scenario_private_v1",
        scenario_id=scenario_id,
        pool_id=request.pool_id,
        department_id=collection["pool"]["department_id"],
        created_by=created_by,
        as_of=collection["as_of"],
        captured_at=collection["captured_at"],
        collection_digest=collection["collection_digest"],
        scope_token=str(uuid.uuid4()),
        identity_secret=new_identity_secret(),
        rule_profile=profile,
        request=request,
        collection=copy.deepcopy(collection),
    ).model_dump(mode="json")
    verify_snapshot(snapshot, validate_current_recipe=True)
    return snapshot


def verify_snapshot(value, *, validate_current_recipe=False):
    bounded_json(value)
    snapshot = PrivateSnapshot.model_validate(value)
    if snapshot.model_dump(mode="json") != value:
        raise ValueError("Private snapshot must preserve exact original JSON scalar types")
    request = _check_collection(snapshot.collection)
    if (
        request.model_dump(mode="json") != capture_request(snapshot.request).model_dump(mode="json")
        or snapshot.request.expected_capture_digest != snapshot.collection_digest
        or snapshot.collection_digest != snapshot.collection["collection_digest"]
        or snapshot.pool_id != request.pool_id
        or snapshot.department_id != snapshot.collection["pool"]["department_id"]
        or snapshot.as_of != snapshot.collection["as_of"]
        or snapshot.captured_at != snapshot.collection["captured_at"]
    ):
        raise ValueError("Immutable scenario identity and original collection differ")
    _check_selections(snapshot.request, snapshot.collection)
    profile = snapshot.rule_profile
    if (
        set(profile) != {"schema_version", "profile_token", "rule_id", "rule_version", "recipe", "recipe_hash", "input_policy", "input_policy_hash"}
        or profile["schema_version"] != "surgery_rule_profile_v1"
        or profile["rule_id"] != RULE_ID
        or profile["rule_version"] != "1"
    ):
        raise ValueError("Unsupported original rule profile")
    from app.ai.surgery_contract import identity

    identity(profile["profile_token"])
    if hash_content(profile["recipe"]) != profile["recipe_hash"] or hash_content(profile["input_policy"]) != profile["input_policy_hash"]:
        raise ValueError("Full frozen rule profile differs from its original recipe or policy hashes")
    if validate_current_recipe and (profile["recipe_hash"] != recipe_digest() or profile["input_policy_hash"] != input_policy_digest()):
        raise ValueError("Original recipe or policy differs from the currently executable version")
    return snapshot


def _technical_fact(meta, member, identities):
    if member.selection == "confirmed":
        raise ValueError("An undisclosed original cannot become a confirmed public fact object")
    return FactRef(
        fact_id=identities.uuid("fact", meta["source_record_id"]),
        kind=meta["source_kind"],
        content_hash=meta["content_hash"],
        governance_hash=meta["governance_hash"],
        recorded_at=meta["recorded_at"],
        published_at=meta["reviewed_at"] if meta["status"] == "published" or meta["status"] == "revoked" and meta["revision"] == 3 else None,
        status=meta["status"],
        revision=meta["revision"],
        review=member.selection,
        review_basis_hash=identities.basis(member.basis_note),
    )


def project_snapshot(value, governance_hash, *, validate_current_recipe=True):
    """Return native source and local technical issues; no raw issue text is sent."""
    snapshot = verify_snapshot(value, validate_current_recipe=validate_current_recipe)
    request, collection = snapshot.request, snapshot.collection
    identities = PublicIdentity(snapshot.identity_secret)
    members, records = _check_selections(request, collection)
    manifest, issues = [], []
    for key, record in records.items():
        if record["capsule"] is not None:
            fact = public_operational_fact(record["capsule"], members[key], identities, snapshot.as_of)
        elif record["original"] is not None:
            fact = public_fact(record["original"], members[key], identities, snapshot.as_of)
        else:
            fact = _technical_fact(record["metadata"], members[key], identities)
        manifest.append(fact.model_dump(mode="json"))
    manifest.sort(key=lambda item: item["fact_id"])
    projected = {key: [] for key in ("resources", "busy_intervals", "duties", "transition_policies", "work_policies", "cases")}
    declarations = {item.resource_id: item for item in request.resources}
    for resource in collection["resources"]:
        key = resource["resource_id"]
        result = project_resource(
            resource_id=key,
            kind=resource["resource_kind"],
            original_identity_hash=resource["content_hash"],
            declaration=declarations[key],
            capsules=[item["capsule"] for item in records.values() if item["metadata"]["resource_id"] == key],
            members={key: member.model_dump(mode="json") for key, member in members.items()},
            identities=identities,
        )
        if result["resource"] is not None:
            projected["resources"].append(result["resource"].model_dump(mode="json"))
            for name in ("busy_intervals", "duties", "transition_policies", "work_policies"):
                projected[name].extend(item.model_dump(mode="json") for item in result[name])
        issues.extend({"code": code, "subject_token": identities.uuid("resource", key)} for code in result["issues"])
    available_resources = {item["resource_id"] for item in projected["resources"]}
    for domain in request.cases:
        result = project_case(
            domain,
            records[domain.requirements.source_record_id]["original"],
            records[domain.duration_estimate.source_record_id]["original"],
            {key: record["capsule"] for key, record in records.items() if record["capsule"] is not None},
            identities,
        )
        case = result["case"]
        if case is not None and any(choice.resource_id not in available_resources for demand in [case.room, *case.roles, *case.equipment] for choice in demand.choices):
            case = None
            result["issues"].append("case_choice_resource_not_projectable")
        if case is not None:
            projected["cases"].append(case.model_dump(mode="json"))
        issues.extend({"code": code, "subject_token": identities.uuid("case", domain.application_id)} for code in result["issues"])
    for gap in collection["known_gaps"]:
        if set(gap) != {"code", "commitment"}:
            raise ValueError("Known collection gaps require closed technical commitments")
        issues.append({"code": gap["code"], "subject_token": identities.prehashed_key("known_gap", gap["commitment"])})

    def coverage(declaration, incomplete):
        return {
            "start_at": declaration.start_at,
            "end_at": declaration.end_at,
            "status": "unknown" if incomplete else declaration.status,
            "basis_hash": identities.basis({"original": declaration.basis_note, "known_issues": issues}) if incomplete else identities.basis(declaration.basis_note),
        }

    for values in projected.values():
        values.sort(key=canonical_json)
    profile = snapshot.rule_profile
    profile_content_hash = hash_content(profile)
    source = {
        "schema_version": "surgery_source_v1",
        "scenario_id": snapshot.scenario_id,
        "source_id": f"surgery_scenario:{snapshot.scenario_id}:{hash_content(value)[:12]}",
        "content_hash": hash_content(value),
        "governance_hash": governance_hash,
        "scope_token": snapshot.scope_token,
        "original_scope_hash": hash_content({"pool": collection["pool"], "cases": collection["cases"], "resource_collection_digest": collection["resource_collection_digest"]}),
        "period": collection["period"],
        "as_of": snapshot.as_of,
        "captured_at": snapshot.captured_at,
        "objective_mode": request.objective_mode,
        "rule_binding": {
            "rule_id": profile["rule_id"],
            "rule_version": profile["rule_version"],
            "profile_token": profile["profile_token"],
            "profile_content_hash": profile_content_hash,
            "profile_governance_hash": hash_content({"profile_token": profile["profile_token"], "profile_content_hash": profile_content_hash, "scenario_governance_hash": governance_hash}),
            "recipe_hash": profile["recipe_hash"],
            "input_policy_hash": profile["input_policy_hash"],
        },
        "collection": {**{key: collection[key] for key in ("collection_digest", *DIGEST_FIELDS[:4])}, "manifest_digest": hash_content(manifest)},
        "problem_coverage": {
            **{key: coverage(getattr(request.problem_coverage, key), bool(issues)) for key in ("cases", "resources", "all_locations_busy", "policies")},
            "finite_domains_status": request.problem_coverage.finite_domains_status,
            "basis_hash": identities.basis(request.problem_coverage.basis_note),
        },
        "person_partition": {"status": request.person_partition.status, "basis_hash": identities.basis(request.person_partition.model_dump(mode="json"))},
        "manifest": manifest,
        **projected,
    }
    bounded_json(source)
    if validate_current_recipe:
        source = SurgerySource.model_validate(source).model_dump(mode="json")
    return {"source": source, "issues": issues}


def project_source(snapshot, governance_hash, *, validate_current_recipe=True):
    return project_snapshot(snapshot, governance_hash, validate_current_recipe=validate_current_recipe)["source"]
