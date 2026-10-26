"""Writing changes preserve medical boundaries and frozen protocol identities."""

import hashlib
import json

from app.ai.catalog import COMMON_SYSTEM_PROMPT, FEATURE_BY_KEY, FEATURES
from app.ai.feature_prompts import SYSTEM_PROMPT_OVERRIDES
from scripts.export_ai_catalog import artifacts


def test_every_generic_text_task_gets_task_appropriate_writing_guidance():
    generic = [spec for spec in FEATURES if spec.engine == "llm" and spec.key not in SYSTEM_PROMPT_OVERRIDES]
    assert len(generic) == 51
    exported = {item["key"]: item["task_prompt"] for item in json.loads(artifacts()["ai-prompts.json"])["features"]}
    for spec in generic:
        prompt = exported[spec.key]
        assert prompt == spec.task_prompt and spec.instruction in prompt
        assert "先列出影响本任务的风险和数据缺口" not in prompt
        assert "危急值、红旗或禁止级规则时先呈现" in prompt
        assert "warnings 只写本次确有依据" in prompt
        assert "missing_data 逐项说明实际缺少什么" in prompt
        assert "不为控制长度省略事实或伪称覆盖完整" in prompt
    assert "药学核查" in exported["prescription_draft"]
    assert "住院护理表达" in exported["handover_summary"]
    assert "患者沟通" in exported["patient_report_explanation"]
    assert "管理与知识表达" in exported["operations_qa"]
    assert "临床表达" in exported["differential_diagnosis"]


def test_document_body_and_review_notes_have_separate_fields():
    for key in ("outpatient_note", "admission_note", "progress_note", "discharge_summary", "imaging_report_assistant"):
        prompt = FEATURE_BY_KEY[key].task_prompt
        assert "sections 仅放临床文书正文" in prompt
        assert "summary 仅简短说明本次草稿的资料范围，不作为临床正文" in prompt
        assert "统一放 missing_data 或 warnings，不混入正文" in prompt
        assert "没有可写事实的栏目保留待填，不补造正常或阴性记录" in prompt
    assert "患者沟通" in FEATURE_BY_KEY["consent_material"].task_prompt


def test_native_task_style_applies_only_to_permitted_text_fields():
    for key in SYSTEM_PROMPT_OVERRIDES:
        prompt = FEATURE_BY_KEY[key].task_prompt
        assert "表达要求：" in prompt
        assert "逐字引文不作润色" in prompt
        assert "sections 必须" not in prompt
    assert "没有问题时按契约返回 null" in FEATURE_BY_KEY["drg_evidence_review"].task_prompt
    assert "没有具体待核问题时返回空 observations" in FEATURE_BY_KEY["charge_reconciliation"].task_prompt
    assert "本任务没有可自由改写的解释字段" in FEATURE_BY_KEY["research_extraction"].task_prompt
    assert "不增补医学解释" in FEATURE_BY_KEY["drug_label_extraction"].task_prompt
    assert "不添加未受审教学内容" in FEATURE_BY_KEY["clinical_training"].task_prompt


def test_packaged_writing_change_preserves_saved_prompt_and_inactive_configuration(db_session, seed_data):
    from app.ai.governance import active_prompt, describe_config
    from app.ai.models import AIFeatureConfig, AIPromptVersion

    for key in ("patient_summary", *SYSTEM_PROMPT_OVERRIDES):
        spec = FEATURE_BY_KEY[key]
        assert active_prompt(db_session, spec, None) == (spec.task_prompt, 0)
        baseline = describe_config(db_session, spec, None, management=True)
        assert baseline["enabled"] is False and baseline["validation_status"] == "unreviewed"
        saved_text = f"已保存的院内任务版本：{key}。仅按本次实际授权资料和原有响应契约完成核对。"
        saved = AIPromptVersion(feature_key=key, version=7, task_prompt=saved_text, change_note="保留既有自定义版本", created_by=seed_data["super_admin_user"].user_id)
        db_session.add(saved)
        db_session.flush()
        config = AIFeatureConfig(feature_key=key, active_prompt_id=saved.prompt_id, allowed_roles_json=json.dumps(spec.default_roles), updated_by=seed_data["super_admin_user"].user_id)
        db_session.add(config)
        db_session.flush()
        before = {column.name: getattr(config, column.name) for column in AIFeatureConfig.__table__.columns}
        assert active_prompt(db_session, spec, config) == (saved_text, 7)
        visible = describe_config(db_session, spec, config, management=True)
        assert visible["prompt_version"] == 7 and visible["active_prompt_id"] == saved.prompt_id
        assert visible["enabled"] is False and visible["validation_status"] == "unreviewed"
        assert {column.name: getattr(config, column.name) for column in AIFeatureConfig.__table__.columns} == before
        assert saved.task_prompt == saved_text


def test_writing_revision_preserves_all_frozen_fixed_system_bytes():
    # Historical native artifacts compare these exact bytes. A future System
    # migration must explicitly provide compatibility rather than relabel them.
    expected = {
        "common": "39af79072a9aaa6b789b6c748d8414387c73044ddf058464da0b70f0a3e5c20e",
        "research_extraction": "7de629cfd383f20c8c3bdccc0372e72ad268fb07af23280ccc2e7d1f653b0ddd",
        "drg_evidence_review": "ba8c9e2e7849c90b316472ec3df37f5b7622b21d6f0fc5435b8f546214324079",
        "charge_reconciliation": "bd440419aa1aaed76bc204a22d0304c2ded561f55e5169434fd401c5285df5d8",
        "feedback_analysis": "efd3fca5422616201fc4611e7693a52ffa7e96827c6bab2aa1c132286241f9bf",
        "guideline_ingestion": "2961fcc5d873abb5ede7813e7e15500f5f17bf9c3bebc3c399996118d0c49b4d",
        "drug_label_extraction": "6847bfa62383416a1296b37c7eececccd6c2132454a8e866af35da0628e2cd2f",
        "guideline_change_review": "3b802b38212b08e4b0079354720324d656587c46c522bc135ecf077a5377599a",
        "research_cohort": "dde37bb46ad5abf165899b8a4c473b37f24acf772d6cedca5530a777b02d21ab",
        "deidentification": "8bc0bbb4c4034cb1488fa7a2755f1eb7d29f9bbba0f77c761f33fc30ae0a1128",
        "operations_support": "091019337c952d3be9ebc65dc97066167a3e46b60e6894746b8b7ff599de6ad9",
        "clinical_training": "353b28078fb061dcde85a4b6b377feba52c23193bce5edf7a7254517d0334934",
        "incident_rca": "56b8679b6a084a7b24984129defb4c7c06ae47d2d406921bad7d14da887926f4",
    }
    systems = {"common": COMMON_SYSTEM_PROMPT, **SYSTEM_PROMPT_OVERRIDES}
    assert {key: hashlib.sha256(value.encode("utf-8")).hexdigest() for key, value in systems.items()} == expected
