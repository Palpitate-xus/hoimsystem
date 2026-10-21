"""Current SQL declarations for one complete finite comparison family.

The Infection Gate precedes all locators. Source/patient purpose checks precede
Scenario payload and review basis TEXT, including for Super. Scenario governance
is purpose-authorized too; an existing publication never restores a clinical
body or an execution permission after that purpose is withdrawn.
"""

import json
import uuid

from fastapi import HTTPException
from pydantic import TypeAdapter

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_input as source_input
from app.ai import infection_cluster_projection as p
from app.ai import infection_cluster_registry as r
from app.ai import infection_cluster_scenario_input as i
from app.ai import infection_cluster_sources as sources
from app.ai import infection_cluster_statistics_contract as k
from app.ai.infection_cluster_implementation import implementation_descriptor
from app.ai.infection_cluster_models import AIInfectionSnapshot
from app.ai.infection_cluster_scenario_models import AIInfectionScenario
from app.ai.infection_cluster_write_guard import current, lock_gate

ANCHORS = ("snapshot_id", "source_id", "source_private_hash", "source_public_hash", "source_witness_hash", "directory_hash", "author_epoch_hash", "plan_hash", "recipe_hash", "implementation_hash")
TECHNICAL = tuple(column.name for column in AIInfectionScenario.__table__.columns if column.name not in {"payload_json", "review_basis", "revoke_basis"})


def epoch(actor):
    return i.ActorEpoch(user_id=actor.user_id, user_role=actor.user_role, token_invalid_before=actor.token_invalid_before.isoformat() if actor.token_invalid_before else None)


def _locator(db, rid, *, write=False):
    TypeAdapter(c.UUID).validate_python(rid)
    row = current(db.query(*(getattr(AIInfectionScenario, name) for name in TECHNICAL)).filter_by(scenario_id=rid), shared=not write).one_or_none()
    if row is None:
        raise HTTPException(404, "完整比较方案不存在")
    return row


def _anchors(row):
    return {**{field: getattr(row, field) for field in ANCHORS}, "department_ids_hash": c.text_digest(row.department_ids_json)}


def _audit_payload(row, action, revision):
    anchors = _anchors(row)
    if action == "review":
        anchors["reviewer_epoch_hash"] = row.reviewer_epoch_hash
    return r.audit_detail("scenario", row.scenario_id, action, row.content_hash, revision, anchors=anchors)


def _audits(db, row):
    for action, event_id, actor_id, revision in [
        ("create", row.create_event_id, row.created_by, 1),
        ("review", row.review_event_id, row.reviewed_by, 2),
        ("revoke", row.revoke_event_id, row.revoked_by, row.revision),
    ]:
        if event_id is None:
            continue
        actual = r._actual(db, r.AIAuditEvent, event_id)
        if actual is None or (actual.actor_id, actual.action, actual.target, actual.detail_json) != (actor_id, f"infection.scenario.{action}", row.scenario_id, _audit_payload(row, action, revision)):
            raise HTTPException(409, "比较方案技术范围与具体审计PK不一致")


def _governance(row):
    return i.ScenarioGovernance.model_validate({field: r.utc(getattr(row, field)) if field.endswith("_at") else getattr(row, field) for field in i.ScenarioGovernance.model_fields})


def metadata(row):
    return {
        "schema_version": "infection_comparison_scenario_metadata_v1",
        "scenario_id": row.scenario_id,
        "snapshot_id": row.snapshot_id,
        "content_hash": row.content_hash,
        "status": row.status,
        "revision": row.revision,
        "recorded_at": r.utc(row.recorded_at),
        "plan_hash": row.plan_hash,
        "recipe_hash": row.recipe_hash,
        "implementation_hash": row.implementation_hash,
        "detail_required": True,
        "clinical_body_included": False,
        "can_execute": False,
        "publication_does_not_enable_execution": True,
    }


def _ids(row):
    try:
        value = json.loads(row.department_ids_json, object_pairs_hook=c._pairs, parse_constant=c._nonfinite)
        ids = TypeAdapter(list[c.PositiveId]).validate_python(value)
        if not 1 <= len(ids) <= k.MAX_COMPARISONS or len(set(ids)) != len(ids) or c.canonical(ids) != row.department_ids_json:
            raise ValueError("The exact explicit Department locator differs")
        return ids
    except (ValueError, TypeError) as exc:
        raise HTTPException(409, "方案科室技术目录不能完整核对") from exc


def _begin_source(db, user, snapshot_id, *, related=(), roles=source_input.SOURCE_ROLES):
    # Only Snapshot scope/owner locators are read before patient rights. The
    # Source service subsequently verifies those against its exact audit PK.
    lock_gate(db)
    locator = sources._snapshot_locator(db, snapshot_id)
    if locator is None:
        raise HTTPException(409, "原完整来源快照不存在")
    req = source_input.SnapshotCreate.model_validate_json(locator.scope_json)
    return r._start(db, user, patient_ids=req.patient_ids, roles=roles, related_user_ids={locator.created_by, *related})


def _source(db, actor, snapshot_id, *, execution=False):
    private_value = sources.snapshot_part(db, actor, snapshot_id, "private", execution=execution)
    private = c.PrivateCollection.model_validate(private_value["value"])
    snapshot = current(db.query(AIInfectionSnapshot).filter_by(snapshot_id=snapshot_id), shared=True).one()
    public = p.InfectionClusterSource.model_validate_json(snapshot.public_json)
    binding = k.SourceBinding(
        snapshot_id=snapshot_id, source_id=public.source_id, private_collection_hash=snapshot.private_hash, public_source_hash=snapshot.public_hash, witness_hash=snapshot.witness_hash
    )
    return private, public, snapshot, binding


def _departments(db, ids, private, snapshot):
    from app.models import Department

    rows = current(db.query(Department.department_id, Department.name).filter(Department.department_id.in_(sorted(ids))).order_by(Department.department_id), shared=True).all()
    by_id = {row.department_id: row for row in rows}
    if len(by_id) != len(ids):
        raise HTTPException(409, "每个明确科室须为当前真实Department目录成员")
    result = []
    for did in ids:
        row = by_id[did]
        result.append(
            i.DepartmentBinding(
                department_id=did,
                recorded_name=row.name,
                directory_hash=c.digest({"department_id": did, "name": row.name}),
                department_token=p._token(snapshot.mapping_key, private, snapshot.private_hash, "department", did),
                identity_fields="actual_department_id_and_recorded_name_only_not_full_directory_or_active_status",
            )
        )
    return result


def _actors_current(db, row, *, require_publication=False):
    from app.models import User

    ids = sorted({row.created_by, *([row.reviewed_by] if row.reviewed_by is not None else [])})
    users = {u.user_id: u for u in current(db.query(User).filter(User.user_id.in_(ids)).order_by(User.user_id), shared=True).all()}
    author = users.get(row.created_by)
    if author is None or author.user_role != "super_admin" or c.digest(epoch(author)) != row.author_epoch_hash:
        raise HTTPException(409, "原方案提出者当前角色/令牌时段已变化")
    if row.reviewed_by is not None:
        reviewer = users.get(row.reviewed_by)
        if reviewer is None or reviewer.user_role != "super_admin" or c.digest(epoch(reviewer)) != row.reviewer_epoch_hash:
            raise HTTPException(409, "原独立审核者当前角色/令牌时段已变化")
    if require_publication and row.status != "published":
        raise HTTPException(409, "仅当前独立发布的完整方案可执行")


def _load(db, actor, locator, *, execution=False, require_publication=False):
    # Exact audit binds the technical locator BEFORE Source or Scenario TEXT.
    _audits(db, locator)
    _actors_current(db, locator, require_publication=require_publication)
    if locator.implementation_hash != c.digest(implementation_descriptor()):
        raise HTTPException(409, "当前已安装统计实现版本与声明不同，须重新声明复核")
    private, public, snapshot, binding = _source(db, actor, locator.snapshot_id, execution=execution)
    if (binding.source_id, binding.private_collection_hash, binding.public_source_hash, binding.witness_hash) != (
        locator.source_id,
        locator.source_private_hash,
        locator.source_public_hash,
        locator.source_witness_hash,
    ):
        raise HTTPException(409, "实际完整来源与方案冻结锚不一致")
    departments = _departments(db, _ids(locator), private, snapshot)
    if i.directory_digest(departments) != locator.directory_hash:
        raise HTTPException(409, "所选真实科室窄目录已变化，未读取方案正文")
    row = current(db.query(AIInfectionScenario).filter_by(scenario_id=locator.scenario_id), shared=True).one()
    payload = i.ScenarioPayload.model_validate_json(row.payload_json)
    if c.canonical(payload) != row.payload_json or payload.source_binding != binding or payload.departments != departments:
        raise HTTPException(409, "完整方案原件/同源HMAC科室映射不一致")
    if (
        c.digest(payload) != row.content_hash
        or payload.scenario_id != row.scenario_id
        or payload.directory_hash != row.directory_hash
        or payload.plan_hash != row.plan_hash
        or payload.recipe_hash != row.recipe_hash
        or payload.implementation_hash != row.implementation_hash
        or c.digest(payload.author_epoch) != row.author_epoch_hash
    ):
        raise HTTPException(409, "完整方案字段与技术/版本锚不一致")
    if payload.plan.pathogen_code not in private.definition.payload.pathogen_codes:
        raise HTTPException(409, "所选病原代码不属于此实际已发布定义")
    # This validates all windows against the actual whole Source without
    # executing the evaluator or pretending the declaration grants authority.
    k.StatisticsInput(
        schema_version="infection_statistics_input_v1",
        source=public,
        scenario=payload.plan,
        scenario_content_hash=payload.plan_hash,
        scenario_governance_hash=c.digest(_governance(row)),
        recipe_hash=payload.recipe_hash,
        authority_basis="pure_structure_and_arithmetic_only_server_must_verify_current_authority",
    )
    _audits(db, row)
    full = i.ScenarioRecord(
        schema_version="infection_comparison_scenario_record_v1",
        scenario_id=row.scenario_id,
        payload=payload,
        content_hash=row.content_hash,
        governance=_governance(row),
        governance_hash=c.digest(_governance(row)),
        eligible=row.status == "published",
        authority_basis="current_source_patient_purpose_directory_super_and_exact_audit_pk_not_clinical_validation",
        publication_does_not_enable_execution=True,
    )
    return row, full, public


def _new_event(db, actor, row, action, revision):
    # The pending mutation is flushed only after the specific Audit PK exists.
    event = r.AIAuditEvent(
        actor_id=actor.user_id, action=f"infection.scenario.{action}", target=row.scenario_id, detail_json=_audit_payload(row, action, revision), create_time=r.utcnow().replace(microsecond=0)
    )
    db.add(event)
    db.flush([event])
    return event, r._state(event)


def _verify(db, row, expected_event, actor, *, technical_only=False):
    from app.models import User

    expected_epoch = epoch(actor)
    fields = TECHNICAL if technical_only else tuple(column.name for column in row.__table__.columns)
    expected = {field: getattr(row, field) for field in fields}
    db.flush()
    actual = current(db.query(*(getattr(AIInfectionScenario, field) for field in fields)).filter_by(scenario_id=row.scenario_id), shared=True).one_or_none()
    actual_actor = current(db.query(User.user_id, User.user_role, User.token_invalid_before).filter_by(user_id=expected_epoch.user_id), shared=True).one_or_none()
    if actual is None or dict(actual._mapping) != expected or actual_actor is None or actual_actor.user_role != "super_admin" or epoch(actual_actor) != expected_epoch:
        raise HTTPException(409, "方案写后实际SQL/当前审核者不一致")
    r._verify_audit(db, expected_event)
    _audits(db, actual)


@r.atomic
def create_scenario(db, user, value):
    req = i.ScenarioCreate.model_validate(value)
    actor = _begin_source(db, user, req.source_binding.snapshot_id, roles=source_input.GOVERNANCE_ROLES)
    private, public, snapshot, binding = _source(db, actor, req.source_binding.snapshot_id)
    if binding != req.source_binding:
        raise HTTPException(409, "明确提交的完整来源四锚与当前来源不同")
    if req.pathogen_code not in private.definition.payload.pathogen_codes:
        raise HTTPException(409, "须选择本来源真实已审病原代码，不猜测原标签")
    departments = _departments(db, req.department_ids, private, snapshot)
    rid = str(uuid.uuid4())
    plan = k.ScenarioPlan(
        schema_version="infection_comparison_plan_v1",
        scenario_id=rid,
        source_binding=binding,
        department_tokens=[d.department_token for d in departments],
        windows=req.windows,
        pathogen_code=req.pathogen_code,
        alpha_decimal=req.alpha_decimal,
        method="one_sided_fisher_greater_fixed_margins",
        family_basis="complete_declared_department_by_window_cartesian_product",
        declaration_basis="declared_before_this_execution_not_proven_independent_of_observed_data",
        no_population_denominator="not_provided",
    )
    payload = i.ScenarioPayload(
        schema_version="infection_comparison_scenario_payload_v1",
        scenario_id=rid,
        created_by=actor.user_id,
        recorded_at=r.utc(r.utcnow()),
        author_epoch=epoch(actor),
        source_binding=binding,
        departments=departments,
        directory_hash=i.directory_digest(departments),
        plan=plan,
        plan_hash=c.digest(plan),
        recipe_hash=c.digest(k.RECIPE),
        implementation_hash=c.digest(implementation_descriptor()),
        basis_note=req.basis_note,
        limitations=k.LIMITATIONS,
    )
    # Preflight whole Source+plan input; individual Source validity does not
    # promise that every repeated HTTP/Task wrapper fits its own8MiB budget.
    k.StatisticsInput(
        schema_version="infection_statistics_input_v1",
        source=public,
        scenario=plan,
        scenario_content_hash=payload.plan_hash,
        scenario_governance_hash="0" * 64,
        recipe_hash=payload.recipe_hash,
        authority_basis="pure_structure_and_arithmetic_only_server_must_verify_current_authority",
    )
    row = AIInfectionScenario(
        scenario_id=rid,
        schema_version="infection_comparison_scenario_v1",
        snapshot_id=binding.snapshot_id,
        source_id=binding.source_id,
        source_private_hash=binding.private_collection_hash,
        source_public_hash=binding.public_source_hash,
        source_witness_hash=binding.witness_hash,
        department_ids_json=c.canonical(req.department_ids),
        directory_hash=payload.directory_hash,
        author_epoch_hash=c.digest(payload.author_epoch),
        plan_hash=payload.plan_hash,
        recipe_hash=payload.recipe_hash,
        implementation_hash=payload.implementation_hash,
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
    event, expected = _new_event(db, actor, row, "create", 1)
    row.create_event_id = event.event_id
    db.add(row)
    _verify(db, row, expected, actor)
    return _load(db, actor, _locator(db, rid))[1]


@r.atomic
def scenario_current(db, user, rid, *, execution=False):
    lock_gate(db)
    locator = _locator(db, rid)
    _audits(db, locator)
    actor = _begin_source(db, user, locator.snapshot_id, related={locator.created_by, *([locator.reviewed_by] if locator.reviewed_by is not None else [])})
    if actor.user_role != "super_admin" and locator.status != "published":
        raise HTTPException(403, "未发布方案仅用于明确授权的Super治理")
    return _load(db, actor, locator, execution=execution, require_publication=execution)[1]


@r.atomic
def review_scenario(db, user, rid, value):
    req = i.ScenarioReview.model_validate(value)
    lock_gate(db)
    locator = _locator(db, rid)
    _audits(db, locator)
    actor = _begin_source(db, user, locator.snapshot_id, related={locator.created_by}, roles=source_input.GOVERNANCE_ROLES)
    row, full, _ = _load(db, actor, locator)
    r._cas(req, full)
    if row.status != "draft" or row.created_by == actor.user_id:
        raise HTTPException(409, "仅另一当前Super可审核明确的未审核完整方案")
    # Upgrade only after all Source parents/current patient checks; all paths
    # already own the same domain Gate, so another supported writer cannot hold
    # the reverse Scenario→Source lock order.
    row = current(db.query(AIInfectionScenario).filter_by(scenario_id=rid)).one()
    row.status = "published" if req.decision == "publish" else "rejected"
    row.revision, row.reviewed_by, row.reviewed_at = 2, actor.user_id, r.utcnow()
    row.review_basis, row.privacy_review, row.faithfulness_review, row.parameters_review = req.basis_note, req.privacy_review, req.faithfulness_review, req.parameters_review
    row.reviewer_epoch_hash = c.digest(epoch(actor))
    event, expected = _new_event(db, actor, row, "review", 2)
    row.review_event_id = event.event_id
    _verify(db, row, expected, actor)
    return _load(db, actor, _locator(db, rid))[1]


@r.atomic
def revoke_scenario(db, user, rid, value):
    req = source_input.CAS.model_validate(value)
    lock_gate(db)
    locator = _locator(db, rid)
    _audits(db, locator)
    actor = _begin_source(db, user, locator.snapshot_id, related={locator.created_by}, roles=source_input.GOVERNANCE_ROLES)
    row, full, _ = _load(db, actor, locator)
    r._cas(req, full)
    if row.status == "revoked":
        raise HTTPException(409, "方案撤销完整CAS已变化或已撤销")
    row = current(db.query(AIInfectionScenario).filter_by(scenario_id=rid)).one()
    row.status, row.revision, row.revoked_by, row.revoked_at, row.revoke_basis = "revoked", row.revision + 1, actor.user_id, r.utcnow(), req.basis_note
    event, expected = _new_event(db, actor, row, "revoke", row.revision)
    row.revoke_event_id = event.event_id
    _verify(db, row, expected, actor)
    _load(db, actor, _locator(db, rid))
    return metadata(row)


def scenario_directory(db, user, *, snapshot_id=None, page=1, size=20):
    actor = r._start(db, user, roles=source_input.SOURCE_ROLES)
    if type(page) is not int or page < 1 or type(size) is not int or not 1 <= size <= 100:
        raise HTTPException(422, "需要明确的完整分页参数")
    query = db.query(*(getattr(AIInfectionScenario, field) for field in TECHNICAL))
    if snapshot_id is not None:
        TypeAdapter(c.UUID).validate_python(snapshot_id)
        actor = _begin_source(db, actor, snapshot_id)
        source_locator = sources._snapshot_locator(db, snapshot_id)
        req = source_input.SnapshotCreate.model_validate_json(source_locator.scope_json)
        r.authorize_patients(db, actor, req.patient_ids)
        query = query.filter(AIInfectionScenario.snapshot_id == snapshot_id)
    elif actor.user_role != "super_admin":
        raise HTTPException(422, "业务目录须明确完整来源快照，不自动列出全院方案")
    if actor.user_role != "super_admin":
        query = query.filter(AIInfectionScenario.status == "published")
    # Bodyless current directory only. A separate explicit detail call must
    # still establish current Source permission; no metadata row is eligible.
    rows = current(query.order_by(AIInfectionScenario.scenario_id), shared=True).limit(c.MAX_ROOTS + 1).all()
    if len(rows) > c.MAX_ROOTS:
        raise HTTPException(413, "完整技术目录超过本版4096行界限，未冒充完整分页")
    return {"items": [metadata(row) for row in rows[(page - 1) * size : page * size]], "page": page, "size": size, "total": len(rows), "clinical_body_included": False}


def department_directory(db, user, *, page=1, size=20):
    from app.models import Department

    r._start(db, user)
    if type(page) is not int or page < 1 or type(size) is not int or not 1 <= size <= 100:
        raise HTTPException(422, "需要明确的完整分页参数")
    rows = current(db.query(Department.department_id, Department.name).order_by(Department.department_id), shared=True).limit(c.MAX_ROOTS + 1).all()
    if len(rows) > c.MAX_ROOTS:
        raise HTTPException(413, "完整科室技术目录超过4096，未裁切为完整目录")
    return {
        "items": [
            {"department_id": row.department_id, "recorded_name": row.name, "directory_hash": c.digest({"department_id": row.department_id, "name": row.name})}
            for row in rows[(page - 1) * size : page * size]
        ],
        "page": page,
        "size": size,
        "total": len(rows),
        "identity_basis": "actual_pk_and_recorded_name_only_no_active_status_or_professional_qualification",
    }
