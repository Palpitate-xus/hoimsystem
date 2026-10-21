"""Current SQL leaflet authorization before constructing a private task seed.

The returned seed is internal and must be persisted once in the RunArtifact.
It is absent from ContextBundle, model data and public Source. A fresh read of
an existing task must reuse its stored seed rather than creating a new one.
"""

import secrets

from fastapi import HTTPException

from app.ai import document_evidence_contract as d
from app.ai.drug_label_context_contract import binding_for_projection, checked_context, evidence_for_binding, expand_public_context, selection, short_context
from app.ai.drug_label_projection import project_source


def prepare_context(db, user, values, *, mapping_seed=None):
    from app.ai.context import ContextBundle
    from app.ai.drug_label_sources import source_current, utcnow

    try:
        request = selection(values)
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(422, "须明确规范说明书绑定UUID，可另附最多2000码点及8000字节的原样问题") from exc
    record = source_current(db, user, request.drug_label_source_binding_id, execution=True)
    seed = secrets.token_hex(32) if mapping_seed is None else mapping_seed
    try:
        source = project_source(record, secret=seed)
        binding = binding_for_projection(source)
        context = short_context(binding, d.utc_text(utcnow()))
        # Refuse an unusable complete wrapper before Run/Artifact persistence.
        expand_public_context(context, source)
        bundle = ContextBundle(data=context, evidence=evidence_for_binding(binding), department_ids=set())
        return bundle, record, source, seed
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "完整说明书投影、任务时钟或私有映射依据无法核对，未创建任务") from exc


def expand_context(db, user, context, *, mapping_seed, frozen_audit=False):
    from app.ai.drug_label_sources import source_current

    try:
        if type(frozen_audit) is not bool:
            raise ValueError("Frozen audit must be explicit boolean")
        binding = checked_context(context)
        # Current Source gate/actor/signer/SKU/original reads always precede
        # returning any full original. Only Source's actual Super audit path
        # may reconstruct an earlier publication without live eligibility.
        record = source_current(db, user, binding.source.source_binding_id, audit_only=frozen_audit, execution=not frozen_audit)
        source = project_source(record, secret=mapping_seed, frozen=frozen_audit)
        return expand_public_context(context, source), record, source
    except HTTPException:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "说明书当前来源、冻结任务或原映射摘要无法核对") from exc
