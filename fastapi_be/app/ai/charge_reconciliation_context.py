"""Short private admission binding and the sole verified model-visible projection."""

from typing import Literal

from fastapi import HTTPException
from pydantic import Field, TypeAdapter, model_validator

from app.ai.charge_reconciliation_contract import SHA, UUID, CaseOriginalProof, Positive, StrictModel, UtcText, canonical_json, digest

SCOPE_NOTE = "仅核对一次实际住院完整已记录账目及医嘱层级执行；模型只提出部分待核实问题，不作收费、退款或资金流确认。"
MISSING_DATA = (
    "实际收款、现金退款与押金交易流水未提供；原状态和汇总不证明资金流动。",
    "币种、历史价格、收费适用依据及逐收费行执行分摊未知；不从名称、相近时间或当前价格推断。",
    "浮点驱动值与独立SQL存储见证不等于原始输入十进制；字面引文不证明模型解释，最小化也不保证匿名。",
)


class ChargeContextBinding(StrictModel):
    schema_version: Literal["charge_context_binding_v1"]
    case_snapshot_id: UUID
    patient_id: Positive
    admission_id: UUID
    source_id: str = Field(min_length=1, max_length=110)
    content_hash: SHA
    publication_governance_hash: SHA
    projection_hash: SHA
    collection_digest: SHA
    manifest_hash: SHA
    policy_hash: SHA
    captured_at: UtcText
    float_capture_basis: Literal["mysql_same_statement_double_promotion", "sqlite_orm_float_only"]
    department_ids: list[Positive] = Field(max_length=1)

    @model_validator(mode="after")
    def exact_source_identity(self):
        if self.source_id != f"charge_case:{self.case_snapshot_id}:{self.content_hash[:12]}":
            raise ValueError("The case's immutable source identity differs")
        return self


def selection(values):
    if not isinstance(values, dict) or set(values) - {"charge_case_id", "question"} or "charge_case_id" not in values:
        raise HTTPException(422, "须明确选择一件受审住院账目原件，仅可另附问题，不得混入其他来源或业务写入字段")
    try:
        identifier = TypeAdapter(UUID).validate_python(values["charge_case_id"], strict=True)
        if "question" in values and values["question"] is not None:
            question = values["question"]
            if type(question) is not str or len(question) > 2000 or len(question.encode("utf-8", errors="strict")) > 8000:
                raise ValueError("The question must be exact bounded UTF8 text")
        return identifier
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "账目原件须为规范UUID；可选问题最多2000个Unicode码点和8000字节UTF8") from exc


def binding_for(value):
    from app.ai.charge_reconciliation_contract import POLICY, project_snapshot
    from app.ai.charge_reconciliation_sources import published_metadata, verify_original

    original = {key: value[key] for key in CaseOriginalProof.model_fields}
    if not verify_original(original):
        raise ValueError("The whole immutable recorded-ledger proof is invalid")
    published = published_metadata(original)
    projected = project_snapshot(original["snapshot"], published)
    if original["public_source"] != projected or original["projection_hash"] != digest(projected):
        raise ValueError("The complete sole public projection differs from its private original")
    collection = original["snapshot"]["collection"]
    department = collection["admission"]["department_id"]
    return ChargeContextBinding(
        schema_version="charge_context_binding_v1",
        **{key: original[key] for key in ("case_snapshot_id", "patient_id", "admission_id", "source_id", "content_hash", "collection_digest")},
        publication_governance_hash=published["governance_hash"],
        projection_hash=digest(projected),
        manifest_hash=collection["manifest_hash"],
        policy_hash=digest(POLICY),
        captured_at=collection["captured_at"],
        float_capture_basis=collection["float_capture_basis"],
        department_ids=[] if department is None else [department],
    ).model_dump(mode="json")


def charge_evidence(binding):
    bound = ChargeContextBinding.model_validate(binding).model_dump(mode="json")
    return {"source_id": bound["source_id"], "kind": "clinical_record", "title": "单次住院完整账目与医嘱层级执行冻结依据", "content": canonical_json({"charge_binding": bound})}


def short_context(binding, snapshot_time):
    bound = ChargeContextBinding.model_validate(binding)
    TypeAdapter(UtcText).validate_python(snapshot_time, strict=True)
    if snapshot_time < bound.captured_at:
        raise ValueError("The task clock cannot precede its complete original capture")
    return {
        "scope": "patient",
        "source_domain": "single_admission_recorded_ledger",
        "department_ids": bound.department_ids,
        "selected_sources": {"charge_case_id": bound.case_snapshot_id},
        "charge_binding": bound.model_dump(mode="json"),
        "scope_note": SCOPE_NOTE,
        "missing_data": list(MISSING_DATA),
        "truncated_sources": [],
        "snapshot_time": snapshot_time,
    }


def charge_context(db, user, patient_id, encounter_ref, values):
    from app.ai.charge_reconciliation_contract import utc_text
    from app.ai.charge_reconciliation_sources import case_current, utcnow
    from app.ai.context import ContextBundle

    value = case_current(db, user, selection(values), execution=True)
    bound = binding_for(value)
    if type(patient_id) is not int or patient_id != bound["patient_id"] or type(encounter_ref) is not str or encounter_ref != bound["admission_id"]:
        raise HTTPException(403, "受审账目原件与当前实际患者和住院作用域不一致")
    clock = utc_text(utcnow())
    return ContextBundle(data=short_context(bound, clock), evidence=[charge_evidence(bound)], department_ids=set(bound["department_ids"]))


def expand_context(db, context, *, user=None, current=False):
    """No-user frozen expansion is internal only, after actual Run authorization."""
    from app.ai.charge_reconciliation_sources import case_current, frozen_case_proof

    try:
        bound = ChargeContextBinding.model_validate(context["charge_binding"])
        binding = bound.model_dump(mode="json")
        if canonical_json(context) != canonical_json(short_context(binding, context["snapshot_time"])):
            raise ValueError("Different or mixed context cannot enter this recorded-ledger task")
        if current and user is None:
            raise ValueError("Current execution requires the actual authorized actor")
        value = frozen_case_proof(db, bound.case_snapshot_id) if user is None else case_current(db, user, bound.case_snapshot_id, audit_only=not current, execution=current)
        if binding_for(value) != binding:
            raise ValueError("The complete case or retained publication differs from the frozen binding")
        return {**context, "charge_source": value["public_source"], "charge_case": {**value, "frozen_task_view": True, "can_record": False, "can_review": False, "can_revoke": False}}
    except HTTPException as exc:
        if exc.status_code == 403:
            raise
        raise HTTPException(409, "账目完整原件、当前来源或冻结任务绑定无效") from exc
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "账目完整原件、当前来源或冻结任务绑定无效") from exc


def public_payload(data):
    """Send only the mechanically checked public projection and explicit question."""
    context = data["context"]
    bound = ChargeContextBinding.model_validate(context["charge_binding"])
    expected = short_context(bound.model_dump(mode="json"), context["snapshot_time"])
    if set(context) != {*expected, "charge_source", "charge_case"} or canonical_json({key: context[key] for key in expected}) != canonical_json(expected):
        raise ValueError("A mixed private context cannot enter this model request")
    source = context["charge_source"]
    if (
        selection(data["input"]) != bound.case_snapshot_id
        or context["charge_case"].get("eligible") is not True
        or context["charge_case"].get("audit_only") is not False
        or binding_for(context["charge_case"]) != bound.model_dump(mode="json")
        or digest(source) != bound.projection_hash
        or source["source_id"] != bound.source_id
        or source["content_hash"] != bound.content_hash
        or source["governance_hash"] != bound.publication_governance_hash
        or source["collection_digest"] != bound.collection_digest
        or digest(source["policy"]) != bound.policy_hash
    ):
        raise ValueError("The complete model-visible projection differs from the frozen case")
    return {"charge_source": source, "source_projection_hash": bound.projection_hash, "question": data["input"].get("question")}
