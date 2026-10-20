"""Mechanical public surgery projection from verified, authorized local originals."""

import hashlib
import hmac
import re
import secrets
import uuid

from app.ai.surgery_contract import FactRef, SurgeryCase, canonical_json, hash_content, identity
from app.ai.surgery_facts import GOVERNANCE_FIELDS, SourceFrozenIdentity, SourceWrapper
from app.ai.surgery_scenario_input import CaseDomain, MemberDeclaration, OriginalReference


def new_identity_secret():
    """Persist only inside the private scenario; never include in native payloads."""
    return secrets.token_hex(32)


class PublicIdentity:
    def __init__(self, private_secret):
        if not isinstance(private_secret, str) or re.fullmatch(r"[a-f0-9]{64}", private_secret) is None:
            raise ValueError("An actual private 256-bit scenario identity secret is required")
        self._key = bytes.fromhex(private_secret)

    def _digest(self, kind, value):
        return hmac.new(self._key, canonical_json([kind, value]).encode(), hashlib.sha256).digest()

    def uuid(self, kind, value):
        return str(uuid.UUID(bytes=self._digest(kind, value)[:16], version=4))

    def technical(self, kind, case_id, raw_key):
        # A client's ASCII technical key can itself contain a name. Every stage
        # and demand is mechanically renamed, including all referring fields.
        return "k_" + self._digest(kind, [identity(case_id), raw_key]).hex()[:40]

    def hashed_key(self, kind, raw_key):
        return self.prehashed_key(kind, hash_content(raw_key))

    def prehashed_key(self, kind, original_sha256):
        if not isinstance(original_sha256, str) or re.fullmatch(r"[a-f0-9]{64}", original_sha256) is None:
            raise ValueError("Complete original key SHA is required")
        return self._digest(kind, original_sha256).hex()

    def basis(self, original):
        return self._digest("original_basis", original).hex()


def _full_integrity(item):
    if item.payload is None or item.parent_binding is None or item.review_basis_note is None or item.revoke_reason is None:
        raise ValueError("A redacted technical source cannot reconstruct its undisclosed full original")
    if item.payload.kind != item.source_kind or item.source_id != f"surgery_fact:{item.source_record_id}:{item.content_hash[:12]}":
        raise ValueError("Original source kind or identity differs")
    body = {key: getattr(item, key) for key in SourceFrozenIdentity.model_fields}
    body.update(payload=item.payload.model_dump(mode="json"), parent_binding=item.parent_binding.model_dump(mode="json"))
    if hash_content(body) != item.content_hash or hash_content({key: getattr(item, key) for key in GOVERNANCE_FIELDS}) != item.governance_hash:
        raise ValueError("Complete private original or governance does not reconstruct")
    return item


def verified_original(value):
    """Reconstruct the full original and governance hashes; no live authority claim."""
    item = SourceWrapper.model_validate(value)
    if not item.eligible_for_new_use or item.status != "published" or item.exclusion_reasons:
        raise ValueError("An excluded, unknown or frozen-audit original cannot be restored for new native use")
    return _full_integrity(item)


def check_reference(original, reference, kind):
    reference = OriginalReference.model_validate({key: getattr(reference, key) for key in OriginalReference.model_fields} if isinstance(reference, OriginalReference) else reference)
    if original.source_kind != kind or any(
        getattr(original, key) != expected
        for key, expected in (
            ("source_record_id", reference.source_record_id),
            ("content_hash", reference.expected_content_hash),
            ("governance_hash", reference.expected_governance_hash),
        )
    ):
        raise ValueError("Selected whole original differs from its explicit original reference")


def public_fact(value, declaration, identities, as_of):
    item = SourceWrapper.model_validate(value)
    declaration = MemberDeclaration.model_validate(declaration.model_dump() if isinstance(declaration, MemberDeclaration) else declaration)
    check_reference(item, declaration, declaration.source_kind)
    if item.recorded_at > as_of or item.reviewed_at is not None and item.reviewed_at > as_of:
        raise ValueError("Current source was not available at the original cutoff; recapture instead of filtering")
    if declaration.selection == "confirmed":
        verified_original(value)
    elif item.payload is not None and item.parent_binding is not None and item.review_basis_note is not None and item.revoke_reason is not None:
        _full_integrity(item)
    return FactRef(
        fact_id=identities.uuid("fact", item.source_record_id),
        kind=item.source_kind,
        content_hash=item.content_hash,
        governance_hash=item.governance_hash,
        recorded_at=item.recorded_at,
        published_at=item.reviewed_at if item.status == "published" or item.status == "revoked" and item.revision == 3 else None,
        status=item.status,
        revision=item.revision,
        review=declaration.selection,
        review_basis_hash=identities.basis(declaration.basis_note),
    )


def _time_limit(value, identities):
    raw = value.model_dump(mode="json")
    return raw if raw["kind"] == "known" else {"kind": raw["kind"], "basis_hash": identities.basis(raw["basis_note"])}


def project_case(domain, requirements, estimate, duty_originals, identities):
    """Project a whole selected case; missing required/group declarations stay open.

    Inputs must already belong to the locked, authorized complete SQL collection.
    This helper checks integrity and binding, and cannot grant live SQL authority.
    """
    domain = CaseDomain.model_validate(domain.model_dump() if isinstance(domain, CaseDomain) else domain)
    requirements, estimate = verified_original(requirements), verified_original(estimate)
    check_reference(requirements, domain.requirements, "case_requirements")
    check_reference(estimate, domain.duration_estimate, "case_duration_estimate")
    if any(item.application_id != domain.application_id or item.parent_binding.case is None for item in (requirements, estimate)):
        raise ValueError("An actual matching case is required")
    parent = requirements.parent_binding.case
    if parent != estimate.parent_binding.case or parent.application_id != domain.application_id or parent.patient_id != requirements.patient_id or parent.patient_id != estimate.patient_id:
        raise ValueError("Selected case originals refer to different actual clinical parents")
    case, timing = requirements.payload, estimate.payload
    if any(item.professional_status != "confirmed" for item in (requirements, estimate)):
        return {"case": None, "issues": ["case_professional_attestation_unknown"]}
    unknown = [key for key in ("required", "procedure_group_key") if getattr(case, key) is None]
    if unknown:
        return {"case": None, "issues": ["case_" + key + "_unknown" for key in unknown]}
    original_roles = {item.slot_id: item for item in case.roles}
    original_equipment = {item.slot_id: item for item in case.equipment}
    if case.room.slot_id != domain.room.slot_id or set(original_roles) != {item.slot_id for item in domain.roles} or set(original_equipment) != {item.slot_id for item in domain.equipment}:
        raise ValueError("Every original role and concrete equipment demand needs its exact declared domain")
    app_id = domain.application_id

    def stage(raw):
        return identities.technical("stage", app_id, raw)

    def occupation(value):
        return {
            "segment_ids": [stage(key) for key in value.segment_ids],
            "occupation_mode": value.occupation_mode,
            "transition_class_hash": identities.hashed_key("transition_class", value.transition_class_key) if value.transition_class_key is not None else None,
            "transition_class_absent_reason": value.transition_class_absent_reason,
            "accounting": {"counted_as_work": value.counted_as_work, "absent_reason": value.counted_as_work_absent_reason},
            "basis_hash": identities.basis(value.basis_note),
        }

    def demand(original, declared, person=False):
        choices = []
        for choice in declared.choices:
            duty = None
            if person:
                if choice.duty_source is not None:
                    raw = verified_original(duty_originals[choice.duty_source.source_record_id])
                    check_reference(raw, choice.duty_source, "resource_availability_busy")
                    if raw.resource_id != choice.resource_id or raw.payload.record_type != "duty":
                        raise ValueError("Explicit duty membership belongs to a different actual person or record")
                duty = {
                    "duty_id": identities.uuid("duty", choice.duty_source.source_record_id) if choice.duty_source is not None else None,
                    "status": choice.duty_binding_status,
                    "basis_hash": identities.basis(choice.duty_basis_note),
                }
            choices.append({"resource_id": identities.uuid("resource", choice.resource_id), "penalty": choice.penalty.model_dump(), "duty_binding": duty})
        result = {
            "slot_id": identities.technical("demand", app_id, original.slot_id),
            "capability_hashes": [identities.hashed_key("capability", key) for key in original.capability_keys],
            "occupation": occupation(original.occupation),
            "domain_status": declared.domain_status,
            "choices": choices,
            "basis_hash": identities.basis({"requirement": original.basis_note, "domain": declared.basis_note}),
        }
        if person:
            result.update(role_kind=original.role_kind, other_role_hash=identities.hashed_key("role", original.other_role_key) if original.other_role_key is not None else None)
        return result

    value = SurgeryCase(
        case_id=identities.uuid("case", app_id),
        patient_conflict_token=identities.uuid("patient", parent.patient_id),
        patient_identity_status="verified",
        procedure_group_hash=identities.hashed_key("procedure_group", case.procedure_group_key),
        ref_ids=[identities.uuid("fact", requirements.source_record_id)],
        required=case.required,
        release=_time_limit(case.release, identities),
        deadline=_time_limit(case.deadline, identities),
        start_domain_status=domain.start_domain_status,
        starts=[item.model_dump() for item in domain.starts],
        timing={
            "method": timing.method,
            "semantics": timing.semantics,
            "segments": [
                {
                    "segment_id": stage(item.segment_id),
                    "start_offset_us": item.start_offset_us.model_dump(),
                    "end_offset_us": item.end_offset_us.model_dump(),
                    "ref_ids": [identities.uuid("fact", estimate.source_record_id)],
                }
                for item in timing.segments
            ],
            "basis_hash": identities.basis(timing.basis_note),
        },
        patient_presence={"segment_ids": [stage(key) for key in case.patient_segment_ids], "occupation_mode": case.patient_occupation_mode, "basis_hash": identities.basis(case.basis_note)},
        room=demand(case.room, domain.room),
        roles=[demand(original_roles[item.slot_id], item, True) for item in domain.roles],
        equipment=[demand(original_equipment[item.slot_id], item) for item in domain.equipment],
        penalty_if_scheduled=domain.penalty_if_scheduled.model_dump(),
        penalty_if_deferred=domain.penalty_if_deferred.model_dump() if domain.penalty_if_deferred is not None else None,
        other_requirements={"status": case.other_requirements_status, "basis_hash": identities.basis(case.basis_note)},
    )
    return {"case": value, "issues": []}
