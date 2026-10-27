"""Opaque native identity and orphan-marker rejection, never Source authority."""

from fastapi import HTTPException
from sqlalchemy import case, or_, select

from app.ai import rca_evidence_task_contract as t
from app.ai.models import AIRun
from app.ai.native_task_routing import locate_native_task, opaque_run_id
from app.sql_json import json_extract, json_type, json_valid

# Presence includes JSON null. A damaged native package never becomes generic.
INPUT_PATHS = (
    "$.rca_evidence_case_id",
    "$.input.rca_evidence_case_id",
    "$.payload.input.rca_evidence_case_id",
    "$.payload.context.rca_evidence_binding",
    "$.payload.context.rca_evidence_source",
    "$.payload.context.selected_sources.rca_evidence_case_id",
)
RESULT_PATHS = ("$.rca_evidence_draft", "$.rca_evidence_binding")


def marker_predicate(db):
    """The same body-free marker expression qualifies queue candidates."""
    def safe(column):
        return case((json_valid(column) == 1, column), else_="{}")

    def extract(column, path):
        return json_extract(safe(column), path)

    def present(column, path):
        if db.get_bind().dialect.name in {"mysql", "mariadb"}:
            return json_type(extract(column, path)).is_not(None)
        return json_type(safe(column), path).is_not(None)

    marker = or_(
        AIRun.feature_key == t.FEATURE_KEY,
        *(present(AIRun.input_json, path) for path in INPUT_PATHS),
        *(present(AIRun.result_json, path) for path in RESULT_PATHS),
        extract(AIRun.input_json, "$.schema_version") == "rca_evidence_task_snapshot_v1",
        extract(AIRun.input_json, "$.payload.context.source_domain") == t.SOURCE_DOMAIN,
        extract(AIRun.result_json, "$.schema_version") == "rca_evidence_result_ref_v1",
        extract(AIRun.evidence_json, "$[0].kind") == "rca_evidence_case",
    )
    return case((marker, True), else_=False)


def marker_statement(db, identifier):
    return select(marker_predicate(db)).where(AIRun.run_id == identifier)


def is_rca_task(db, value):
    identifier = opaque_run_id(value)
    if db is None or type(identifier) is not str:
        return False
    identity = locate_native_task(db, identifier)
    if identity is not None:
        return identity.domain == "rca"
    # A current short connection prevents an old RR view hiding a committed
    # orphan marker. It returns one bool, no body, no lock, no authorization.
    statement = marker_statement(db, identifier)
    with db.no_autoflush:
        bind = db.get_bind()
        if bind.dialect.name in {"mysql", "mariadb"}:
            with getattr(bind, "engine", bind).connect().execution_options(isolation_level="READ COMMITTED") as connection:
                marker = connection.scalar(statement)
        else:
            marker = db.scalar(statement)
        marker = marker or db.scalar(statement)
    if marker:
        raise HTTPException(409, "RCA原生标记缺少唯一实际Artifact，未读取正文或降级通用任务")
    return False


def guard_rca_task(db, user, value, *, frozen_audit=False):
    if not is_rca_task(db, value):
        return False
    from app.ai.rca_evidence_storage import load_task

    load_task(db, user, value, frozen_audit=frozen_audit)
    return True


def is_located_rca_task(db, value):
    """Route own technical exceptions without probing unrelated anchors first.

    A missing own anchor is not a generic authorization. The caller must still
    enter the existing directory Gates and private-read guard, which rejects
    orphan RCA markers before reading any Task body.
    """
    from app.ai.rca_evidence_storage import locate_artifact

    return locate_artifact(db, value) is not None and is_rca_task(db, value)
