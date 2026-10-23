"""Only this domain's three opaque columns before any mixed-domain Gate.

This is dispatch identity, not retained locks or Source authorization. A miss
must follow the existing other-domain guard order; no all-domain UNION is run
before the Billing Gate merely to decide whether a task belongs to78.
"""

from sqlalchemy import select

from app.ai.infection_cluster_run_models import AIInfectionRunArtifact as Artifact
from app.ai.infection_cluster_task_contract import FEATURE_KEY


def opaque(db, value):
    from app.ai.infection_cluster_task_storage import _run_id

    rid = _run_id(value)
    if db is None or type(rid) is not str:
        return None
    # A real writer records this hint only after INSERT, in its actual still
    # open Source-Gate transaction. Re-read exactly the same three columns.
    own = db.info.get("native_task_routing_staged_identities", {}).get(("infection", rid))
    statement = select(Artifact.run_id, Artifact.scenario_id, Artifact.requested_by).where(Artifact.run_id == rid)
    with db.no_autoflush:
        bind = db.get_bind()
        if own is not None and own[0] is db.get_transaction() and own[0] is not None:
            return db.execute(statement).one_or_none()
        if bind.dialect.name in {"mysql", "mariadb"}:
            engine = getattr(bind, "engine", bind)
            with engine.connect().execution_options(isolation_level="READ COMMITTED") as conn:
                return conn.execute(statement).one_or_none()
        return db.execute(statement).one_or_none()


def is_own_task(db, value):
    if opaque(db, value) is not None:
        # Only a positive own-domain hit may inspect all-domain contradictory
        # immutable anchors. That query is still identity, never authority.
        from app.ai.native_task_routing import locate_native_task

        found = locate_native_task(db, value)
        return found is not None and found.domain == "infection"
    if type(value) is str:
        return False
    loaded = vars(value)
    return loaded.get("feature_key") == FEATURE_KEY or any(
        type(loaded.get(field)) is str and any(marker in loaded[field] for marker in ("infection_local_frozen_task_v1", "infection_statistics_result_pointer_v1", "infection_cluster_scenario_id"))
        for field in ("input_json", "evidence_json", "context_metadata_json", "result_json")
    )
