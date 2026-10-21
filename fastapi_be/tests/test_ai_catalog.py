"""Contract checks for the user-approved capability set and packaged prompts."""

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY, FEATURES, describe_feature
from app.dependencies import VALID_USER_ROLES


def test_catalog_preserves_all_eighty_distinct_capabilities():
    assert {spec.number for spec in FEATURES} == set(range(1, 81))
    assert len(FEATURE_BY_KEY) == 80
    assert sum(spec.priority == "P0" for spec in FEATURES) == 10
    assert len({spec.task_prompt for spec in FEATURES}) == 80
    for spec in FEATURES:
        assert set(spec.default_roles) <= VALID_USER_ROLES
        assert "super_admin" in spec.default_roles
        assert spec.instruction in spec.task_prompt
        assert len(spec.deliverables) >= 4


def test_treatment_contract_requires_evidence_and_dedicated_models_stay_distinct():
    treatment = FEATURE_BY_KEY["treatment_pathway"]
    assert treatment.requires_knowledge
    assert treatment.scope == "patient"
    assert "医生确认诊断" in treatment.inputs
    assert FEATURE_BY_KEY["imaging_detection"].engine == "vision"
    assert FEATURE_BY_KEY["ecg_analysis"].engine == "signal"
    assert FEATURE_BY_KEY["sepsis_risk"].engine == "prediction"
    assert "不得把缺失信息补写成正常或阴性" in COMMON_SYSTEM_PROMPT


def test_hospital_scope_does_not_advertise_access_to_unscoped_business_roles():
    for spec in FEATURES:
        if spec.scope == "hospital":
            expected = {"super_admin", "admin", "director"} | ({"pharmacist"} if spec.number in {66, 67} else set())
            assert set(spec.default_roles) <= expected
    assert FEATURE_BY_KEY["feedback_analysis"].requires_patient_data_permission
    assert FEATURE_BY_KEY["research_cohort"].requires_patient_data_permission
    assert not FEATURE_BY_KEY["operations_qa"].requires_patient_data_permission


def test_risk_metadata_advertises_its_independent_supported_source_modes():
    assert describe_feature(FEATURE_BY_KEY["deterioration_risk"])["source_reference_keys"] == ["news2_assessment_id", "observation_window_id"]
    assert describe_feature(FEATURE_BY_KEY["aki_risk"])["source_reference_keys"] == ["aki_assessment_id", "observation_window_id"]
    assert describe_feature(FEATURE_BY_KEY["sepsis_risk"])["source_reference_keys"] == ["observation_window_id", "qsofa_assessment_id", "sofa_assessment_id", "sofa_change_assessment_id"]
    for spec in FEATURES:
        if spec.number not in {41, 42, 43}:
            assert "observation_window_id" not in describe_feature(spec)["source_reference_keys"]
        if spec.number != 41:
            assert "news2_assessment_id" not in describe_feature(spec)["source_reference_keys"]
        if spec.number != 43:
            assert "aki_assessment_id" not in describe_feature(spec)["source_reference_keys"]
        if spec.number != 42:
            assert "qsofa_assessment_id" not in describe_feature(spec)["source_reference_keys"]
            assert not {"sofa_assessment_id", "sofa_change_assessment_id"} & set(describe_feature(spec)["source_reference_keys"])
        support_keys = {"support_source_id", "support_source_kind"}
        advertised = set(describe_feature(spec)["source_reference_keys"])
        assert support_keys <= advertised if spec.number == 47 else not support_keys & advertised


def test_export_declares_actual_distinct_fixed_system_prompts_for_closed_drafts():
    import json

    from app.ai.coding_evidence_prompt import CODING_SYSTEM_PROMPT
    from app.ai.document_extraction_contract import EXTRACTION_SYSTEM_PROMPT
    from app.ai.drug_label_draft import SYSTEM_PROMPT as DRUG_LABEL_SYSTEM_PROMPT
    from scripts.export_ai_catalog import artifacts

    payload = json.loads(artifacts()["ai-prompts.json"])
    assert payload["system_prompt"] == COMMON_SYSTEM_PROMPT
    assert payload["system_prompt_overrides"] == {"drg_evidence_review": CODING_SYSTEM_PROMPT, "guideline_ingestion": EXTRACTION_SYSTEM_PROMPT, "drug_label_extraction": DRUG_LABEL_SYSTEM_PROMPT}
    assert FEATURE_BY_KEY["guideline_ingestion"].default_roles == ("super_admin",)
    assert FEATURE_BY_KEY["guideline_ingestion"].requires_patient_data_permission
    assert describe_feature(FEATURE_BY_KEY["guideline_ingestion"])["source_reference_keys"] == ["document_original_id"]


def test_drug_label_source_mode_roles_data_purpose_and_actual_super_prompt_editor(db_session, seed_data):
    from app.ai.drug_label_draft import SYSTEM_PROMPT, TASK_PROMPT
    from app.ai.governance import describe_config, digest
    from app.routers.ai_admin import list_prompts

    spec = FEATURE_BY_KEY["drug_label_extraction"]
    assert spec.default_roles == ("super_admin", "pharmacist")
    assert spec.requires_patient_data_permission and not spec.requires_knowledge
    assert TASK_PROMPT in spec.task_prompt and spec.instruction in spec.task_prompt
    assert describe_feature(spec)["source_reference_keys"] == ["drug_label_source_binding_id"]
    assert all(("drug_label_source_binding_id" in describe_feature(item)["source_reference_keys"]) == (item.number == 73) for item in FEATURES)
    view = describe_config(db_session, spec, None, management=True)
    assert view["input_mode"] == "drug_label_evidence" and view["system_prompt_hash"] == digest(SYSTEM_PROMPT)
    prompt = list_prompts(spec.key, user=seed_data["super_admin_user"], db=db_session)["data"]
    assert prompt["system_prompt"] == SYSTEM_PROMPT
    assert prompt["versions"][-1]["task_prompt"] == spec.task_prompt


def test_drug_label_current_configuration_cannot_expand_roles_or_omit_patient_data_permission(db_session, seed_data):
    import pytest
    from fastapi import HTTPException

    from app.ai.governance import provider_feature_issues
    from app.ai.models import AIFeatureConfig, AIProvider
    from app.ai.runtime import authorized_feature

    spec = FEATURE_BY_KEY["drug_label_extraction"]
    config = AIFeatureConfig(feature_key=spec.key, allowed_roles_json='["admin","pharmacist"]', updated_by=seed_data["super_admin_user"].user_id)
    db_session.add(config)
    db_session.commit()
    for role in ("pharmacist", "super_admin"):
        assert authorized_feature(db_session, seed_data[role + "_user"], spec.key)[0] is spec
    for role in ("admin", "director", "doctor", "patient"):
        with pytest.raises(HTTPException) as error:
            authorized_feature(db_session, seed_data[role + "_user"], spec.key)
        assert error.value.status_code == 403
    provider = AIProvider(kind="chat", model="synthetic-raw-original", allows_patient_data=0)
    issues = provider_feature_issues(spec, provider)
    assert issues and any("资料" in item["message"] for item in issues)
    provider.allows_patient_data = 1
    assert provider_feature_issues(spec, provider) == []
