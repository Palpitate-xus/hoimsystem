"""Real local implementation governance; no fake HTTP provider or automatic enable.

The domain Gate precedes current actors, Definition/Department/profile and
configuration rows. Profile publication records a technical independent review.
It never creates a patient-purpose grant or proves a clinical validation claim.
"""

import json
import uuid

from fastapi import HTTPException
from pydantic import TypeAdapter
from sqlalchemy.orm.attributes import flag_modified

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as source_input
from app.ai import infection_cluster_profile_input as i
from app.ai import infection_cluster_registry as r
from app.ai import infection_cluster_scenario as scenario
from app.ai import infection_cluster_scenario_input as scenario_input
from app.ai import infection_cluster_statistics_contract as k
from app.ai.infection_cluster_implementation import implementation_descriptor
from app.ai.infection_cluster_profile_models import AIInfectionLocalProfile, AIInfectionLocalSelection
from app.ai.infection_cluster_write_guard import current, lock_gate
from app.ai.models import AIFeatureConfig

KEY = "infection_cluster"
PROFILE_TECHNICAL = tuple(col.name for col in AIInfectionLocalProfile.__table__.columns if col.name not in {"payload_json", "review_basis", "revoke_basis"})


def _start(db, user, *, profile_id=None, roles=source_input.GOVERNANCE_ROLES):
    lock_gate(db)
    related = set()
    selected_ids = {profile_id} if profile_id is not None else set()
    selection = current(db.query(AIInfectionLocalSelection.updated_by, AIInfectionLocalSelection.profile_id).filter_by(feature_key=KEY), shared=True).one_or_none()
    if selection is not None:
        related.add(selection.updated_by)
        if selection.profile_id is not None:
            selected_ids.add(selection.profile_id)
    if selected_ids:
        for row in current(
            db.query(AIInfectionLocalProfile.created_by, AIInfectionLocalProfile.reviewed_by, AIInfectionLocalProfile.revoked_by).filter(AIInfectionLocalProfile.profile_id.in_(sorted(selected_ids))),
            shared=True,
        ).all():
            related.update(uid for uid in row if uid is not None)
    return r._start(db, user, related_user_ids=related, roles=roles)


def _row(db, rid, *, shared=True):
    TypeAdapter(c.UUID).validate_python(rid)
    row = current(db.query(AIInfectionLocalProfile).filter_by(profile_id=rid), shared=shared).one_or_none()
    if row is None:
        raise HTTPException(404, "本地统计Profile不存在")
    return row


def _governance(row):
    return scenario_input.ScenarioGovernance.model_validate(
        {field: r.utc(getattr(row, field)) if field.endswith("_at") else getattr(row, field) for field in scenario_input.ScenarioGovernance.model_fields}
    )


def _audit_text(row, action, revision):
    anchors = {name: getattr(row, name) for name in ("implementation_hash", "directory_hash", "author_epoch_hash")}
    if action == "review":
        anchors["reviewer_epoch_hash"] = row.reviewer_epoch_hash
    return r.audit_detail("local_profile", row.profile_id, action, row.content_hash, revision, anchors=anchors)


def _audits(db, row):
    for action, event_id, actor_id, revision in [
        ("create", row.create_event_id, row.created_by, 1),
        ("review", row.review_event_id, row.reviewed_by, 2),
        ("revoke", row.revoke_event_id, row.revoked_by, row.revision),
    ]:
        if event_id is None:
            continue
        event = r._actual(db, r.AIAuditEvent, event_id)
        if event is None or (event.actor_id, event.action, event.target, event.detail_json) != (actor_id, f"infection.local_profile.{action}", row.profile_id, _audit_text(row, action, revision)):
            raise HTTPException(409, "本地Profile具体审计PK与原件不一致")


def _event(db, actor, row, action, revision):
    event = r.AIAuditEvent(
        actor_id=actor.user_id, action=f"infection.local_profile.{action}", target=row.profile_id, detail_json=_audit_text(row, action, revision), create_time=r.utcnow().replace(microsecond=0)
    )
    db.add(event)
    db.flush([event])
    return event, r._state(event)


def _actual_epoch(db, expected):
    from app.models import User

    actual = current(db.query(User.user_id, User.user_role, User.token_invalid_before).filter_by(user_id=expected.user_id), shared=True).one_or_none()
    return actual is not None and actual.user_role == "super_admin" and scenario.epoch(actual) == expected


def _verify_write(db, row, expected_event, actor):
    expected, epoch = r._state(row), scenario.epoch(actor)
    db.flush()
    actual = r._actual(db, AIInfectionLocalProfile, row.profile_id)
    if actual is None or dict(actual._mapping) != expected or not _actual_epoch(db, epoch):
        raise HTTPException(409, "Profile写后实际SQL或请求身份时段变化")
    r._verify_audit(db, expected_event)
    _audits(db, row)


def _departments(db, ids):
    from app.models import Department

    rows = current(db.query(Department.department_id, Department.name).filter(Department.department_id.in_(sorted(ids))).order_by(Department.department_id), shared=True).all()
    index = {row.department_id: row for row in rows}
    if len(index) != len(ids):
        raise HTTPException(409, "验证适用科室必须均为实际当前目录成员")
    return [i.ProfileDepartment(department_id=did, recorded_name=index[did].name, directory_hash=c.digest({"department_id": did, "name": index[did].name})) for did in ids]


def _parents(db, payload):
    if payload.expected_implementation_hash != c.digest(implementation_descriptor()) or payload.implementation_descriptor.model_dump(mode="json") != implementation_descriptor():
        raise HTTPException(409, "实际安装的统计实现/配方身份与审核版本不同")
    definition, _ = r.definition_current(db, payload.scope.definition_id)
    if (definition.content_hash, definition.governance_hash) != (payload.scope.definition_content_hash, payload.scope.definition_governance_hash) or not set(payload.scope.pathogen_codes) <= set(
        definition.payload.pathogen_codes
    ):
        raise HTTPException(409, "验证范围的实际定义、发布治理或已审代码改变")
    if _departments(db, payload.scope.department_ids) != payload.departments:
        raise HTTPException(409, "验证范围的实际科室窄目录已改变")


def _issues(db, row, payload):
    from app.models import User

    issues = [] if row.status == "published" else ["not_published"]
    ids = sorted({row.created_by, *([row.reviewed_by] if row.reviewed_by is not None else [])})
    users = {u.user_id: u for u in current(db.query(User).filter(User.user_id.in_(ids)).order_by(User.user_id), shared=True).all()}
    for uid, sha, reason in [(row.created_by, row.author_epoch_hash, "author_epoch_changed"), (row.reviewed_by, row.reviewer_epoch_hash, "reviewer_epoch_changed")]:
        if uid is not None:
            actor = users.get(uid)
            if actor is None or actor.user_role != "super_admin" or c.digest(scenario.epoch(actor)) != sha:
                issues.append(reason)
    if payload.expected_implementation_hash != c.digest(implementation_descriptor()) or payload.implementation_descriptor.model_dump(mode="json") != implementation_descriptor():
        issues.append("installed_implementation_changed")
    try:
        definition, _ = r.definition_current(db, payload.scope.definition_id)
        if (definition.content_hash, definition.governance_hash) != (payload.scope.definition_content_hash, payload.scope.definition_governance_hash) or not set(payload.scope.pathogen_codes) <= set(
            definition.payload.pathogen_codes
        ):
            issues.append("definition_changed")
    except HTTPException:
        issues.append("definition_changed")
    try:
        if _departments(db, payload.scope.department_ids) != payload.departments:
            issues.append("department_directory_changed")
    except HTTPException:
        issues.append("department_directory_changed")
    return issues


def record(db, row, *, require_current=False):
    payload = i.ProfilePayload.model_validate_json(row.payload_json)
    if c.canonical(payload) != row.payload_json or (payload.profile_id, c.digest(payload), payload.expected_implementation_hash, payload.directory_hash, c.digest(payload.author_epoch)) != (
        row.profile_id,
        row.content_hash,
        row.implementation_hash,
        row.directory_hash,
        row.author_epoch_hash,
    ):
        raise HTTPException(409, "本地Profile完整原件与技术锚不一致")
    _audits(db, row)
    issues = _issues(db, row, payload)
    full = i.ProfileRecord(
        schema_version="infection_local_profile_record_v1",
        profile_id=row.profile_id,
        payload=payload,
        content_hash=row.content_hash,
        governance=_governance(row),
        governance_hash=c.digest(_governance(row)),
        eligible=not issues,
        current_issues=issues,
        publication_does_not_enable_execution=True,
        authority_basis="current_independent_super_exact_audit_pk_and_installed_identity_not_verified_clinical_validity",
    )
    c.canonical(full)
    if require_current and not full.eligible:
        raise HTTPException(409, "本地Profile未当前独立发布或其范围/身份已失效")
    return full


@r.atomic
def create_profile(db, user, value):
    req = i.ProfileCreate.model_validate(value)
    actor = _start(db, user)
    departments = _departments(db, req.scope.department_ids)
    payload = i.ProfilePayload(
        **req.model_dump(),
        schema_version="infection_local_profile_payload_v1",
        profile_id=str(uuid.uuid4()),
        created_by=actor.user_id,
        recorded_at=r.utc(r.utcnow()),
        author_epoch=scenario.epoch(actor),
        implementation_descriptor=implementation_descriptor(),
        departments=departments,
        directory_hash=c.digest([d.model_dump(mode="json") for d in departments]),
        limitations=k.LIMITATIONS,
        validation_assertion_basis="human_recorded_scope_and_evidence_not_code_certification_or_automatic_activation",
    )
    _parents(db, payload)
    row = AIInfectionLocalProfile(
        profile_id=payload.profile_id,
        schema_version="infection_local_profile_v1",
        implementation_hash=payload.expected_implementation_hash,
        directory_hash=payload.directory_hash,
        author_epoch_hash=c.digest(payload.author_epoch),
        parameters_review="unknown",
        payload_json=c.canonical(payload),
        content_hash=c.digest(payload),
        status="draft",
        revision=1,
        recorded_at=r.clock(payload.recorded_at),
        created_by=actor.user_id,
        privacy_review="unknown",
        faithfulness_review="unknown",
        review_basis="",
        revoke_basis="",
    )
    event, expected = _event(db, actor, row, "create", 1)
    row.create_event_id = event.event_id
    db.add(row)
    _verify_write(db, row, expected, actor)
    _parents(db, payload)
    return record(db, row)


@r.atomic
def detail(db, user, rid):
    _start(db, user, profile_id=rid)
    return record(db, _row(db, rid))


@r.atomic
def review_profile(db, user, rid, value):
    req = scenario_input.ScenarioReview.model_validate(value)
    actor = _start(db, user, profile_id=rid)
    row = _row(db, rid, shared=False)
    full = record(db, row)
    r._cas(req, full)
    if row.status != "draft" or row.created_by == actor.user_id or "author_epoch_changed" in full.current_issues:
        raise HTTPException(409, "须由另一当前Super审核有效提出者的完整草稿")
    _parents(db, full.payload)
    row.status, row.revision, row.reviewed_by, row.reviewed_at = "published" if req.decision == "publish" else "rejected", 2, actor.user_id, r.utcnow()
    row.review_basis, row.privacy_review, row.faithfulness_review, row.parameters_review = req.basis_note, req.privacy_review, req.faithfulness_review, req.parameters_review
    row.reviewer_epoch_hash = c.digest(scenario.epoch(actor))
    event, expected = _event(db, actor, row, "review", 2)
    row.review_event_id = event.event_id
    _verify_write(db, row, expected, actor)
    _parents(db, full.payload)
    return record(db, row)


@r.atomic
def revoke_profile(db, user, rid, value):
    req = source_input.CAS.model_validate(value)
    actor = _start(db, user, profile_id=rid)
    row = _row(db, rid, shared=False)
    r._cas(req, record(db, row))
    if row.status == "revoked":
        raise HTTPException(409, "本地Profile已撤回")
    row.status, row.revision, row.revoked_by, row.revoked_at, row.revoke_basis = "revoked", row.revision + 1, actor.user_id, r.utcnow(), req.basis_note
    event, expected = _event(db, actor, row, "revoke", row.revision)
    row.revoke_event_id = event.event_id
    _verify_write(db, row, expected, actor)
    return record(db, row)


def metadata(row):
    return dict(
        schema_version="infection_local_profile_metadata_v1",
        profile_id=row.profile_id,
        status=row.status,
        revision=row.revision,
        content_hash=row.content_hash,
        implementation_hash=row.implementation_hash,
        directory_hash=row.directory_hash,
        recorded_at=r.utc(row.recorded_at),
        detail_required=True,
        clinical_body_included=False,
        publication_does_not_enable_execution=True,
    )


def directory(db, user, *, page=1, size=20):
    _start(db, user)
    if type(page) is not int or page < 1 or type(size) is not int or not 1 <= size <= 100:
        raise HTTPException(422, "需要明确的完整分页参数")
    rows = current(db.query(*(getattr(AIInfectionLocalProfile, name) for name in PROFILE_TECHNICAL)).order_by(AIInfectionLocalProfile.profile_id), shared=True).limit(c.MAX_ROOTS + 1).all()
    if len(rows) > c.MAX_ROOTS:
        raise HTTPException(413, "完整本地Profile目录超过4096，未伪装完整分页")
    return dict(items=[metadata(row) for row in rows[(page - 1) * size : page * size]], total=len(rows), page=page, size=size, clinical_body_included=False)


def config_state(row):
    # These are real legacy DATETIME(0) clocks, explicitly written at second
    # precision. No microsecond clock is invented for the old configuration.
    return {
        col.name: getattr(row, col.name).isoformat() if col.name in {"validated_at", "update_time"} and getattr(row, col.name) is not None else getattr(row, col.name) for col in row.__table__.columns
    }


def _roles(config):
    from app.dependencies import VALID_USER_ROLES

    try:
        roles = json.loads(config.allowed_roles_json, object_pairs_hook=c._pairs, parse_constant=c._nonfinite)
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "当前本地配置角色无法核对") from exc
    if type(roles) is not list or not roles or any(type(role) is not str or role not in VALID_USER_ROLES for role in roles) or len(roles) != len(set(roles)):
        raise HTTPException(409, "当前角色须为完整已知平台角色闭集")
    return roles


def _selection_audit(selection):
    return c.canonical(
        {
            "schema_version": "infection_local_configuration_audit_v1",
            "feature_key": KEY,
            "profile_id": selection.profile_id,
            "selection_revision": selection.revision,
            "feature_revision": selection.feature_revision,
            "config_hash": selection.config_hash,
            "writer_epoch_hash": selection.writer_epoch_hash,
            "updated_at": r.utc(selection.updated_at),
        }
    )


def _coupled(db, config, selection, *, require_current_governor=True):
    if (
        config is None
        or selection is None
        or config.provider_id is not None
        or config.active_prompt_id is not None
        or (config.revision, c.digest(config_state(config))) != (selection.feature_revision, selection.config_hash)
    ):
        raise HTTPException(409, "实际本地选择与完整FeatureConfig不一致，禁止外部模型/Prompt降级")
    _roles(config)
    if (
        type(config.enabled) is not int
        or config.enabled not in {0, 1}
        or config.validation_status not in {"unreviewed", "pilot", "validated", "suspended"}
        or type(config.daily_limit) is not int
        or not 1 <= config.daily_limit <= 10000
        or config.validation_status in {"pilot", "validated"}
        and (config.validated_by != selection.updated_by or config.validated_at is None or len(config.validation_note.strip()) < 10)
        or config.validation_status in {"unreviewed", "suspended"}
        and (config.validated_by is not None or config.validated_at is not None)
    ):
        raise HTTPException(409, "实际本地配置标量/验证声明不是闭集，未推定有效")
    event = r._actual(db, r.AIAuditEvent, selection.change_event_id)
    if event is None or (event.actor_id, event.action, event.target, event.detail_json) != (selection.updated_by, "infection.local_configuration.write", KEY, _selection_audit(selection)):
        raise HTTPException(409, "本地配置具体审计PK不一致")
    from app.models import User

    actor = current(db.query(User).filter_by(user_id=selection.updated_by), shared=True).one_or_none()
    governor_current = actor is not None and actor.user_role == "super_admin" and c.digest(scenario.epoch(actor)) == selection.writer_epoch_hash
    if require_current_governor and not governor_current:
        raise HTTPException(409, "原配置治理者当前角色/令牌时段已变化")
    return governor_current


@r.atomic
def configure(db, user, value):
    from app.dependencies import VALID_USER_ROLES

    req = i.LocalConfigWrite.model_validate(value)
    actor = _start(db, user, profile_id=req.profile_id)
    expected_epoch = scenario.epoch(actor)
    if any(role not in VALID_USER_ROLES for role in req.allowed_roles):
        raise HTTPException(422, "配置中存在未知平台角色，未自动删除")
    profile = record(db, _row(db, req.profile_id), require_current=True) if req.profile_id is not None else None
    if req.enabled and (profile is None or profile.payload.validation_status != "validated"):
        raise HTTPException(409, "本地Profile未记录适用范围验证，不能因发布而启用")
    config = current(db.query(AIFeatureConfig).filter_by(feature_key=KEY)).one_or_none()
    selection = current(db.query(AIInfectionLocalSelection).filter_by(feature_key=KEY)).one_or_none()
    if (config.revision if config else 0, selection.revision if selection else 0) != (req.expected_feature_revision, req.expected_selection_revision):
        raise HTTPException(409, "完整Feature/本地选择双版本CAS已改变")
    if selection is not None:
        # A new current Super may explicitly disable/rebind an intact historic
        # configuration after its old governor loses authority. This does not
        # restore its execution/read eligibility or bypass either full CAS.
        _coupled(db, config, selection, require_current_governor=False)
    if config is None:
        config = AIFeatureConfig(feature_key=KEY, revision=0, updated_by=actor.user_id)
        db.add(config)
    config.provider_id, config.active_prompt_id = None, None
    config.enabled, config.allowed_roles_json, config.validation_status = int(req.enabled), c.canonical(req.allowed_roles), req.validation_status
    # None explicitly clears this old NOT NULL technical note, matching the
    # existing feature-management contract; clinical Source originals are not
    # changed or normalized by this configuration operation.
    config.validation_note = req.validation_note if req.validation_note is not None else ""
    config.validated_by, config.validated_at = (actor.user_id, r.utcnow().replace(microsecond=0)) if req.validation_status in {"pilot", "validated"} else (None, None)
    config.daily_limit, config.revision, config.updated_by, config.update_time = req.daily_limit, config.revision + 1, actor.user_id, r.utcnow().replace(microsecond=0)
    # Equal wall-clock values are still explicit: otherwise the legacy Column
    # onupdate callback may substitute a different real microsecond timestamp.
    flag_modified(config, "update_time")
    db.flush([config])
    if selection is None:
        selection = AIInfectionLocalSelection(feature_key=KEY, revision=0)
        db.add(selection)
    selection.profile_id, selection.revision, selection.feature_revision = req.profile_id, selection.revision + 1, config.revision
    selection.config_hash, selection.writer_epoch_hash, selection.updated_by, selection.updated_at = c.digest(config_state(config)), c.digest(expected_epoch), actor.user_id, r.utcnow()
    event = r.AIAuditEvent(actor_id=actor.user_id, action="infection.local_configuration.write", target=KEY, detail_json=_selection_audit(selection), create_time=r.utcnow().replace(microsecond=0))
    db.add(event)
    db.flush([event])
    selection.change_event_id = event.event_id
    expected_config, expected_selection, expected_event = r._state(config), r._state(selection), r._state(event)
    db.flush()
    actual_config, actual_selection = r._actual(db, AIFeatureConfig, KEY), r._actual(db, AIInfectionLocalSelection, KEY)
    if (
        actual_config is None
        or actual_selection is None
        or dict(actual_config._mapping) != expected_config
        or dict(actual_selection._mapping) != expected_selection
        or not _actual_epoch(db, expected_epoch)
    ):
        raise HTTPException(409, "配置写后实际SQL/请求身份时段不一致")
    r._verify_audit(db, expected_event)
    _coupled(db, config, selection)
    if profile is not None:
        record(db, _row(db, profile.profile_id), require_current=True)
    return configuration(db, actor, management=True)


def configuration(db, user, *, management=False):
    actor = _start(db, user, roles=source_input.GOVERNANCE_ROLES if management else source_input.SOURCE_ROLES)
    config = current(db.query(AIFeatureConfig).filter_by(feature_key=KEY), shared=True).one_or_none()
    selection = current(db.query(AIInfectionLocalSelection).filter_by(feature_key=KEY), shared=True).one_or_none()
    if config is None and selection is None:
        return dict(
            schema_version="infection_local_configuration_v1",
            feature_key=KEY,
            engine="prediction",
            execution="local_exact_statistics",
            enabled=False,
            validation_status="unreviewed",
            feature_revision=0,
            selection_revision=0,
            profile=None,
            profile_id=None,
            allowed_roles=sorted(source_input.SOURCE_ROLES),
            daily_limit=None,
            validation_note=None,
            config_hash=None,
            current_role_in_fixed_and_configured=False,
            configuration_governor_current=False,
            implementation_descriptor=implementation_descriptor(),
            requires_explicit_configuration=True,
            provider_id=None,
        )
    governor_current = _coupled(db, config, selection, require_current_governor=not management)
    profile = _row(db, selection.profile_id) if selection.profile_id is not None and management else None
    return dict(
        schema_version="infection_local_configuration_v1",
        feature_key=KEY,
        engine="prediction",
        execution="local_exact_statistics",
        enabled=bool(config.enabled),
        validation_status=config.validation_status,
        feature_revision=config.revision,
        selection_revision=selection.revision,
        profile_id=selection.profile_id,
        profile=record(db, profile).model_dump(mode="json") if profile else None,
        allowed_roles=_roles(config),
        daily_limit=config.daily_limit,
        validation_note=config.validation_note if management else None,
        config_hash=selection.config_hash,
        implementation_descriptor=implementation_descriptor(),
        requires_explicit_configuration=False,
        provider_id=None,
        current_role_in_fixed_and_configured=actor.user_role in source_input.SOURCE_ROLES and actor.user_role in _roles(config),
        configuration_governor_current=governor_current,
    )


def execution_configuration(db, user, *, preview=False):
    """Current local activation only. Caller must independently authorize Source."""
    from app.access_control import enforce_feature_permission

    actor = _start(db, user, roles=source_input.SOURCE_ROLES)
    enforce_feature_permission(db, actor, KEY, fresh=True)
    config = current(db.query(AIFeatureConfig).filter_by(feature_key=KEY), shared=True).one_or_none()
    selection = current(db.query(AIInfectionLocalSelection).filter_by(feature_key=KEY), shared=True).one_or_none()
    _coupled(db, config, selection)
    if actor.user_role not in _roles(config):
        raise HTTPException(403, "当前执行角色不在固定角色与当前配置交集中")
    if preview and actor.user_role != "super_admin":
        raise HTTPException(403, "仅当前Super可明确预览未启用的本地统计")
    if selection.profile_id is None:
        raise HTTPException(409, "尚未明确选择本地统计Profile")
    profile = record(db, _row(db, selection.profile_id), require_current=True)
    if not preview and (not config.enabled or config.validation_status != "validated" or profile.payload.validation_status != "validated"):
        raise HTTPException(409, "本地功能及适用范围尚未明确验证启用")
    if config.validation_status == "suspended" or profile.payload.validation_status == "suspended":
        raise HTTPException(409, "当前功能或Profile已暂停")
    return actor, config, selection, profile


@r.atomic
def reject_generic_configuration(db, user):
    """78 has no external Provider or mutable LLM Prompt activation branch."""
    _start(db, user)
    raise HTTPException(409, "病例关联统计须经专用本地Profile/配置双CAS治理；不能由外部Provider或LLM Prompt接口替换")
