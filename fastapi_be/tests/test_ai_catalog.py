"""Contract checks for the user-approved capability set and packaged prompts."""

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY, FEATURES
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
