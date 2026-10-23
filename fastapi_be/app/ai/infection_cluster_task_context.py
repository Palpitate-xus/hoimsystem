"""Current patient purpose and reviewed local scope before private Task storage."""

from fastapi import HTTPException

from app.ai import infection_cluster_contract as c
from app.ai import infection_cluster_profiles as profiles
from app.ai import infection_cluster_registry as r
from app.ai import infection_cluster_scenario as scenarios
from app.ai import infection_cluster_statistics_contract as k
from app.ai import infection_cluster_task_contract as t
from app.ai.infection_cluster_implementation import implementation_descriptor


def epoch(actor):
    return t.RequesterEpoch(user_id=actor.user_id, user_role=actor.user_role, token_invalid_before=actor.token_invalid_before.isoformat() if actor.token_invalid_before else None)


def prepare(db, user, scenario_id, *, preview=False):
    # Profile governance is technical, not a patient grant. Actual Scenario
    # currentness below checks every patient's processing purpose. There is no
    # external model call and external_model_transfer is never implied/required.
    actor, config, selection, profile = profiles.execution_configuration(db, user, preview=preview)
    full = scenarios.scenario_current(db, actor, scenario_id, execution=True)
    private, public, snapshot, binding = scenarios._source(db, actor, full.payload.source_binding.snapshot_id, execution=True)
    scope, plan = profile.payload.scope, full.payload.plan
    definition, _ = r.definition_current(db, scope.definition_id)
    raw_departments = {proof.original.department_id for proof in private.originals if proof.original.department_id is not None}
    if (
        private.definition.payload.definition_id != scope.definition_id
        or (definition.content_hash, definition.governance_hash) != (scope.definition_content_hash, scope.definition_governance_hash)
        or not set(d.department_id for d in full.payload.departments) <= set(scope.department_ids)
        or not raw_departments <= set(scope.department_ids)
        or private.window.date_from < scope.source_window.date_from
        or private.window.date_to > scope.source_window.date_to
        or plan.pathogen_code not in scope.pathogen_codes
        or plan.alpha_decimal not in scope.alpha_decimals
        or len(private.originals) > scope.max_source_records
        or len(plan.department_tokens) * len(plan.windows) > scope.max_comparisons
        or full.payload.implementation_hash != profile.payload.expected_implementation_hash
    ):
        raise HTTPException(409, "完整来源/全部原科室/参数族不在当前所选本地Profile明确验证范围")
    value = k.StatisticsInput(
        schema_version="infection_statistics_input_v1",
        source=public,
        scenario=plan,
        scenario_content_hash=full.payload.plan_hash,
        scenario_governance_hash=full.governance_hash,
        recipe_hash=full.payload.recipe_hash,
        authority_basis="pure_structure_and_arithmetic_only_server_must_verify_current_authority",
    )
    return actor, full, value, profile, config, selection


def freeze(run_id, prepared, *, preview):
    actor, scenario, value, profile, config, selection = prepared
    return t.FrozenTask(
        schema_version="infection_local_frozen_task_v1",
        feature_key=t.FEATURE_KEY,
        engine="prediction",
        execution="installed_local_exact_integer_statistics_no_external_model",
        run_id=run_id,
        requester_epoch=epoch(actor),
        preview=preview,
        created_at=r.utc(r.utcnow()),
        scenario_id=scenario.scenario_id,
        scenario_content_hash=scenario.content_hash,
        scenario_governance_hash=scenario.governance_hash,
        source_binding=scenario.payload.source_binding,
        profile_id=profile.profile_id,
        profile_content_hash=profile.content_hash,
        profile_governance_hash=profile.governance_hash,
        feature_revision=config.revision,
        selection_revision=selection.revision,
        configuration_hash=selection.config_hash,
        recipe_hash=profile.payload.implementation_descriptor.recipe_hash,
        implementation_hash=c.digest(implementation_descriptor()),
        source_hash=c.digest(value),
        prompt_origin="local_fixed_recipe",
        prompt_version=0,
        system_prompt="",
        task_prompt=t.LOCAL_TASK_TEXT,
        prompt_hash=t.LOCAL_PROMPT_HASH,
        external_model_transfer=False,
    )


def compare_current(frozen, prepared, *, execution=False):
    actor, scenario, value, profile, config, selection = prepared
    if (
        scenario.scenario_id != frozen.scenario_id
        or (scenario.content_hash, scenario.governance_hash, scenario.payload.source_binding) != (frozen.scenario_content_hash, frozen.scenario_governance_hash, frozen.source_binding)
        or (profile.profile_id, profile.content_hash, profile.governance_hash) != (frozen.profile_id, frozen.profile_content_hash, frozen.profile_governance_hash)
        or (config.revision, selection.revision, selection.config_hash) != (frozen.feature_revision, frozen.selection_revision, frozen.configuration_hash)
        or c.digest(value) != frozen.source_hash
        or frozen.implementation_hash != c.digest(implementation_descriptor())
        or execution
        and epoch(actor) != frozen.requester_epoch
    ):
        raise HTTPException(409, "原任务完整来源/统计族/本地版本/配置或请求者原身份时段已改变")
    return value
