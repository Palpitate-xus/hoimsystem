"""Finite76 recorded-column declarations; no SQL, app imports or derived units."""

VARIABLE_FIELDS = {
    "patient_demographics": {"sex": "original_integer", "birthday": "original_calendar_date"},
    "registrations": {"specialist": "original_integer", "status": "original_integer", "time": "original_naive_clock"},
    "admissions": {
        "admission_type": "original_integer",
        "admission_time": "original_naive_clock",
        "admission_diagnosis": "verbatim_text",
        "chief_complaint": "verbatim_text",
        "present_illness": "verbatim_text",
        "past_history": "verbatim_text",
        "discharge_time": "original_naive_clock",
        "discharge_diagnosis": "verbatim_text",
        "status": "original_integer",
    },
    "medical_records": {
        "consultation_time": "original_naive_clock",
        "symptom": "verbatim_text",
        "result": "verbatim_text",
        "status": "original_integer",
        "sign_time": "original_naive_clock",
    },
    "structured_medical_records": {
        "record_type": "original_integer",
        "chief_complaint": "verbatim_text",
        "present_illness": "verbatim_text",
        "past_history": "verbatim_text",
        "personal_history": "verbatim_text",
        "family_history": "verbatim_text",
        "physical_exam": "verbatim_text",
        "auxiliary_exam": "verbatim_text",
        "diagnosis": "verbatim_text",
        "treatment_plan": "verbatim_text",
        "status": "original_integer",
        "sign_time": "original_naive_clock",
        "create_time": "original_naive_clock",
        "update_time": "original_naive_clock",
    },
}
MAX_VARIABLES = 64
VARIABLE_SOURCE_ROLES = frozenset({"super_admin", "admin", "director", "doctor", "pharmacist"})
VARIABLE_USE = "research_variable_extraction"
VARIABLE_SCHEMA_VERSION = "research_variable_dictionary_v1"
LIMITATIONS = (
    "仅抽取所声明记录族的原字段或逐字区间，不代表全部医疗资料、研究变量有效性或临床结论。",
    "变量字典中的单位是人工声明；原文单位、数值、否定、未知和条件不做换算或医学归一化。",
    "缺原记录、NULL、未提出候选不等于未测、不适用、正常或疾病不存在；显式缺失状态须有原文证据。",
    "多条原记录保留全部候选和原时钟，不自动选择最近、有利结果或构造历史可得时间。",
    "读取和模型处理分别核验明确项目、对应用途及逐患者当前研究授权，包括超级管理员。",
)
