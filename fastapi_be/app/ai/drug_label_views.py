"""Bound complete authorized task wire views without exposing the private seed."""

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from app.ai import drug_label_storage as storage
from app.ai.context import context_metadata
from app.ai.drug_label_context import prepare_context
from app.ai.drug_label_context_contract import expand_public_context
from app.ai.drug_label_draft import SYSTEM_PROMPT, bounded_json
from app.ai.drug_label_runtime import FEATURE_KEY, describe_drug_label_run
from app.ai.drug_label_task_view_contract import DrugLabelPreview, DrugLabelRunDetail, DrugLabelRunSummary, DrugLabelRunTrace, checked_wire
from app.ai.governance import digest
from app.ai.models import AIPromptVersion, AIProvider


def response(data):
    """The whole HTTP envelope retains its independent 8MiB bound."""
    value = {"code": 200, "msg": "success", "data": jsonable_encoder(data)}
    try:
        bounded_json(value)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise HTTPException(409, "完整说明书响应超过上限或不能逐字核对，未截断返回") from exc
    return value


def preview(db, user, values):
    from app.ai.runtime import authorized_feature

    spec, config = authorized_feature(db, user, FEATURE_KEY)
    bundle, record, public, _private_seed = prepare_context(db, user, values)
    prompt = spec.task_prompt
    if config is not None and config.active_prompt_id:
        row = db.query(AIPromptVersion).filter_by(prompt_id=config.active_prompt_id).populate_existing().with_for_update(read=True).one_or_none()
        if row is None or row.feature_key != FEATURE_KEY:
            raise HTTPException(409, "说明书当前Prompt已删除或改绑")
        prompt = row.task_prompt
    provider = db.get(AIProvider, config.provider_id) if config is not None and config.provider_id is not None else None
    metadata = context_metadata(bundle)
    metadata.update(
        feature_revision=config.revision if config is not None else 1,
        validation_status=config.validation_status if config is not None else "unreviewed",
        tool_fingerprint=digest({}),
        instructions_digest=storage.instructions_digest(SYSTEM_PROMPT, prompt),
        model_version=provider.model if provider is not None else "unconfigured",
    )
    data = {"context": expand_public_context(bundle.data, public), "metadata": metadata, "evidence": bundle.evidence, "drug_label_source_record": record.model_dump(mode="json")}
    return checked_wire(data, DrugLabelPreview).model_dump(mode="json")


def run_view(db, user, run, include_result=True, *, frozen_audit=False):
    data = describe_drug_label_run(db, user, run, include_result, frozen_audit=frozen_audit)
    model = DrugLabelRunDetail if include_result else DrugLabelRunSummary
    return checked_wire(jsonable_encoder(data), model).model_dump(mode="json")


def trace_view(db, user, run):
    stored = storage.authorize_drug_label_run(db, user, run, frozen_audit=True)
    data = run_view(db, user, stored.run, frozen_audit=True)
    raw = {name: getattr(stored.run, name) for name in ("input_json", "evidence_json", "context_metadata_json")}
    if any(len(value.encode("utf-8", errors="strict")) > 65535 for value in raw.values()):
        raise HTTPException(409, "说明书原任务TEXT超出真实存储边界，未返回截断审计")
    data.update(requested_by=stored.run.requested_by, provider_id=stored.run.provider_id, snapshot_complete=True, frozen_request=stored.snapshot, raw_frozen_json=raw)
    return checked_wire(data, DrugLabelRunTrace).model_dump(mode="json")
