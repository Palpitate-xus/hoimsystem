"""Current opaque dispatch identity, never Source authority or a retained lock.

MySQL uses one independent short READ COMMITTED connection. Only domain tags
and immutable run/source/owner IDs are returned; no Task or Artifact TEXT, Gate,
User or Run locks cross this classifier. The selected domain must subsequently
perform its complete original Gate -> actor -> Source -> Run authorization.
"""

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import inspect, literal, select, union_all

_STAGED = "native_task_routing_staged_identities"


@dataclass(frozen=True)
class NativeTaskIdentity:
    domain: str
    run_id: str
    source_id: str
    requested_by: int


def _domains():
    from app.ai.charge_reconciliation_run_models import AIChargeRunArtifact
    from app.ai.document_extraction_models import AIDocumentExtractionRunAnchor
    from app.ai.drug_label_run_models import AIDrugLabelRunArtifact
    from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact
    from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact

    return (
        ("charge", AIChargeRunArtifact, "case_snapshot_id"),
        ("satisfaction", AISatisfactionRunArtifact, "case_id"),
        ("document", AIDocumentExtractionRunAnchor, "original_id"),
        ("drug_label", AIDrugLabelRunArtifact, "source_binding_id"),
        ("rca", AIRcaEvidenceRunArtifact, "case_id"),
    )


def opaque_run_id(value):
    if type(value) is str:
        return value
    state = inspect(value, raiseerr=False)
    if state is not None:
        return state.identity[0] if state.identity else state.dict.get("run_id")
    return getattr(value, "run_id", None)


def remember_staged_identity(db, artifact):
    """Called only by the real writer after its own Artifact INSERT/flush."""
    for domain, model, source_key in _domains():
        if isinstance(artifact, model):
            value = NativeTaskIdentity(domain, artifact.run_id, getattr(artifact, source_key), artifact.requested_by)
            transaction = db.get_transaction()
            if transaction is None:
                raise RuntimeError("A staged native identity requires its actual SQL transaction")
            db.info.setdefault(_STAGED, {})[(domain, value.run_id)] = (transaction, value)
            return
    raise TypeError("Only a real supported native Artifact can register an own uncommitted identity")


def locate_native_task(db, value):
    """Detect erased markers and ambiguous cross-domain anchors without authority.

    SQLite reuses the caller connection. An extra StaticPool Session could roll
    back its transaction. A writer's own uncommitted anchor is accepted only in
    the exact registered transaction and re-read as the same three SQL columns;
    a rolled-back savepoint or a completed transaction cannot leave a fake hint.
    """
    identifier = opaque_run_id(value)
    if db is None or type(identifier) is not str:
        return None
    domains = _domains()
    statements = [select(literal(domain), model.run_id, getattr(model, key), model.requested_by).where(model.run_id == identifier) for domain, model, key in domains]
    statement = union_all(*statements)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as connection:
                rows = connection.execute(statement).all()
        else:
            rows = db.execute(statement).all()
        found = {NativeTaskIdentity(*tuple(row)) for row in rows}
        for domain, model, key in domains:
            own = db.info.get(_STAGED, {}).get((domain, identifier))
            if own is None or own[0] is not db.get_transaction() or own[0] is None:
                continue
            row = db.execute(select(model.run_id, getattr(model, key), model.requested_by).where(model.run_id == identifier)).one_or_none()
            if row is None:
                continue
            current = NativeTaskIdentity(domain, *tuple(row))
            if current != own[1]:
                raise HTTPException(409, "本事务原生任务技术身份已改变，未分派执行")
            found.add(current)
    if len(found) > 1:
        raise HTTPException(409, "同一任务存在互相矛盾的原生域锚点，未分派或降级")
    if not found:
        return None
    identity = found.pop()
    if identity.run_id != identifier or type(identity.source_id) is not str or not identity.source_id or type(identity.requested_by) is not int or identity.requested_by < 1:
        raise HTTPException(409, "原生任务技术身份损坏，未分派或降级")
    return identity
