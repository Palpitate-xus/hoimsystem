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
    from app.ai.clinical_training_run_models import AITrainingRunArtifact
    from app.ai.deidentification_run_models import AIDeidentificationRunSource
    from app.ai.document_change_run_models import AIDocumentChangeRunArtifact
    from app.ai.document_extraction_models import AIDocumentExtractionRunAnchor
    from app.ai.drug_label_run_models import AIDrugLabelRunArtifact
    from app.ai.infection_cluster_run_models import AIInfectionRunArtifact
    from app.ai.operations_support_run_models import AIOperationsRunArtifact
    from app.ai.rca_evidence_run_models import AIRcaEvidenceRunArtifact
    from app.ai.research_cohort_artifact_models import AIResearchCohortRunArtifact
    from app.ai.research_variables_run_models import AIResearchVariableRunArtifact
    from app.ai.satisfaction_artifact_models import AISatisfactionRunArtifact

    return (
        ("charge", AIChargeRunArtifact, "case_snapshot_id"),
        ("satisfaction", AISatisfactionRunArtifact, "case_id"),
        ("document", AIDocumentExtractionRunAnchor, "original_id"),
        ("drug_label", AIDrugLabelRunArtifact, "source_binding_id"),
        ("document_change", AIDocumentChangeRunArtifact, "scope_id"),
        ("research_cohort", AIResearchCohortRunArtifact, "case_id"),
        ("deidentification", AIDeidentificationRunSource, "case_id"),
        ("operations_support", AIOperationsRunArtifact, "case_id"),
        ("clinical_training", AITrainingRunArtifact, "submission_id"),
        ("rca", AIRcaEvidenceRunArtifact, "case_id"),
        ("infection", AIInfectionRunArtifact, "scenario_id"),
        ("research_variables", AIResearchVariableRunArtifact, "batch_id"),
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
    back its transaction. MySQL unions that fresh independent view with this
    Session's actual SQL, including direct flushed inserts without a process
    hint. Registered writer hints are additionally checked against actual SQL;
    a rolled-back savepoint or completed transaction cannot invent an anchor.
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
        if bind.dialect.name in {"mysql", "mariadb"}:
            found.update(NativeTaskIdentity(*tuple(row)) for row in db.execute(statement).all())
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


def queue_identity_condition(db):
    """Retain ambiguous/orphan anchors without letting them block every poll.

    This is only a technical SQL qualification, not Source authorization or a
    claim that an interrupted/corrupt task incurred no paid model usage.
    """
    from sqlalchemy import and_, case, exists, func, or_

    from app.ai.models import AIRun
    from app.ai.rca_evidence_dispatch import marker_predicate as rca_marker
    from app.ai.research_variables_task_routing import marker_predicate as variable_marker

    domains = _domains()
    anchors = sum(case((exists().where(model.run_id == AIRun.run_id).correlate(AIRun), 1), else_=0) for _, model, _ in domains)
    # The actual unique anchor retains priority even if a mutable marker now
    # names another domain. No anchor plus a native76/77 marker is never a
    # generic candidate: keep it intact for technical inspection, without
    # inventing a terminal state, usage receipt or repeated maintenance cost.
    no_orphan = and_(~func.coalesce(variable_marker(db), False), ~func.coalesce(rca_marker(db), False))
    # A changed mutable status must not replay a real prior claim/dispatch or
    # consume all128 maintenance slots on every poll. These are technical SQL
    # predicates only: no Source grant, Task body projection or zero receipt.
    phase_names = (
        "claim_event_id",
        "claim_lease",
        "claimed_at",
        "dispatch_event_id",
        "dispatched_at",
        "usage_event_id",
        "receipt_event_id",
        "accept_event_id",
        "accepted_lease",
        "accepted_at",
        "lease_token",
        "result_hash",
        "result_bytes",
    )
    advanced = []
    for _, model, _ in domains:
        columns = [getattr(model, name) for name in phase_names if hasattr(model, name)]
        if columns:
            advanced.append(exists().where(model.run_id == AIRun.run_id, or_(*(column.is_not(None) for column in columns))).correlate(AIRun))
    pristine = and_(
        func.hex(AIRun.status) == "717565756564",
        func.hex(AIRun.result_json) == "7B7D",
        AIRun.lease_token.is_(None),
        AIRun.start_time.is_(None),
        AIRun.finish_time.is_(None),
        AIRun.latency_ms.is_(None),
        AIRun.error_code.is_(None),
        AIRun.error_message.is_(None),
        AIRun.input_tokens == 0,
        AIRun.output_tokens == 0,
        ~or_(*advanced),
    )
    return and_(anchors <= 1, or_(and_(anchors == 1, pristine), and_(anchors == 0, no_orphan)))
