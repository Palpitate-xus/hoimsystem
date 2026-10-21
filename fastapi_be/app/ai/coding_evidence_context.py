"""Short immutable case references; only the one reviewed text projection leaves SQL."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from app.ai.coding_evidence_input import SHA, UUID, Positive, StrictModel, UtcText

SCOPE_NOTE = "仅整理一份实际病案首页及同次住院的完整已记录编码证据；模型意见须人工核实，不执行编码、分组或结算。"
MISSING_DATA = (
    "逐字引文只核实最小化投影的文字位置，不证明模型对否定、疑似、既往或因果关系的医学解释。",
    "当前字典未提供发行版本；已记录分组缺少原历史规则依据，本地前缀规则包不等于官方DRG/DIP分组器。",
    "技术发布和来源校验不代表编码员或医生已确认；直接标识最小化不保证匿名。",
)


class CodingContextBinding(StrictModel):
    schema_version: Literal["coding_context_binding_v1"]
    case_snapshot_id: UUID
    patient_id: Positive
    admission_id: UUID
    home_id: UUID
    source_id: str = Field(min_length=1, max_length=110)
    content_hash: SHA
    publication_governance_hash: SHA
    projection_hash: SHA
    collection_digest: SHA
    manifest_hash: SHA
    policy_hash: SHA
    captured_at: UtcText
    department_ids: list[Positive] = Field(max_length=1)

    @model_validator(mode="after")
    def exact_identity(self):
        if self.source_id != f"coding_case:{self.case_snapshot_id}:{self.content_hash[:12]}":
            raise ValueError("The immutable case source identity differs")
        return self


def selection(values):
    if not isinstance(values, dict) or set(values) - {"coding_case_id", "question"} or "coding_case_id" not in values:
        raise HTTPException(422, "须明确选择一件受审编码证据快照，仅可另附问题，不能混入首页或其他来源引用")
    try:
        from pydantic import TypeAdapter

        identifier = TypeAdapter(UUID).validate_python(values["coding_case_id"], strict=True)
        if "question" in values:
            if type(values["question"]) is not str or len(values["question"]) > 12000:
                raise ValueError("Question must be bounded text")
            values["question"].encode("utf-8")
        return identifier
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "编码证据须为规范UUID，补充问题须为最多12000字UTF-8文本") from exc


def binding_for(value):
    """Rebuild from the complete private original and its sole public mapper."""
    from app.ai.coding_evidence_projection import POLICY, project_snapshot
    from app.ai.coding_evidence_sources import GOVERNANCE, IDENTITY, hash_content, published_metadata, verify_original

    original = {key: value[key] for key in (*IDENTITY, *GOVERNANCE, "content_hash", "source_id", "governance_hash", "snapshot")}
    if not verify_original(original):
        raise ValueError("Complete immutable case proof is invalid")
    published = published_metadata(original)
    source = project_snapshot(original["snapshot"], published)
    if value.get("public_source") != source or value.get("projection_hash") != hash_content(source):
        raise ValueError("The stored complete projection differs from its original")
    collection = original["snapshot"]["collection"]
    department = collection["admission_binding"]["department_id"]
    return CodingContextBinding(
        schema_version="coding_context_binding_v1",
        **{key: original[key] for key in ("case_snapshot_id", "patient_id", "admission_id", "home_id", "source_id", "content_hash", "collection_digest")},
        publication_governance_hash=published["governance_hash"],
        projection_hash=hash_content(source),
        manifest_hash=collection["manifest_hash"],
        policy_hash=hash_content(POLICY),
        captured_at=collection["captured_at"],
        department_ids=[] if department is None else [department],
    ).model_dump(mode="json")


def coding_evidence(binding):
    from app.ai.coding_evidence_sources import canonical_json

    bound = CodingContextBinding.model_validate(binding).model_dump(mode="json")
    return {"source_id": bound["source_id"], "kind": "clinical_record", "title": "单次住院完整病案编码原件及最小化引文投影", "content": canonical_json({"coding_binding": bound})}


def short_context(binding, snapshot_time):
    bound = CodingContextBinding.model_validate(binding)
    return {
        "scope": "patient",
        "source_domain": "single_home_coding_evidence",
        "department_ids": bound.department_ids,
        "selected_sources": {"coding_case_id": bound.case_snapshot_id},
        "coding_binding": bound.model_dump(mode="json"),
        "scope_note": SCOPE_NOTE,
        "missing_data": list(MISSING_DATA),
        "truncated_sources": [],
        "snapshot_time": snapshot_time,
    }


def coding_context(db, user, patient_id, encounter_ref, values):
    from app.ai.coding_evidence_sources import case_current
    from app.ai.context import ContextBundle

    value = case_current(db, user, selection(values), execution=True)
    bound = binding_for(value)
    if type(patient_id) is not int or patient_id != bound["patient_id"] or encounter_ref != bound["admission_id"]:
        raise HTTPException(403, "编码证据与当前实际患者和住院作用域不一致")
    now = datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return ContextBundle(data=short_context(bound, now), evidence=[coding_evidence(bound)], department_ids=set(bound["department_ids"]))


def expand_context(db, context, *, user=None, current=False):
    """No-user expansion is internal proof only, after the caller authorizes Run."""
    from app.ai.coding_evidence_sources import canonical_json, case_current, frozen_case_proof

    try:
        bound = CodingContextBinding.model_validate(context["coding_binding"])
        binding = bound.model_dump(mode="json")
        if canonical_json(context) != canonical_json(short_context(binding, context["snapshot_time"])):
            raise ValueError("Short context has different scalar types, scope or extra bodies")
        from pydantic import TypeAdapter

        TypeAdapter(UtcText).validate_python(context["snapshot_time"], strict=True)
        if current and user is None:
            raise ValueError("Current execution needs the actual authorized actor")
        value = frozen_case_proof(db, bound.case_snapshot_id) if user is None else case_current(db, user, bound.case_snapshot_id, audit_only=not current, execution=current)
        if binding_for(value) != binding:
            raise ValueError("Complete case or frozen publication binding differs")
        return {**context, "coding_source": value["public_source"], "coding_case": {**value, "frozen_task_view": True, "can_record": False, "can_review": False, "can_revoke": False}}
    except HTTPException as exc:
        if exc.status_code == 403:
            raise
        raise HTTPException(409, "编码证据完整原件、当前来源或冻结任务绑定无效") from exc
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
        raise HTTPException(409, "编码证据完整原件、当前来源或冻结任务绑定无效") from exc


def public_payload(data):
    """Model sees the checked projection and question; no patient/home/operator ids."""
    from app.ai.coding_evidence_sources import canonical_json, hash_content

    context = data["context"]
    bound = CodingContextBinding.model_validate(context["coding_binding"])
    expected = short_context(bound.model_dump(mode="json"), context["snapshot_time"])
    if set(context) != {*expected, "coding_source", "coding_case"} or canonical_json({key: context[key] for key in expected}) != canonical_json(expected):
        raise ValueError("Different or mixed private context cannot enter this coding request")
    source = context["coding_source"]
    if (
        selection(data["input"]) != bound.case_snapshot_id
        or hash_content(source) != bound.projection_hash
        or source["source_id"] != bound.source_id
        or source["case_content_hash"] != bound.content_hash
        or source["case_publication_governance_hash"] != bound.publication_governance_hash
        or source["case_snapshot_id"] != bound.case_snapshot_id
        or hash_content(source["policy"]) != bound.policy_hash
    ):
        raise ValueError("Complete model-visible source differs from the frozen binding")
    return {"coding_source": source, "source_projection_hash": bound.projection_hash, "question": data["input"].get("question")}
