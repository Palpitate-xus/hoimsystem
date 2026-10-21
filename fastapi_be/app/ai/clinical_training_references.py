"""Actual current, finite manual-training references; never native-source bypass.

All selected metadata and current actors precede any reference content. Alternate
knowledge/publication lock order uses NOWAIT and refuses a busy dependency.
Callers retain the transaction until their final source check and commit.
"""

import datetime as dt
import hashlib

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import LargeBinary, cast, func
from sqlalchemy.exc import SQLAlchemyError

from app.ai import clinical_training_contract as c
from app.ai import clinical_training_reference_contract as rc
from app.ai.clinical_training_write_guard import lock_training_write
from app.ai.document_evidence_models import AIDocumentKnowledgePublication
from app.ai.models import AIKnowledgeDocument
from app.models import User

METADATA_COLUMNS = tuple(rc.KnowledgeMetadata.model_fields)


def utc_text(value):
    if not isinstance(value, dt.datetime) or value.tzinfo is not None:
        raise ValueError("A stored naive UTC microsecond clock is required")
    return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def actor_packet(row):
    return dict(user_id=row.user_id, user_role=row.user_role, token_invalid_before=utc_text(row.token_invalid_before) if row.token_invalid_before is not None else None)


def reference_state_hash(value):
    return c.content_hash([dict(metadata=item.metadata.model_dump(), author=item.author.model_dump(), reviewer=item.reviewer.model_dump()) for item in value.references])


def _capture_current(db, actor_id, lesson_id, identifiers, *, now=None, expected_references=None, expected_state_hash=None, metadata_only=False):
    """Internal: current lesson/submission authority must be established first."""
    try:
        lesson_id = TypeAdapter(c.Identifier).validate_python(lesson_id, strict=True)
        if type(identifiers) is not list or not 1 <= len(identifiers) <= 2048 or identifiers != sorted(set(identifiers)):
            raise ValueError("The exact explicit sorted unique reference union is required")
        for key in identifiers:
            TypeAdapter(c.Identifier).validate_python(key, strict=True)
        clock = utc_text(now if now is not None else dt.datetime.now(dt.UTC).replace(tzinfo=None))
        # CAST counts NUL and supplementary UTF8 bytes without returning content.
        with db.no_autoflush:
            rows = db.query(*(getattr(AIKnowledgeDocument, key) for key in METADATA_COLUMNS), func.length(cast(AIKnowledgeDocument.content, LargeBinary)).label("content_size")).filter(AIKnowledgeDocument.document_id.in_(identifiers)).order_by(AIKnowledgeDocument.document_id).populate_existing().with_for_update(read=True, nowait=True).all()
            if [row.document_id for row in rows] != identifiers:
                raise HTTPException(404, "明确选择的培训参考版本不存在")
            # The immutable FK remains authoritative after URI/kind are erased.
            native = db.query(AIDocumentKnowledgePublication.publication_id).filter(AIDocumentKnowledgePublication.knowledge_document_id.in_(identifiers)).with_for_update(read=True, nowait=True).first()
            if native is not None:
                raise HTTPException(403, "当前课程仅支持独立手工全局培训参考，原文关联须使用其专属授权流程")
        metadata = []
        for row in rows:
            values = {key: getattr(row, key) for key in METADATA_COLUMNS}
            for key in ("effective_from", "effective_to", "reviewed_at", "create_time"):
                if values[key] is not None:
                    values[key] = utc_text(values[key])
            item = rc.KnowledgeMetadata.model_validate(values, strict=True)
            if type(row.content_size) is not int or not 1 <= row.content_size <= 65535:
                raise ValueError("The actual whole reference exceeds its original TEXT limit")
            if item.reviewed_at > clock or item.effective_from is not None and item.effective_from > clock or item.effective_to is not None and item.effective_to <= clock:
                raise HTTPException(403, "明确培训参考当前尚未生效或已经失效")
            metadata.append(item)
        actor_ids = sorted({key for item in metadata for key in (item.created_by, item.reviewed_by)})
        with db.no_autoflush:
            actors = db.query(User.user_id, User.user_role, User.token_invalid_before).filter(User.user_id.in_(actor_ids)).order_by(User.user_id).populate_existing().with_for_update(read=True, nowait=True).all()
        if [row.user_id for row in actors] != actor_ids or any(row.user_role != "super_admin" for row in actors):
            raise HTTPException(403, "培训参考的作者或审核人当前不具备治理角色")
        actor_values = {row.user_id: actor_packet(row) for row in actors}
        state = [dict(metadata=item.model_dump(), author=actor_values[item.created_by], reviewer=actor_values[item.reviewed_by]) for item in metadata]
        if expected_state_hash is not None and c.content_hash(state) != expected_state_hash:
            raise HTTPException(409, "课程所绑定的参考元数据或账户授权时刻已变化，未读取任何参考正文")
        if expected_references is not None:
            for item, expected in zip(metadata, expected_references, strict=True):
                if c.whole(item) != c.whole(expected.metadata) or actor_values[item.created_by] != expected.author.model_dump() or actor_values[item.reviewed_by] != expected.reviewer.model_dump():
                    raise HTTPException(409, "受审参考元数据或作者/审核人授权时刻已变化，未读取参考正文")
        if metadata_only:
            return dict(reference_ids=identifiers, state_hash=c.content_hash(state), checked_at=clock)
        # Every member has passed current metadata/actor checks before the first
        # actual content column is returned. No identity-map body is trusted.
        with db.no_autoflush:
            bodies = db.query(AIKnowledgeDocument.document_id, AIKnowledgeDocument.content).filter(AIKnowledgeDocument.document_id.in_(identifiers)).order_by(AIKnowledgeDocument.document_id).populate_existing().with_for_update(read=True, nowait=True).all()
        if [row.document_id for row in bodies] != identifiers:
            raise ValueError("A locked selected reference disappeared")
        snapshot = rc.TrainingReferenceSnapshot(schema_version="clinical_training_reference_snapshot_v1", lesson_id=lesson_id, captured_by=actor_id, captured_at=clock, selection_basis="exact_union_of_all_private_question_reference_ids", publication_claim="stored_manual_training_publication_and_current_actors_not_independent_content_truth", references=[rc.TrainingReference(metadata=item, author=rc.ReferenceActor.model_validate(actor_values[item.created_by], strict=True), reviewer=rc.ReferenceActor.model_validate(actor_values[item.reviewed_by], strict=True), content=row.content, content_utf8_sha256=hashlib.sha256(row.content.encode("utf-8", errors="strict")).hexdigest()) for item, row in zip(metadata, bodies, strict=True)])
        c.whole(snapshot)
        return snapshot
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(409, "培训参考或关联正在变更，请刷新后重试") from exc
    except (ValueError, TypeError, KeyError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "完整培训参考的元数据、原文或当前绑定不满足明确范围") from exc


def capture_for_author(db, user, lesson_id, identifiers):
    actor = lock_training_write(db, user, governance=True)
    return _capture_current(db, actor.user_id, lesson_id, identifiers)


def verify_current(db, actor_id, value):
    """Internal after lesson header authority; frozen bytes never renew access."""
    try:
        frozen = rc.TrainingReferenceSnapshot.model_validate(c.parse_packet(value), strict=True)
        fresh = _capture_current(db, actor_id, frozen.lesson_id, [item.metadata.document_id for item in frozen.references], expected_references=frozen.references)
        if [c.whole(item) for item in fresh.references] != [c.whole(item) for item in frozen.references]:
            raise HTTPException(409, "受审培训参考原文、元数据或作者/审核人授权时刻已变化，须新建课程版本")
        return frozen
    except (ValueError, TypeError, KeyError, UnicodeError, ValidationError) as exc:
        raise HTTPException(409, "完整冻结培训参考已经损坏") from exc
