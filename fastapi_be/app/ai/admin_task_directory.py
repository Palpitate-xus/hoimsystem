"""All-domain technical management never reads private Task or Source text."""

import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, exists, func, literal, or_, select, union_all

from app.ai.admin_read_snapshot import admin_read_snapshot
from app.ai.catalog import FEATURE_BY_KEY
from app.ai.governance import get_spec
from app.ai.models import AIFeedback, AIRun
from app.ai.native_task_routing import _domains

DOMAIN_FEATURES = {
    "charge": "charge_reconciliation",
    "satisfaction": "feedback_analysis",
    "document": "guideline_ingestion",
    "drug_label": "drug_label_extraction",
    "document_change": "guideline_change_review",
    "research_cohort": "research_cohort",
    "deidentification": "deidentification",
    "operations_support": "operations_support",
    "clinical_training": "clinical_training",
    "rca": "incident_rca",
    "infection": "infection_cluster",
    "research_variables": "research_extraction",
}
NativeDomain = Literal["charge", "satisfaction", "document", "drug_label", "document_change", "research_cohort", "deidentification", "operations_support", "clinical_training", "rca", "infection", "research_variables"]
Positive = Annotated[int, Field(strict=True, ge=1)]
Nonnegative = Annotated[int, Field(strict=True, ge=0)]
RUN_FIELDS = ("run_id", "feature_key", "status", "requested_by", "provider_id", "provider_revision", "prompt_version", "preview", "create_time", "start_time", "finish_time")


class AdminTaskMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["global_ai_task_technical_v1"] = "global_ai_task_technical_v1"
    run_id: Annotated[str, Field(min_length=1, max_length=36)]
    feature_key: str | None
    feature_name: str | None
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "invalid"]
    native_domains: Annotated[list[NativeDomain], Field(max_length=12)]
    native_identity_state: Literal["unique", "unproven", "conflicting", "invalid"]
    native_feature_key: str | None
    feature_matches_native_contract: bool | None
    requested_by: Positive | None
    provider_id: Positive | None
    provider_revision: Positive | None
    prompt_version: Nonnegative | None
    preview: bool | None
    create_time: datetime.datetime | None
    start_time: datetime.datetime | None
    finish_time: datetime.datetime | None
    feedback_count: Nonnegative
    usage_verification: Literal["not_verified"] = "not_verified"
    input_tokens: None = None
    output_tokens: None = None


def _positive(value):
    return value if type(value) is int and value > 0 else None


def _conditions(domains, *, feature_key, status, requested_by, outcome):
    conditions = []
    if feature_key is not None:
        get_spec(feature_key)
        anchors = [(domain, exists().where(model.run_id == AIRun.run_id).correlate(AIRun)) for domain, model, _ in domains]
        none = ~or_(*(anchor for _, anchor in anchors))
        canonical = [anchor for domain, anchor in anchors if DOMAIN_FEATURES[domain] == feature_key]
        conditions.append(or_(*canonical, and_(AIRun.feature_key == feature_key, none)))
    if status is not None:
        conditions.append(AIRun.status == status)
    if requested_by is not None:
        conditions.append(AIRun.requested_by == requested_by)
    if outcome is not None:
        conditions.append(exists().where(AIFeedback.run_id == AIRun.run_id, AIFeedback.outcome == outcome).correlate(AIRun))
    return conditions


def _native_headers(snapshot, ids, domains):
    if not ids:
        return {}
    # Joining the actual parent returns its canonical PK even under MySQL
    # ai_ci aliases. A child alias or conflicting owner is visibly invalid,
    # never lost by a Python string-key lookup or promoted to generic access.
    statements = [select(AIRun.run_id.label("parent_id"), literal(domain).label("domain"), model.run_id.label("artifact_run_id"), model.requested_by).select_from(AIRun).join(model, model.run_id == AIRun.run_id).where(AIRun.run_id.in_(ids)) for domain, model, _ in domains]
    result = {}
    for row in snapshot.execute(union_all(*statements)):
        result.setdefault(row.parent_id, []).append((row.domain, row.artifact_run_id, row.requested_by))
    return result


def _metadata(header, anchors, feedback_count):
    names = sorted({row[0] for row in anchors})
    state = "unproven" if not anchors else "conflicting" if len(anchors) > 1 else "unique"
    if len(anchors) == 1 and (anchors[0][1] != header["run_id"] or _positive(anchors[0][2]) is None or anchors[0][2] != header["requested_by"]):
        state = "invalid"
    native_feature = DOMAIN_FEATURES[names[0]] if len(names) == 1 else None
    spec = FEATURE_BY_KEY.get(header["feature_key"])
    return AdminTaskMetadata(
        run_id=header["run_id"],
        feature_key=spec.key if spec else None,
        feature_name=spec.name if spec else None,
        status=header["status"] if header["status"] in {"queued", "running", "succeeded", "failed", "cancelled"} else "invalid",
        native_domains=names,
        native_identity_state=state,
        native_feature_key=native_feature,
        feature_matches_native_contract=header["feature_key"] == native_feature if native_feature else None,
        requested_by=_positive(header["requested_by"]),
        provider_id=_positive(header["provider_id"]),
        provider_revision=_positive(header["provider_revision"]),
        prompt_version=header["prompt_version"] if type(header["prompt_version"]) is int and header["prompt_version"] >= 0 else None,
        preview=bool(header["preview"]) if type(header["preview"]) is int and header["preview"] in {0, 1} else None,
        create_time=header["create_time"], start_time=header["start_time"], finish_time=header["finish_time"],
        feedback_count=feedback_count,
    ).model_dump(mode="json")


def task_directory(db, user, *, feature_key=None, status=None, requested_by=None, outcome=None, page=1, page_size=30):
    domains = _domains()
    if {domain for domain, _, _ in domains} != set(DOMAIN_FEATURES):
        raise RuntimeError("Every actual native domain requires an explicit technical feature mapping")
    conditions = _conditions(domains, feature_key=feature_key, status=status, requested_by=requested_by, outcome=outcome)
    with admin_read_snapshot(db, user) as snapshot:
        total = snapshot.scalar(select(func.count()).select_from(AIRun).where(*conditions))
        headers = snapshot.execute(select(*(getattr(AIRun, name) for name in RUN_FIELDS)).where(*conditions).order_by(AIRun.create_time.desc(), AIRun.run_id).offset((page - 1) * page_size).limit(page_size)).mappings().all()
        ids = [header["run_id"] for header in headers]
        anchors = _native_headers(snapshot, ids, domains)
        counts = dict(snapshot.execute(select(AIRun.run_id, func.count(AIFeedback.feedback_id)).join(AIFeedback, AIFeedback.run_id == AIRun.run_id).where(AIRun.run_id.in_(ids)).group_by(AIRun.run_id)).all()) if ids else {}
        data = [_metadata(header, anchors.get(header["run_id"], []), counts.get(header["run_id"], 0)) for header in headers]
    return {"code": 200, "msg": "success", "data": data, "total": total, "page": page, "page_size": page_size}
