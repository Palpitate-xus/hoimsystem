"""Complete recorded ledger facts, never proof of money movement or entitlement."""

import datetime as dt
import hashlib
import hmac
import json
import math
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, create_model, model_validator
from sqlalchemy import Date, DateTime, Float, Integer, Numeric

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 8192
SOURCE_ROLES = frozenset({"admin", "super_admin", "cashier", "director"})
SHA = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
UUID = Annotated[str, Field(pattern=r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$")]
Positive = Annotated[int, Field(strict=True, ge=1, le=2147483647)]


def utf8(value):
    return value.encode("utf-8", errors="strict")


def canonical_json(value):
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(utf8(canonical_json(value))).hexdigest()


def utc_text(value):
    if value.tzinfo is not None:
        value = value.astimezone(dt.UTC).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds") + "Z"


def exact_clock(value, *, utc):
    parsed = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ" if utc else "%Y-%m-%dT%H:%M:%S.%f")
    if (utc_text(parsed) if utc else parsed.isoformat(timespec="microseconds")) != value:
        raise ValueError("Exact Gregorian clock spelling required")
    return value


UtcText = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"), AfterValidator(lambda value: exact_clock(value, utc=True))]
NaiveText = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}$"), AfterValidator(lambda value: exact_clock(value, utc=False))]
DateText = Annotated[str, AfterValidator(lambda value: value if dt.date.fromisoformat(value).isoformat() == value else (_ for _ in ()).throw(ValueError("Canonical Date required")))]
DecimalText = Annotated[str, AfterValidator(lambda value: value if str(Decimal(value)) == value else (_ for _ in ()).throw(ValueError("Exact fetched Decimal text required")))]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_default=True, allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def strings_are_utf8(cls, value):
        # This also rejects surrogate strings in private notes before storage.
        pending = [value]
        while pending:
            item = pending.pop()
            if isinstance(item, BaseModel):
                pending.append(item.model_dump(mode="json"))
            elif isinstance(item, str):
                utf8(item)
            elif isinstance(item, dict):
                for key, child in item.items():
                    utf8(key)
                    pending.append(child)
            elif isinstance(item, list):
                pending.extend(item)
        return value


class SQLFloatWitness(StrictModel):
    method: Literal["mysql_CAST_AS_DOUBLE_in_same_current_statement"]
    value_text: str | None
    binary_hex: str | None

    @model_validator(mode="after")
    def promoted_value(self):
        if self.value_text is None and self.binary_hex is None:
            return self
        value = float.fromhex(self.binary_hex)
        if not math.isfinite(value) or value.hex() != self.binary_hex or repr(value) != self.value_text:
            raise ValueError("The SQL-promoted finite Float witness must remain exact")
        return self


class StoredFloat(StrictModel):
    state: Literal["null", "finite", "nan", "positive_infinity", "negative_infinity"]
    value_text: str | None
    binary_hex: str | None
    precision_basis: Literal["fetched_ORM_float_not_original_decimal_or_SQLite_MySQL_precision_equivalence"]
    storage_witness: SQLFloatWitness | None

    @model_validator(mode="after")
    def original_representation(self):
        if self.state == "null":
            if self.value_text is not None or self.binary_hex is not None:
                raise ValueError("Null Float must remain null")
            return self
        value = float.fromhex(self.binary_hex)
        state = "nan" if math.isnan(value) else "positive_infinity" if value == math.inf else "negative_infinity" if value == -math.inf else "finite"
        if state != self.state or repr(value) != self.value_text or value.hex() != self.binary_hex:
            raise ValueError("The fetched Float repr and hexadecimal proof differ")
        return self


def stored_float(value, *, sql_witness=None):
    return StoredFloat(
        state="null" if value is None else "nan" if math.isnan(value) else "positive_infinity" if value == math.inf else "negative_infinity" if value == -math.inf else "finite",
        value_text=None if value is None else repr(value),
        binary_hex=None if value is None else value.hex(),
        precision_basis="fetched_ORM_float_not_original_decimal_or_SQLite_MySQL_precision_equivalence",
        storage_witness=sql_witness,
    ).model_dump(mode="json")


class CaptureRequest(StrictModel):
    patient_id: Positive
    admission_id: UUID


class CaseCreate(StrictModel):
    request: CaptureRequest
    expected_collection_digest: SHA
    note: str = Field(max_length=4000)

    @model_validator(mode="after")
    def note_bytes(self):
        if len(utf8(self.note)) > 4000:
            raise ValueError("Private basis exceeds4000UTF8bytes")
        return self


class CompareAndSwap(StrictModel):
    expected_revision: Annotated[int, Field(ge=1, le=3)]
    expected_content_hash: SHA
    expected_governance_hash: SHA


class SourceReview(CompareAndSwap):
    decision: Literal["publish", "reject"]
    basis_note: str = Field(min_length=20, max_length=4000)

    @model_validator(mode="after")
    def basis_bytes(self):
        check_basis(self.basis_note)
        return self


class SourceRevoke(CompareAndSwap):
    basis_note: str = Field(min_length=20, max_length=1000)

    @model_validator(mode="after")
    def basis_bytes(self):
        check_basis(self.basis_note)
        return self


def check_basis(value):
    if len("".join(value.split())) < 20 or len(utf8(value)) > 4000:
        raise ValueError("Explicit meaningful review basis within4000UTF8bytes required")


class PatientBinding(StrictModel):
    patient_id: Positive
    name: str | None
    identity: str | None
    phone: str | None
    address: str | None


# Exact field sets come from real SQL models; relationships are never traversed.
# An added legacy column changes the generated schema and must be reviewed; no
# arbitrary JSON or silent omission is accepted by the private proof validator.
def original_model(name, sql_model):
    fields = {}
    for column in sql_model.__table__.columns:
        type_ = column.type
        annotation = (
            StoredFloat
            if isinstance(type_, Float)
            else NaiveText
            if isinstance(type_, DateTime)
            else DateText
            if isinstance(type_, Date)
            else int
            if isinstance(type_, Integer)
            else DecimalText
            if isinstance(type_, Numeric)
            else str
        )
        fields[column.name] = (annotation if isinstance(type_, Float) else annotation | None, ...)
    return create_model(name, __base__=StrictModel, __module__=__name__, **fields)


from app import models as _models  # noqa: E402

AdmissionOriginal = original_model("AdmissionOriginal", _models.Admission)
ChargeOriginal = original_model("ChargeOriginal", _models.InpatientCharge)
OrderOriginal = original_model("OrderOriginal", _models.InpatientOrder)
OrderItemOriginal = original_model("OrderItemOriginal", _models.InpatientOrderItem)
ExecutionOriginal = original_model("ExecutionOriginal", _models.OrderExecution)
AdministrationOriginal = original_model("AdministrationOriginal", _models.MedicationAdministration)


class Member(StrictModel):
    kind: Literal["patient_binding", "admission", "charge", "order", "order_item", "execution", "administration"]
    record_id: str
    content_hash: SHA


class Collection(StrictModel):
    schema_version: Literal["charge_ledger_collection_v1"]
    request: CaptureRequest
    captured_at: UtcText
    float_capture_basis: Literal["mysql_same_statement_double_promotion", "sqlite_orm_float_only"]
    patient_binding: PatientBinding
    admission: AdmissionOriginal
    charges: list[ChargeOriginal]
    orders: list[OrderOriginal]
    order_items: list[OrderItemOriginal]
    executions: list[ExecutionOriginal]
    administrations: list[AdministrationOriginal]
    member_manifest: list[Member]
    manifest_hash: SHA
    collection_digest: SHA


class CaseSnapshot(StrictModel):
    schema_version: Literal["charge_case_snapshot_v1"]
    case_snapshot_id: UUID
    patient_id: Positive
    admission_id: UUID
    created_by: Positive
    created_at: UtcText
    identity_secret: SHA
    note: str = Field(max_length=4000)
    collection: Collection

    @model_validator(mode="after")
    def note_byte_limit(self):
        if len(utf8(self.note)) > 4000:
            raise ValueError("Private note exceeds4000UTF8bytes")
        return self


class CaseMetadata(StrictModel):
    case_snapshot_id: UUID
    patient_id: Positive
    admission_id: UUID
    schema_version: Literal["charge_case_snapshot_v1"]
    created_at: UtcText
    created_by: Positive
    collection_digest: SHA
    content_hash: SHA
    source_id: str
    governance_hash: SHA
    status: Literal["draft", "published", "rejected", "revoked"]
    revision: Annotated[int, Field(ge=1, le=3)]
    reviewed_at: UtcText | None
    reviewed_by: Positive | None
    review_basis_note: str = Field(max_length=4000)
    revoked_at: UtcText | None
    revoked_by: Positive | None
    revoke_reason: str = Field(max_length=1000)


class CaseOriginalProof(CaseMetadata):
    snapshot: CaseSnapshot
    public_source: dict | None
    projection_hash: SHA | None


POLICY = {
    "schema_version": "charge_projection_policy_v1",
    "scope": "one_actual_inpatient_admission_recorded_ledger_and_order_level_execution",
    "cash_receipt": "not_provided",
    "cash_refund": "not_provided",
    "deposit_transaction_history": "not_provided",
    "currency_and_historical_tariff": "unknown",
    "line_level_execution_allocation": "not_provided",
    "billing_entitlement": "unknown",
    "legacy_clock_timezone": "unknown",
    "float_semantics": "driver_fetched_value_and_explicit_same_statement_MySQL_DOUBLE_witness_are_distinct_not_original_decimal",
    "monetary_semantics": "stored_decimal_fields_only_no_implied_currency_rounding_tariff_or_cash_flow",
    "minimization": "known_direct_identifiers_in_explicit_display_fields_not_anonymity",
    "automatic_charge_or_refund": False,
}


def token(snapshot, kind, identifier):
    return "charge_" + kind + ":" + hmac.new(bytes.fromhex(snapshot["identity_secret"]), utf8(kind + ":" + str(identifier)), hashlib.sha256).hexdigest()


def project_snapshot(snapshot, metadata):
    from app.ai.context import minimize_identifiers

    collection = snapshot["collection"]
    patient = SimpleNamespace(**collection["patient_binding"])

    def display(value):
        return minimize_identifiers(value, patient)

    specs = (
        ("charges", "charge", "charge_id", ("item_name", "item_type", "quantity", "unit_price", "total_amount", "charge_date", "status", "create_time", "settled_time", "refunded_time")),
        ("orders", "order", "order_id", ("order_type", "category", "status", "priority", "start_time", "stop_time", "create_time")),
        ("order_items", "order_item", "item_id", ("item_name", "item_type", "quantity", "unit", "days", "unit_price", "total_price")),
        ("executions", "execution", "execution_id", ("planned_time", "execution_time", "status")),
        ("administrations", "administration", "administration_id", ("status", "verified_at", "administration_time")),
    )
    result = {
        "schema_version": "charge_ledger_source_v1",
        "source_id": metadata["source_id"],
        "content_hash": metadata["content_hash"],
        "governance_hash": metadata["governance_hash"],
        "collection_digest": collection["collection_digest"],
        "policy": dict(POLICY),
    }
    ids = {row["order_id"] for row in collection["orders"]}
    for key, kind, primary, fields in specs:
        rows = []
        for original in collection[key]:
            row = {"source_id": token(snapshot, kind, original[primary]), **{field: display(original[field]) if field in {"item_name", "unit"} else original[field] for field in fields}}
            for field, allowed in (("item_type", {"drug", "consumable", "bed", "service", "exam", "surgery", "anesthesia"}), ("category", {"drug", "treatment", "exam", "diet", "nursing", "other"})):
                if field in row:
                    row[field] = original[field] if original[field] in allowed else "unknown"
                    row["original_" + field + "_hash"] = digest(original[field])
            for field in {"unit_price", "total_amount", "total_price"} & row.keys():
                value = original[field]
                row[field + "_state"] = "null" if value is None else "finite" if Decimal(value).is_finite() else "nonfinite"
            if "order_id" in original:
                row["order_source_id"] = token(snapshot, "order", original["order_id"])
            if "execution_id" in original and kind == "administration":
                row["execution_source_id"] = token(snapshot, "execution", original["execution_id"])
            if kind == "charge":
                linked = original["related_order_id"]
                row["order_association"] = "not_recorded" if linked is None else "recorded_same_admission" if linked in ids else "unresolved_or_out_of_scope"
                row["order_source_id"] = token(snapshot, "order", linked) if linked in ids else None
            rows.append(row)
        result[key] = rows
    result["admission"] = {
        "status": collection["admission"]["status"],
        "deposit_amount": collection["admission"]["deposit_amount"],
        "admission_time": collection["admission"]["admission_time"],
        "discharge_time": collection["admission"]["discharge_time"],
    }
    deposit = collection["admission"]["deposit_amount"]
    result["admission"]["deposit_amount_state"] = "null" if deposit is None else "finite" if Decimal(deposit).is_finite() else "nonfinite"
    return result
