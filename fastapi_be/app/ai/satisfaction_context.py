"""Short operational scope and the sole safe satisfaction model payload.

Public projection checks do not replace current Source authorization. Only the
explicit internal no-user path expands own frozen bytes after Run authorization.
"""

from typing import Literal

from fastapi import HTTPException
from pydantic import Field, TypeAdapter, model_validator

from app.ai.satisfaction_contract import SHA, UTC, UUID, CaseMetadata, Date, SafeSnapshot, SatisfactionSource, ScopeKind, StrictModel
from app.ai.satisfaction_draft import canonical_json, source_hash, validate_source

FEATURE_KEY = "feedback_analysis"
SCOPE_NOTE = "完整已记录评价与全部人工摘录版本；准确评分统计独立于部分模型主题，不代表总体、历史科室、就诊分母、投诉处理或医疗责任。"
MISSING_DATA = (
    "原记录时钟时区未知，未知日期和异常或NULL评分分别保留，不补当前日期或零。",
    "人工隐私及原意核查声明不是匿名保证、事实或专业确认，审核时钟字面量不证明真实发生时间。",
    "未提供投诉工单、处理结果、去重访问分母或总体代表性；医生当前科室不表示评价当时科室。",
)


class SatisfactionContextBinding(StrictModel):
    schema_version: Literal["satisfaction_context_binding_v1"]
    case_id: UUID
    revision: Literal[2]
    source_id: str = Field(max_length=100)
    content_hash: SHA
    case_governance_hash: SHA
    projection_hash: SHA
    collection_digest: SHA
    safe_projection_hash: SHA
    member_manifest_hash: SHA
    scope_kind: ScopeKind
    date_from: Date
    date_to: Date

    @model_validator(mode="after")
    def exact_source_identity(self):
        if self.source_id != f"satisfaction_case:{self.case_id}:{self.content_hash[:12]}":
            raise ValueError("The retained immutable satisfaction identity differs")
        return self


class SatisfactionFrozenCase(CaseMetadata):
    snapshot: None
    safe_snapshot: SafeSnapshot
    safe_projection_hash: SHA
    public_source: SatisfactionSource
    projection_hash: SHA
    frozen_task_view: Literal[True]
    can_record: Literal[False]
    can_review: Literal[False]
    can_revoke: Literal[False]
    raw_content_hash_verification: Literal["protected_full_original_verified_server_side_not_reconstructible_from_safe_view"]

    @model_validator(mode="after")
    def no_protected_body(self):
        if self.review_basis_note is not None or self.revoke_reason is not None or self.status not in {"published", "revoked"} or self.reviewed_at is None or self.reviewed_by is None:
            raise ValueError("Only an original publication with opaque protected anchors may enter a safe task proof")
        if self.status == "published" and self.revision != 2 or self.status == "revoked" and self.revision != 3:
            raise ValueError("A frozen published source requires its exact governance lineage")
        if self.created_at > self.reviewed_at or self.revoked_at is not None and self.reviewed_at > self.revoked_at:
            raise ValueError("Actual server Case governance clocks are inconsistent")
        return self


def selection(values):
    if not isinstance(values, dict) or set(values) - {"satisfaction_case_id", "question"} or "satisfaction_case_id" not in values:
        raise HTTPException(422, "须明确一件完整评价来源，仅可另附问题，不得混入患者、就诊或其他来源")
    try:
        identifier = TypeAdapter(UUID).validate_python(values["satisfaction_case_id"], strict=True)
        if values.get("question") is not None:
            question = values["question"]
            if type(question) is not str or len(question) > 2000 or len(question.encode("utf-8", errors="strict")) > 8000:
                raise ValueError("The exact question exceeds its Unicode or UTF8 bound")
        return identifier
    except (ValueError, TypeError, UnicodeError) as exc:
        raise HTTPException(422, "来源须为规范UUID；可选问题最多2000个Unicode码点和8000字节UTF8") from exc


def binding_for_value(value):
    """Safe proof closure only; protected origin is verified by the Source service."""
    checked = SatisfactionFrozenCase.model_validate(value).model_dump(mode="json")
    if canonical_json(checked) != canonical_json(value):
        raise ValueError("Frozen proof types or fields differ")
    source = validate_source(checked["public_source"])
    safe = source["safe_snapshot"]
    if (
        any(checked[key] != source[key] for key in ("case_id", "source_id", "content_hash", "collection_digest", "safe_projection_hash"))
        or checked["safe_snapshot"] != safe
        or checked["projection_hash"] != source_hash(source)
        or checked["scope_kind"] != safe["scope_kind"]
        or checked["date_from"] != safe["date_from"]
        or checked["date_to"] != safe["date_to"]
        or checked["status"] == "published"
        and checked["governance_hash"] != source["governance_hash"]
    ):
        raise ValueError("The whole safe proof differs from its original publication projection")
    return SatisfactionContextBinding(
        schema_version="satisfaction_context_binding_v1",
        **{key: checked[key] for key in ("case_id", "source_id", "content_hash", "collection_digest", "projection_hash", "safe_projection_hash", "scope_kind", "date_from", "date_to")},
        revision=2,
        case_governance_hash=source["governance_hash"],
        member_manifest_hash=safe["member_manifest_hash"],
    ).model_dump(mode="json")


def source_binding(value):
    bound = SatisfactionContextBinding.model_validate(value).model_dump(mode="json")
    return {key: child for key, child in bound.items() if key != "schema_version"}


def satisfaction_evidence(binding):
    bound = SatisfactionContextBinding.model_validate(binding).model_dump(mode="json")
    return {"source_id": bound["source_id"], "kind": "operational_record", "title": "完整评价与明确选择人工摘录的安全冻结依据", "content": canonical_json({"satisfaction_binding": bound})}


def short_context(binding, snapshot_time):
    bound = SatisfactionContextBinding.model_validate(binding)
    TypeAdapter(UTC).validate_python(snapshot_time, strict=True)
    return {
        "scope": bound.scope_kind,
        "source_domain": "recorded_satisfaction_review_case",
        "department_ids": [],
        "selected_sources": {"satisfaction_case_id": bound.case_id},
        "satisfaction_binding": bound.model_dump(mode="json"),
        "scope_note": SCOPE_NOTE,
        "missing_data": list(MISSING_DATA),
        "truncated_sources": [],
        "snapshot_time": snapshot_time,
    }


def satisfaction_context(db, user, values):
    from app.ai.context import ContextBundle
    from app.ai.satisfaction_sources import authorize_case, frozen_case_proof, utc_text, utcnow

    identifier = selection(values)
    authorize_case(db, user, identifier, execution=True)
    proof = frozen_case_proof(db, identifier)
    binding = binding_for_value(proof)
    return ContextBundle(data=short_context(binding, utc_text(utcnow())), evidence=[satisfaction_evidence(binding)], department_ids=set())


def expand_context(db, context, *, user=None, current=False, locking=False):
    from app.ai.satisfaction_sources import authorize_case, frozen_case_proof

    try:
        bound = SatisfactionContextBinding.model_validate(context["satisfaction_binding"])
        binding = bound.model_dump(mode="json")
        if canonical_json(context) != canonical_json(short_context(binding, context["snapshot_time"])):
            raise ValueError("A mixed context cannot enter the satisfaction evidence task")
        if current and user is None:
            raise ValueError("A current execution needs an actual authorized actor")
        if user is not None:
            # Even a Super user must use the separate, caller-authorized internal
            # no-user path for frozen auditing. execution=False never skips live
            # Source authority, membership or publication for ordinary history.
            authorize_case(db, user, bound.case_id, binding=source_binding(binding), locking=locking, execution=current)
        proof = frozen_case_proof(db, bound.case_id)
        if binding_for_value(proof) != binding or context["snapshot_time"] < proof["reviewed_at"]:
            raise ValueError("Original publication or task capture clock differs")
        return {**context, "satisfaction_source": proof["public_source"], "satisfaction_case": proof}
    except HTTPException as exc:
        if exc.status_code == 403:
            raise
        raise HTTPException(409, "评价完整原件、当前范围或冻结任务绑定无法核对") from exc
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "评价完整原件、当前范围或冻结任务绑定无法核对") from exc


def public_payload(data):
    """Pure minimization after expand_context(current=True), not an authorization."""
    if not isinstance(data, dict) or set(data) != {"input", "context", "tools", "evidence"} or data["tools"] != {}:
        raise ValueError("Only one source-bound satisfaction input and no tools are allowed")
    context = data["context"]
    bound = SatisfactionContextBinding.model_validate(context["satisfaction_binding"])
    binding = bound.model_dump(mode="json")
    expected = short_context(binding, context["snapshot_time"])
    if set(context) != {*expected, "satisfaction_source", "satisfaction_case"} or canonical_json({key: context[key] for key in expected}) != canonical_json(expected):
        raise ValueError("The model request contains mixed scope or private fields")
    proof = context["satisfaction_case"]
    if (
        selection(data["input"]) != bound.case_id
        or data["evidence"] != [satisfaction_evidence(binding)]
        or binding_for_value(proof) != binding
        or proof["status"] != "published"
        or context["satisfaction_source"] != proof["public_source"]
    ):
        raise ValueError("The safe model source differs from its original published task binding")
    return {"satisfaction_source": validate_source(context["satisfaction_source"]), "question": data["input"].get("question")}
