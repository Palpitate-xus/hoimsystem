"""Pure, bounded76 Task references and literal Source consistency.

These types grant no project, patient, model or export permission. The server
must obtain each named original from its current SQL authority before creating
the access manifest, and repeat that proof before any Task/private Batch TEXT.
"""

import datetime as dt
import hashlib
import json
import math
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, model_validator

from app.ai.research_cohort_contract import SHA, UTC, UUID, Family, Positive, StrictModel, scalar
from app.ai.research_variables_contract import VariableDefinition
from app.ai.research_variables_draft import FieldToken, LiteralDocument, MemberToken, RecordToken, validate_draft
from app.ai.research_variables_fields import LIMITATIONS

FEATURE_KEY = "research_extraction"
INPUT_MODE = "research_variable_extraction"
REFERENCE_KEY = "research_variable_batch_id"
SOURCE_DOMAIN = "published_research_variable_literal_batch"
MAX_WIRE_BYTES = 8 * 1024 * 1024
MAX_RUN_TEXT_BYTES = 65535
# 256 patients * four explicit identity/content/governance anchors plus the
# fixed Scope/ACL/epoch fields fit below this. It is independent of Run TEXT.
MAX_BINDING_BYTES = 262144
MAX_JSON_NODES = 400000
MAX_JSON_DEPTH = 32
RECIPE_FILES = (
    "research_variables_fields.py",
    "research_variables_contract.py",
    "research_variables_collection.py",
    "research_variables_capture_proof.py",
    "research_variables_dictionary.py",
    "research_variables_snapshot.py",
    "research_cohort_contract.py",
    "research_cohort_collection.py",
    "research_cohort_registry.py",
    "research_cohort_sources.py",
)
TaskRole = Literal["super_admin", "admin", "director", "doctor", "pharmacist"]


def _preflight(value, maximum):
    stack, nodes, raw_bytes = [(value, 0)], 0, 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise ValueError("The whole closed JSON exceeds its declared node/depth budget")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise ValueError("Only actual string JSON keys are allowed")
            if nodes + len(stack) + 2 * len(item) > MAX_JSON_NODES:
                raise ValueError("The complete object cannot fit the remaining node budget")
            stack.extend((key, depth + 1) for key in item)
            stack.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            if nodes + len(stack) + len(item) > MAX_JSON_NODES:
                raise ValueError("The complete list cannot fit the remaining node budget")
            stack.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            raw_bytes += len(item.encode("utf-8", errors="strict"))
        elif type(item) is int:
            if not -(2**63) <= item < 2**63:
                raise ValueError("JSON integer metadata must be an exact bounded original")
        elif type(item) is float:
            if not math.isfinite(item):
                raise ValueError("Nonfinite JSON is not a declared fact")
        elif item is not None and type(item) is not bool:
            raise ValueError("Only literal JSON values are supported")
        if raw_bytes > maximum:
            raise ValueError("Whole original UTF8 already exceeds the complete byte budget")


def canonical(value, maximum=MAX_WIRE_BYTES):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    _preflight(value, maximum)
    size, chunks = 0, []
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":"))
    for chunk in encoder.iterencode(value):
        size += len(chunk.encode("utf-8", errors="strict"))
        if size > maximum:
            raise ValueError("The whole JSON including escaping/envelope exceeds its byte budget")
        chunks.append(chunk)
    return "".join(chunks)


def digest(value, maximum=MAX_WIRE_BYTES):
    return hashlib.sha256(canonical(value, maximum).encode("utf-8")).hexdigest()


def strict_json(raw, maximum=MAX_WIRE_BYTES):
    if type(raw) is not str or len(raw.encode("utf-8", errors="strict")) > maximum:
        raise ValueError("A complete bounded UTF8 JSON string is required")
    quoted, escaped, depth = False, False, 0
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise ValueError("JSON nesting exceeds the complete depth budget")
        elif char in "]}":
            depth -= 1

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate JSON keys cannot choose a winner")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Nonfinite constants are not supported")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    canonical(value, maximum)
    return value


def validate_question(value):
    scalar(value)
    if len(value) > 2000 or len(value.encode("utf-8")) > 8000:
        raise ValueError("An unchanged optional question must fit2000 codepoints/8000 UTF8 bytes")
    return value


class VariableTaskSelection(StrictModel):
    research_variable_batch_id: UUID
    question: Annotated[str, AfterValidator(validate_question)] | None = None


class PatientAuthorizationAnchor(StrictModel):
    patient_id: Positive
    authorization_id: UUID
    content_hash: SHA
    governance_hash: SHA


class VariableTaskAccessManifest(StrictModel):
    """Concrete original refs, never a caller assertion of actual permission."""

    schema_version: Literal["research_variable_task_access_v1"]
    requested_by: Positive
    actor_role: TaskRole
    actor_token_invalid_before: UTC | None
    scope_id: UUID
    scope_content_hash: SHA
    scope_governance_hash: SHA
    acl_id: UUID
    acl_content_hash: SHA
    acl_governance_hash: SHA
    patient_authorizations: Annotated[list[PatientAuthorizationAnchor], Field(min_length=1, max_length=256)]

    @model_validator(mode="after")
    def complete_finite_originals(self):
        ids = [row.patient_id for row in self.patient_authorizations]
        grants = [row.authorization_id for row in self.patient_authorizations]
        if ids != sorted(set(ids)) or len(grants) != len(set(grants)):
            raise ValueError("Every original Scope patient and independent permission must be unique, sorted and explicit")
        canonical(self, MAX_BINDING_BYTES)
        return self


class VariableSourceRecipe(StrictModel):
    rule_id: Literal["research_variable_literal_projection_v1"]
    implementation_sha256: dict[str, SHA]

    @model_validator(mode="after")
    def whole_declared_recipe(self):
        if set(self.implementation_sha256) != set(RECIPE_FILES):
            raise ValueError("Every declared original Source implementation hash must remain present")
        return self


def naive_clock(value):
    scalar(value)
    stamp = dt.datetime.fromisoformat(value)
    if stamp.tzinfo is not None or stamp.isoformat(timespec="microseconds") != value:
        raise ValueError("Original naive clock and stored microseconds cannot acquire a timezone")
    return value


NaiveClock = Annotated[str, AfterValidator(naive_clock)]
OriginalInteger = Annotated[int, Field(strict=True, ge=-(2**63), le=2**63 - 1)]


class VariableSourceRecord(StrictModel):
    member_token: MemberToken
    record_token: RecordToken
    family: Family
    recorded_clock: NaiveClock | None
    window_status: Literal["static_subject_without_event_clock", "unknown_record_clock", "recorded_naive_calendar_in_variable_window"]
    lifecycle_original: dict[str, OriginalInteger | NaiveClock | None]
    parent_status: Literal["patient_bound", "unknown_parent", "missing_parent", "patient_mismatch"]
    field_tokens: Annotated[list[FieldToken], Field(min_length=1, max_length=64)]

    @model_validator(mode="after")
    def literal_lifecycle_and_clock(self):
        static = self.family == "patient_demographics"
        expected = set() if static else {"status", "sign_time"} if self.family in {"medical_records", "structured_medical_records"} else {"status"}
        if set(self.lifecycle_original) != expected:
            raise ValueError("The complete original lifecycle fields depend on the declared family")
        status = self.lifecycle_original.get("status")
        signed = self.lifecycle_original.get("sign_time")
        if status is not None and type(status) is not int or signed is not None and type(signed) is not str:
            raise ValueError("Original lifecycle integer and naive-clock types cannot be interchanged")
        expected_window = "static_subject_without_event_clock" if static else "unknown_record_clock" if self.recorded_clock is None else "recorded_naive_calendar_in_variable_window"
        if self.window_status != expected_window or static and self.recorded_clock is not None or static and self.parent_status != "patient_bound":
            raise ValueError("Unknown or static clocks cannot be relabeled as observed event time")
        if len(set(self.field_tokens)) != len(self.field_tokens):
            raise ValueError("One original field cannot appear twice in a public record")
        return self


class VariableTaskSource(StrictModel):
    schema_version: Literal["research_variable_source_v1"]
    source_id: Annotated[str, Field(strict=True, pattern=r"^research_variables:[a-f0-9-]{36}:[a-f0-9]{12}$")]
    content_hash: SHA
    governance_hash: SHA
    captured_at: UTC
    scope_token: Annotated[str, Field(strict=True, pattern=r"^rv_scope:[a-f0-9]{64}$")]
    dictionary_token: Annotated[str, Field(strict=True, pattern=r"^rv_dictionary:[a-f0-9]{64}$")]
    authorization_binding: Annotated[str, Field(strict=True, pattern=r"^rv_authority:[a-f0-9]{64}$")]
    collection_binding: Annotated[str, Field(strict=True, pattern=r"^rv_collection:[a-f0-9]{64}$")]
    member_tokens: Annotated[list[MemberToken], Field(min_length=1, max_length=256)]
    variables: Annotated[list[VariableDefinition], Field(min_length=1, max_length=64)]
    records: Annotated[list[VariableSourceRecord], Field(max_length=8192)]
    documents: Annotated[list[LiteralDocument], Field(max_length=8192)]
    documents_hash: SHA
    recipe: VariableSourceRecipe
    limitations: Annotated[list[str], Field(max_length=5)]
    coverage: Literal["all_declared_recorded_candidates_no_inferred_absence_or_automatic_winner"]
    privacy_basis: Literal["purpose_authorized_identifier_minimization_not_anonymity"]
    external_model_use: Literal["unknown", "recorded_permitted", "not_permitted"]

    @model_validator(mode="after")
    def every_literal_has_one_actual_record_and_variable(self):
        canonical(self)
        if self.limitations != list(LIMITATIONS) or len(set(self.member_tokens)) != len(self.member_tokens):
            raise ValueError("The full declared member set and every fixed limitation are retained")
        if self.source_id.rsplit(":", 1)[1] != self.content_hash[:12]:
            raise ValueError("The public Source identity anchors the actual original content")
        VariableTaskSelection(research_variable_batch_id=self.source_id.split(":")[1])
        variables = {row.variable_key: row for row in self.variables}
        if len(variables) != len(self.variables) or list(variables) != sorted(variables):
            raise ValueError("The complete variable dictionary has unique canonical keys")
        records = {row.record_token: row for row in self.records}
        documents = {row.field_token: row for row in self.documents}
        if len(records) != len(self.records) or len(documents) != len(self.documents):
            raise ValueError("Duplicate original records/fields cannot select a winner")
        used = []
        for record in self.records:
            if record.member_token not in self.member_tokens:
                raise ValueError("An original record cannot extend the declared subject tokens")
            keys = []
            for token in record.field_tokens:
                document = documents.get(token)
                if document is None or (document.member_token, document.record_token) != (record.member_token, record.record_token):
                    raise ValueError("Every field must name its one exact subject and original record")
                variable = variables.get(document.variable_key)
                if variable is None or (variable.family, variable.value_kind) != (record.family, document.value_kind):
                    raise ValueError("A field cannot substitute another variable, family or original type")
                if variable.record_window is not None and record.recorded_clock is not None:
                    if not variable.record_window.date_from <= record.recorded_clock[:10] <= variable.record_window.date_to:
                        raise ValueError("A known original calendar clock must remain inside its exact variable window")
                keys.append(document.variable_key)
                used.append(token)
            if keys != sorted(set(keys)):
                raise ValueError("Each original record retains unique canonical variable fields")
        if used != [row.field_token for row in self.documents] or set(used) != set(documents):
            raise ValueError("The complete document set retains exact record/field order without omission or duplicates")
        if digest([row.model_dump(mode="json") for row in self.documents]) != self.documents_hash:
            raise ValueError("The whole original literal-document SHA differs")
        # Reuse the frozen76 exact integer/date/naive-clock and CP semantics;
        # constructing no proposals never makes NULL a missingness conclusion.
        validate_draft({"schema_version": "research_variable_draft_v1", "coverage": "partial_candidates_only", "candidates": []}, [row.model_dump(mode="json") for row in self.documents])
        return self


def validate_source(value):
    """Shape and literal consistency only, not SQL or HMAC completeness."""
    canonical(value)
    return VariableTaskSource.model_validate(value)


def validate_frozen_source(value, expected_projection_hash):
    """Compare the whole Source to a separately authorized durable SQL anchor.

    The expected hash must come from the trusted current/frozen server record;
    accepting a caller's self-rehashed digest would prove no origin/completeness.
    """
    from pydantic import TypeAdapter

    TypeAdapter(SHA).validate_python(expected_projection_hash, strict=True)
    if digest(value) != expected_projection_hash:
        raise ValueError("The whole public Source differs from its original independent projection anchor")
    return validate_source(value)
