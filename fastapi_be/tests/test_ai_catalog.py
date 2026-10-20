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
