# HOIMSystem API 角色访问矩阵 (RBAC Matrix)

> 由 `fastapi_be/scripts/generate_rbac_matrix.py` 从源码自动生成，请勿手改。
> `✓`=可访问 | `PUBLIC`=无需登录 | 留空=不可访问

共 **1085** 个接口（PUBLIC 18 个 / 需登录 1067 个）。


### `admin.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/campusManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/campusManagement/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/campusManagement/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/campusManagement/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/doctorManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/doctorManagement/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/doctorManagement/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/patientManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/patientManagement/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/departmentManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/departmentManagement/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/departmentManagement/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/departmentManagement/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/notice/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/notice/create` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/notice/update` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/notice/delete` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |

### `admission.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/admission/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/admission/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/admission/detail` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/admission/update` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/admission/getAvailableBeds` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/admission/getInpatientList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `adverse_event.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/adverseEvent/create` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/adverseEvent/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/adverseEvent/updateStatus` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `adverse_reaction.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/adverseReaction/create` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/adverseReaction/getList` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/adverseReaction/updateStatus` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/document-extraction/context` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/runs/{run_id}/document-candidates` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/features` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/patients` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/service-options` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/operational-context` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/encounters` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/prescriptions` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/pathway-options` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/context` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/context` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/runs` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/runs` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/runs/{run_id}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/runs/{run_id}/cancel` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/runs/{run_id}/feedback` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `ai_admin.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/admin/features` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| PUT | `/api/ai/admin/features/{key}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/providers` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/speech-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/ecg-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/image-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/forecast-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/news2-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/aki-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/qsofa-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/sofa-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/roster-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/bed-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/surgery-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/supply-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers/{provider_id}/inventory-capabilities` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/runs` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/runs/{run_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/providers` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| PUT | `/api/ai/admin/providers/{provider_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/prompts/{key}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/prompts/{key}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/prompts/{key}/activate` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/knowledge` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/knowledge/{document_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/knowledge` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/knowledge/{document_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/pathway-sources` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/pathway-sources/{pathway_id}/import` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/grants` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/grants` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| DELETE | `/api/ai/admin/grants/{grant_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/audit` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/usage` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_aki.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/aki-assessments/candidates` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/aki-assessments` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ai/aki-assessments` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/aki-assessments/{assessment_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ai/aki-assessments/{assessment_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/aki-assessments` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/aki-assessments/{assessment_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_audio.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/audio-options` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/ai/audio-assets` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/ai/audio-assets` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/ai/audio-assets/{asset_id}` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/ai/audio-assets/{asset_id}/content` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/ai/audio-assets/{asset_id}/withdraw` |  | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/audio-assets` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/audio-assets/{asset_id}/purge` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_bed_series.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/bed-series/preview` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/bed-series` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/bed-series` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/bed-series/{series_id}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/bed-series/{series_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/bed-series/{series_id}/revoke` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/bed-series` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/bed-series/{series_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_bed_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/bed-sources/options` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/bed-sources/{kind}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/bed-sources/{kind}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/bed-sources/{kind}/{source_record_id}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/bed-sources/{kind}/{source_record_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/bed-sources/{kind}/{source_record_id}/revoke` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/bed-sources` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/bed-sources/{source_record_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_charge_reconciliation.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/charge-reconciliation/options` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/ai/charge-reconciliation/cases/preview` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/ai/charge-reconciliation/cases` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/ai/charge-reconciliation/cases` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/ai/charge-reconciliation/cases/{identifier}` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/ai/charge-reconciliation/cases/{identifier}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/charge-reconciliation/cases/{identifier}/revoke` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |

### `ai_clinical_training_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/clinical-training/lessons` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/clinical-training/lessons` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/clinical-training/lessons/{lesson_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/clinical-training/lessons/{lesson_id}/parts/{part_name}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/clinical-training/lessons/{lesson_id}/reviews` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/clinical-training/lessons/{lesson_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/clinical-training/reviews` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/clinical-training/reviews/{review_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/clinical-training/reviews/{review_id}/body` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/clinical-training/reviews/{review_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/clinical-training/published-lessons` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/clinical-training/published-lessons/{review_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/clinical-training/submissions` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/clinical-training/submissions` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/clinical-training/submission-management` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/clinical-training/submissions/{submission_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/clinical-training/submissions/{submission_id}/parts/{part_name}` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |

### `ai_clinical_training_tasks.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/clinical-training/task-descriptor` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/clinical-training/tasks` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/clinical-training/tasks` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/clinical-training/tasks/{run_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/clinical-training/tasks/{run_id}/parts/{part_name}` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/clinical-training/tasks/{run_id}/cancel` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/clinical-training/tasks/{run_id}/feedback` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/clinical-training/tasks/{run_id}/trace` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_coding_evidence.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/coding-evidence/options` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/ai/coding-evidence/homes` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/ai/coding-evidence/rules` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/coding-evidence/cases/preview` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/ai/coding-evidence/cases` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/ai/coding-evidence/cases` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/ai/coding-evidence/cases/{identifier}` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/ai/coding-evidence/cases/{identifier}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/coding-evidence/cases/{identifier}/revoke` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/ai/coding-evidence/packages` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/ai/coding-evidence/packages` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/coding-evidence/packages/{identifier}` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/ai/coding-evidence/packages/{identifier}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/coding-evidence/packages/{identifier}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_deidentification.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/deidentification/fields` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/cases/directory` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/cases/preview` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/cases` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/deidentification/cases/{case_id}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/cases/{case_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/deidentification/cases/{case_id}/revoke` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/reviews` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/deidentification/reviews/{review_id}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/reviews/{review_id}/residual-review` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/reviews/{review_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/deidentification/reviews/{review_id}/revoke` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/releases` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/deidentification/releases/{release_id}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/releases/{release_id}/authority-review` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/releases/{release_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/deidentification/releases/{release_id}/revoke` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/releases/{release_id}/download` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |

### `ai_deidentification_tasks.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/deidentification/tasks/context` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/deidentification/tasks` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/deidentification/tasks/{run_id}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/deidentification/tasks/{run_id}/technical` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/deidentification/tasks/{run_id}/source` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/deidentification/tasks/{run_id}/result` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/deidentification/tasks/{run_id}/trace` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/deidentification/tasks/{run_id}/cancel` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/deidentification/tasks/{run_id}/parts/{part}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |

### `ai_document_change.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/admin/document-changes/options` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-changes/target-snapshot` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-changes/capture` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-changes/links` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/document-changes/links/{link_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-changes/links/{link_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-changes/links/{link_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-changes/scopes` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/document-changes/scopes/{scope_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/document-changes/scopes/{scope_id}/public-source` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-changes/scopes/{scope_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-changes/scopes/{scope_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/document-changes/links` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/document-changes/scopes` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_document_change_runs.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/document-change/context` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/runs/{run_id}/document-change/source` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/runs/{run_id}/document-change/scope` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/runs/{run_id}/document-change/result` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/runs/{run_id}/document-change/source` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/runs/{run_id}/document-change/scope` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/runs/{run_id}/document-change/result` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_document_evidence.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/admin/document-evidence/options` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-evidence/originals` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/document-evidence/originals` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/document-evidence/originals/{original_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-evidence/originals/{original_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-evidence/originals/{original_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-evidence/candidates` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/document-evidence/candidates` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/document-evidence/candidates/{candidate_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-evidence/candidates/{candidate_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-evidence/candidates/{candidate_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-evidence/candidates/{candidate_id}/publish` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/document-evidence/publications` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/document-evidence/publications/{publication_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/document-evidence/publications/{publication_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_drug_label_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/drug-label-sources/options` |  | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/drug-label-sources/catalog` |  | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/drug-label-sources` |  | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/drug-label-sources` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/drug-label-sources/{binding_id}` |  | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/drug-label-sources/{binding_id}/professional-review` |  |  |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/drug-label-sources/{binding_id}/professional-review/revoke` |  | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/drug-label-sources/{binding_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/drug-label-sources/{binding_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_drug_label_tasks.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/drug-label/context` |  | ✓ |  |  |  |  | ✓ |  |  |  |  |  |

### `ai_ecg.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/ecg-options` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| POST | `/api/ai/ecg-assets` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/ai/ecg-assets` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/ai/ecg-assets/{asset_id}` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/ai/ecg-assets/{asset_id}/window` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/ai/ecg-assets/{asset_id}/content` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| POST | `/api/ai/ecg-assets/{asset_id}/withdraw` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/ai/admin/ecg-assets` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/ecg-assets/{asset_id}/purge` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_feedback_admin.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/admin/review-sources` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/review-sources/{review_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/review-excerpts` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/review-excerpts/{excerpt_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/review-excerpts` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/review-excerpts/{excerpt_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_forecast.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/admin/forecast-series` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/forecast-series/preview` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/forecast-series` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/forecast-series/{series_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/forecast-series/{series_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/forecast-series` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `ai_images.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/image-options` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/ai/image-orders` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| POST | `/api/ai/image-assets` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/ai/image-assets` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/ai/image-assets/{asset_id}` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/ai/image-assets/{asset_id}/pixels` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/ai/image-assets/{asset_id}/content` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| POST | `/api/ai/image-assets/{asset_id}/withdraw` |  | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/ai/admin/image-assets` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/image-assets/{asset_id}/purge` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_infection_cluster_profiles.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/infection-cluster/local-profiles` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/infection-cluster/local-profiles` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/infection-cluster/local-profiles/{profile_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/local-profiles/{profile_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/local-profiles/{profile_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/infection-cluster/local-configuration` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| PUT | `/api/ai/infection-cluster/local-configuration` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_infection_cluster_scenarios.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/infection-cluster/local-implementation` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/infection-cluster/departments` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/scenarios` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/infection-cluster/scenarios` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/infection-cluster/scenarios/{scenario_id}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/scenarios/{scenario_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/scenarios/{scenario_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_infection_cluster_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/infection-cluster/grants` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/definitions` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/case-reviews` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/infection-cluster/registry/{kind}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/infection-cluster/registry/{kind}/{record_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/registry/{kind}/{record_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/registry/{kind}/{record_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/roots/preview` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/snapshots` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/infection-cluster/snapshots` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/infection-cluster/snapshots/{snapshot_id}/parts/{part}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |

### `ai_infection_cluster_tasks.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/infection-cluster/context` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/tasks` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/infection-cluster/tasks` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/infection-cluster/tasks/{run_id}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/infection-cluster/tasks/{run_id}/parts/{part}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/infection-cluster/tasks/{run_id}/cancel` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `ai_inventory_native_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/inventory-native-sources/options` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/inventory-native-sources/legacy-capture` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/inventory-native-sources/preview` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/admin/inventory-native-sources` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/inventory-native-sources/{record_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/inventory-native-sources/{kind}` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/inventory-native-sources/{kind}` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/inventory-native-sources/{kind}/{record_id}` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/inventory-native-sources/{kind}/{record_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/inventory-native-sources/{kind}/{record_id}/revoke` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |

### `ai_inventory_scenarios.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/inventory-scenarios/preview` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/inventory-scenarios` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/inventory-scenarios` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/inventory-scenarios/{scenario_id}` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/inventory-scenarios/{scenario_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/inventory-scenarios/{scenario_id}/revoke` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/admin/inventory-scenarios` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/inventory-scenarios/{scenario_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_lab_mappings.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/admin/lab-mappings/options` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/lab-mappings` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/lab-mappings` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/lab-mappings/{mapping_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/lab-mappings/{mapping_id}/publish` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/lab-mappings/{mapping_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_news2.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/news2-assessments/candidates` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/news2-assessments` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ai/news2-assessments` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/news2-assessments/{assessment_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ai/news2-assessments/{assessment_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/news2-assessments` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/news2-assessments/{assessment_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_observation_windows.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/observation-windows` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/observation-windows` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/observation-windows/{window_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ai/observation-windows/{window_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/observation-windows` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/observation-windows/{window_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_operations_support_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/operations-support/originals` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/operations-support/originals` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/originals/{original_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/originals/{original_id}/body` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/operations-support/originals/{original_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/releases` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/operations-support/releases` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/releases/{release_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/releases/{release_id}/draft` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/releases/{release_id}/source` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/operations-support/releases/{release_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/operations-support/releases/{release_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/cases` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/operations-support/cases` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/cases/{case_id}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/cases/{case_id}/parts/{part_name}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/operations-support/cases/{case_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_operations_support_tasks.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/operations-support/task-descriptor` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/operations-support/tasks` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/tasks` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/tasks/{run_id}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/tasks/{run_id}/parts/{part_name}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/operations-support/tasks/{run_id}/cancel` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/operations-support/tasks/{run_id}/trace` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_qsofa.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/qsofa-assessments/candidates` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/qsofa-assessments` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ai/qsofa-assessments` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/qsofa-assessments/{assessment_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ai/qsofa-assessments/{assessment_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/qsofa-assessments` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/qsofa-assessments/{assessment_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_rca_evidence.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/admin/rca-evidence/options` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/rca-evidence/grants` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/rca-evidence/grants/{grant_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/rca-evidence/grants/{grant_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/rca-evidence/events/{event_id}/directory/{kind}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/rca-evidence/events/{event_id}/capture` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/rca-evidence/events/{event_id}/legacy-witness` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/rca-evidence/originals` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/rca-evidence/originals/{original_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/rca-evidence/originals/{original_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/rca-evidence/originals/{original_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/rca-evidence/cases` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/rca-evidence/cases/{case_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/rca-evidence/cases/{case_id}/public-source` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/rca-evidence/cases/{case_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/rca-evidence/cases/{case_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_rca_evidence_tasks.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/rca-evidence/context` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/runs/{run_id}/rca-evidence/source` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/runs/{run_id}/rca-evidence/case` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/runs/{run_id}/rca-evidence/result` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/runs/{run_id}/rca-evidence/receipt` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/runs/{run_id}/rca-evidence/source` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/runs/{run_id}/rca-evidence/case` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/runs/{run_id}/rca-evidence/result` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/runs/{run_id}/rca-evidence/receipt` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_research_cohort_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/research-cohort/scopes` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/research-cohort/scopes/{scope_id}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/scopes/{scope_id}/authorization-review` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/scopes/{scope_id}/review` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/scopes/{scope_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/project-acls` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/research-cohort/project-acls/{record_id}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/project-acls/{record_id}/review` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/project-acls/{record_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/patient-authorizations` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/research-cohort/patient-authorizations/{record_id}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/patient-authorizations/{record_id}/authorization-review` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/patient-authorizations/{record_id}/review` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/patient-authorizations/{record_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/cases/preview` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/cases` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/research-cohort/cases` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/research-cohort/cases/{case_id}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/cases/{case_id}/review` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/cases/{case_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/research-cohort/scopes` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/research-cohort/project-acls` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/research-cohort/patient-authorizations` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `ai_research_cohort_tasks.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/research-cohort/tasks` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/research-cohort/tasks` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/research-cohort/tasks/{run_id}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/ai/research-cohort/tasks/{run_id}/cancel` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/ai/research-cohort/tasks/{run_id}/parts/{part}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `ai_research_variables_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/research-variables/dictionaries` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/research-variables/dictionaries` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/research-variables/dictionaries/{dictionary_id}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/research-variables/dictionaries/{dictionary_id}/parts/{part}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/research-variables/dictionaries/{dictionary_id}/definition-review` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/research-variables/dictionaries/{dictionary_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/research-variables/dictionaries/{dictionary_id}/revoke` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/research-variables/batches/preview` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/research-variables/batches` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/research-variables/batches` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/research-variables/batches/{batch_id}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/research-variables/batches/{batch_id}/parts/{part}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/research-variables/batches/{batch_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/research-variables/batches/{batch_id}/revoke` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/research-variables/technical/{directory}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/research-variables/technical/{directory}/{record_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_research_variables_tasks.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/research-variables/context` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/runs/{run_id}/research-variables/{part}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/admin/runs/{run_id}/research-variables/{part}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_risk_rules.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/admin/risk-rule-profiles/options` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/risk-rule-profiles` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/risk-rule-profiles` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/risk-rule-profiles/{rule_profile_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/risk-rule-profiles/{rule_profile_id}/publish` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/risk-rule-profiles/{rule_profile_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_roster_plans.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/roster-plans/preview` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/roster-plans` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/roster-plans` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/roster-plans/{plan_id}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/roster-plans/{plan_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/roster-plans/{plan_id}/revoke` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/roster-plans` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/roster-plans/{plan_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_roster_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/roster-sources/options` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/roster-sources/{kind}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/roster-sources/{kind}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/roster-sources/{kind}/{source_record_id}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/roster-sources/{kind}/{source_record_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/roster-sources/{kind}/{source_record_id}/revoke` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/roster-sources` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/roster-sources/{source_record_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_satisfaction_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/satisfaction-sources/options` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/satisfaction-sources/doctors` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/satisfaction-sources/cases/preview` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/satisfaction-sources/cases` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/satisfaction-sources/cases` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/satisfaction-sources/cases/{identifier}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/satisfaction-sources/cases/{identifier}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/satisfaction-sources/cases/{identifier}/revoke` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |

### `ai_sofa.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/sofa-assessments/candidates` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/sofa-assessments` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ai/sofa-assessments` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/sofa-assessments/{assessment_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ai/sofa-assessments/{assessment_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/sofa-assessments` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/sofa-assessments/{assessment_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_sofa_change.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/sofa-change-assessments/candidates` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/sofa-change-assessments` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ai/sofa-change-assessments` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/sofa-change-assessments/{change_assessment_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ai/sofa-change-assessments/{change_assessment_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/sofa-change-assessments` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/sofa-change-assessments/{change_assessment_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_supply_series.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/ai/supply-series/preview` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/supply-series` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/supply-series` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/supply-series/{series_id}` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/supply-series/{series_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/supply-series/{series_id}/revoke` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/admin/supply-series` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/supply-series/{series_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_supply_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/supply-sources/options` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/supply-sources/units` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/supply-sources/units` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/supply-sources/units/{record_id}` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/supply-sources/units/{record_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/supply-sources/units/{record_id}/revoke` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/supply-sources/daily` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/supply-sources/daily` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/supply-sources/daily/{record_id}` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/supply-sources/daily/{record_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/supply-sources/daily/{record_id}/revoke` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/ai/supply-sources/preview` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/ai/admin/supply-sources` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/supply-sources/{record_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `ai_surgery_scenarios.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/surgery-scenarios` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/surgery-scenarios` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/surgery-scenarios/{scenario_id}` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/surgery-scenarios/{scenario_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/surgery-scenarios/{scenario_id}/revoke` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |

### `ai_surgery_sources.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/surgery-sources/options` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/ai/surgery-sources/preview` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/ai/surgery-registry/{kind}` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/ai/surgery-registry/{kind}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/surgery-registry/{kind}/{record_id}` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/ai/surgery-registry/{kind}/{record_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/surgery-registry/{kind}/{record_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/surgery-sources/{kind}` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/ai/surgery-protected-capsules` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/surgery-sources/{kind}` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/ai/surgery-sources/{kind}/{record_id}` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/ai/surgery-sources/{kind}/{record_id}/review` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/surgery-sources/{kind}/{record_id}/revoke` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `ai_vasoactive_mappings.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ai/admin/vasoactive-drug-mappings/options` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/vasoactive-drug-mappings` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/vasoactive-drug-mappings` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/vasoactive-drug-mappings/{mapping_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/vasoactive-drug-mappings/{mapping_id}/publish` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/ai/admin/vasoactive-drug-mappings/{mapping_id}/revoke` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `allergy.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/allergy/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/allergy/create` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| PUT | `/api/allergy/update` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/allergy/disable` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |

### `analytics.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/analytics/operations` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/analytics/refresh` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `antibiotic.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/antibiotic/grade/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/antibiotic/grade/save` | ✓ | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/antibiotic/approval/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/antibiotic/approval/list` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/antibiotic/approval/review` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/antibiotic/ddds` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/antibiotic/submissionRate` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |

### `backup.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/backup/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/backup/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/backup/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/backup/restore` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/backup/download/{filename}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `blood.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/blood/request/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/blood/request/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/blood/request/review` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/blood/recheck` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/blood/crossMatch` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/blood/issue` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/blood/reaction/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/blood/reaction/create` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |

### `charge.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/chargeManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/chargeManagement/charge` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/chargeManagement/refund` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/invoice/getList` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/windowRegistration/schedules` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  | ✓ |  |
| GET | `/api/windowRegistration/patient` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  | ✓ |  |
| GET | `/api/windowRegistration/appointments` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  | ✓ |  |
| POST | `/api/windowRegistration/appointmentConfirm` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  | ✓ |  |
| POST | `/api/windowRegistration/appointmentCancel` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  | ✓ |  |
| POST | `/api/invoice/create` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/invoice/print` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/invoice/pdf/{invoice_id}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/windowRegistration/create` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  | ✓ |  |
| POST | `/api/windowRegistration/cancel` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  | ✓ |  |
| POST | `/api/dailySettlement/report` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/dailySettlement/byPayDate` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/payment/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/payment/query/{payment_no}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/payment/mockNotify` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/payment/getList` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |

### `charge_item.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/chargeItem/list` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/chargeItem/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| PUT | `/api/chargeItem/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/chargeItem/toggle` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `checkin.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/checkIn/getAppointments` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/checkIn/checkIn` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/api/breach/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/breach/checkSuspend` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `clinical_pathway.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/clinicalPathway/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/clinicalPathway/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/clinicalPathway/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/clinicalPathway/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `consumable.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/consumable/getList` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/consumable/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/consumable/update` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/consumable/delete` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |

### `data_import_export.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/dataImportExport/template/{entity}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/dataImportExport/import/{entity}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/dataImportExport/export/{entity}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `diagnosis_template.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/diagnosisTemplate/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/diagnosisTemplate/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| PUT | `/api/diagnosisTemplate/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/diagnosisTemplate/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/diagnosisTemplate/apply` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `digital_signature.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/digitalSignature/sign` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/digitalSignature/verify` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `discharge.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/discharge/doDischarge` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/discharge/getSummary` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/discharge/updateSummary` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/discharge/getDischargedList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `doctor.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/doctorManagement/register` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/doctorScheduleManagement/register` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/doctorScheduleManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/pharmaceuticalManagement/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmaceuticalManagement/getList` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmaceuticalManagement/update` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmaceuticalManagement/delete` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmaceuticalManagement/restore` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmaceuticalManagement/stock_query` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmaceuticalManagement/lowStock` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmaceuticalManagement/nearExpiry` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/prescriptionManagement/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/prescriptionManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/prescriptionManagement/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/clinicalDiagnosis/review` |  |  | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/clinicalDiagnosis/review` |  |  | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecord/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecord/sign` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/labOrder/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/labOrder/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/attendance/checkIn` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/attendance/checkOut` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/attendance/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/slotPool/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/slotPool/adjust` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `drug_damage.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/pharmacy/drugDamage/list` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/drugDamage/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/drugDamage/approve` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/pharmacy/drugDamage/reject` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `emar.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/emar/verify` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/emar/administer` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/emar/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/emar/medication/barcode` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |

### `emergency.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/emergency/triage/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/emergency/triage/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| PUT | `/api/emergency/triage/update` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/emergency/rescue/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/emergency/rescue/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/emergency/observation/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/emergency/observation/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| PUT | `/api/emergency/observation/update` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/emergency/greenChannel/create` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/emergency/greenChannel/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/emergency/greenChannel/approve` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/emergency/greenChannel/close` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/emergency/medicalRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/emergency/medicalRecord/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| PUT | `/api/emergency/medicalRecord/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/emergency/medicalRecord/sign` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `emr.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/emrTemplate/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/emrTemplate/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/emrTemplate/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/emrTemplate/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/emrTemplate/detail` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/structuredMedicalRecord/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/structuredMedicalRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/structuredMedicalRecord/detail` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/structuredMedicalRecord/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/structuredMedicalRecord/sign` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/structuredMedicalRecord/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/progressNote/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/progressNote/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/progressNote/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/wardRound/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/wardRound/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/wardRound/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/medicalRecordQuality/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordQuality/check` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/medicalRecordQuality/summary` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `equipment.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/equipment/list` | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/equipment/create` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/equipment/status` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/equipment/maintenance/list` | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/equipment/maintenance/create` | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/equipment/maintenance/status` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/equipment/inspection/list` | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/equipment/inspection/create` | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  |  |  |
| GET | `/api/equipment/trace/list` | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/equipment/trace/create` | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/equipment/inventory/check` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |

### `events.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/events/recent` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/events/stream` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `exam.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/examPackage/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/examPackage/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examPackage/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examPackage/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/examItem/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/examItem/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examItem/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examItem/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/examAppointment/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/examAppointment/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |
| POST | `/api/examAppointment/updateStatus` | ✓ | ✓ | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |
| GET | `/api/examRecord/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/examRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examRecord/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/examRecord/complete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/examResult/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/examResult/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/examReport/getDetail` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `family_member.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/familyMember/list` |  |  |  |  |  |  |  |  | ✓ |  |  |  |
| POST | `/api/familyMember/create` |  |  |  |  |  |  |  |  | ✓ |  |  |  |
| PUT | `/api/familyMember/update` |  |  |  |  |  |  |  |  | ✓ |  |  |  |
| DELETE | `/api/familyMember/delete` |  |  |  |  |  |  |  |  | ✓ |  |  |  |

### `followup.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/followUpAppointment/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/followUp/createPlan` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/followUp/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/followUp/record` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `home_icd.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/homeIcd/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/homeIcd/uncoded` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/homeIcd/bind` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/homeIcd/unbind` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/homeIcd/setPrimary` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/homeIcd/statistics` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `icd10.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/icd10/diagnosis/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/icd10/diagnosis/create` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| PUT | `/api/icd10/diagnosis/update` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/icd10/operation/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/icd10/operation/create` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| PUT | `/api/icd10/operation/update` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |

### `imaging.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/imaging/order/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/order/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/imaging/order/status` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| POST | `/api/imaging/order/viewer` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/imaging/report/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/report/save` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| POST | `/api/imaging/report/submit` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| POST | `/api/imaging/report/review` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/imaging/template/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/template/save` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| GET | `/api/imaging/viewer/{imaging_order_id}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/imaging/film/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/imaging/film/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  | ✓ | ✓ |  |  |
| POST | `/api/imaging/film/status` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |

### `infection.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/infection/case/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infection/case/create` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infection/case/status` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/infection/outbreakAlert` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/infection/report` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/infection/disinfection/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infection/disinfection/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/infection/exposure/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infection/exposure/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infection/exposure/handle` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |

### `infection_control.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/mdro/getList` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/mdro/create` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/mdro/release` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/handHygiene/getList` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/handHygiene/create` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/notifiableDisease/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| POST | `/api/notifiableDisease/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| POST | `/api/notifiableDisease/submit` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| POST | `/api/notifiableDisease/audit` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/notifiableDisease/correct` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |

### `infusion.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/infusion/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/infusion/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infusion/execute` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infusion/observe` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infusion/complete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/infusion/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `injection.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/injection/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/injection/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/injection/execute` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/injection/complete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/injection/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `inpatient_charge.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/inpatientCharge/getList` | ✓ | ✓ |  |  | ✓ | ✓ |  |  |  |  |  |  |
| GET | `/api/inpatientCharge/getDailyBill` | ✓ | ✓ |  |  | ✓ | ✓ |  |  |  |  |  |  |
| POST | `/api/inpatientCharge/settle` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/inpatientCharge/refund` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/inpatientCharge/getSummary` | ✓ | ✓ |  |  | ✓ | ✓ |  |  |  |  |  |  |
| POST | `/api/inpatientCharge/depositRecharge` | ✓ | ✓ |  |  | ✓ | ✓ |  |  |  |  |  |  |
| GET | `/api/inpatientCharge/depositBalance` | ✓ | ✓ |  |  | ✓ | ✓ |  |  |  |  |  |  |

### `inpatient_gcs.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/inpatient-gcs` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatient-gcs` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/inpatient-gcs/{gcs_observation_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatient-gcs/{gcs_observation_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/gcs-sources` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/gcs-sources/{gcs_observation_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `inpatient_laboratory.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/inpatient-laboratory/candidates` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/inpatient-laboratory/sources` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatient-laboratory/sources` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/inpatient-laboratory/sources/{lab_source_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatient-laboratory/sources/{lab_source_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/lab-sources` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/lab-sources/{lab_source_id}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `inpatient_observations.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/inpatient-observations/points` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatient-observations/points` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/inpatient-observations/points/{observation_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatient-observations/points/{observation_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/inpatient-observations/urine-intervals` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatient-observations/urine-intervals` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/inpatient-observations/urine-intervals/{interval_id}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatient-observations/urine-intervals/{interval_id}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |

### `inpatient_order.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/inpatientOrder/getList` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatientOrder/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/inpatientOrder/audit` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/inpatientOrder/stop` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/inpatientOrder/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/inpatientOrder/getExecutionList` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatientOrder/execute` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `inpatient_support.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/inpatient-support/options` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/inpatient-support/infection-evidence` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/inpatient-support/vasoactive/origin-candidates` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/inpatient-support/vasoactive/mapping-candidates` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/inpatient-support/{kind}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatient-support/{kind}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/inpatient-support/{kind}/{identifier}` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/inpatient-support/{kind}/{identifier}/revoke` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/support-sources/{kind}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/ai/admin/support-sources/{kind}/{identifier}` |  | ✓ |  |  |  |  |  |  |  |  |  |  |

### `insurance.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/insurance/catalog/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/insurance/catalog/save` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/insurance/settlement/list` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/insurance/settlement/create` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/integration/insurance/settlement` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/api/insurance/chronic/list` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/insurance/chronic/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/insurance/drg/group` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/insurance/drg/rule` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| GET | `/api/insurance/drg/rules` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/insurance/drg/autoGroup` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/insurance/drg/analysis` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/insurance/control/warnings` | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |

### `insurance_catalog.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/insuranceCatalog/getList` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/insuranceCatalog/create` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/insuranceCatalog/update` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/insuranceCatalog/delete` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/insuranceCatalog/import` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/insuranceCatalog/template` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |

### `integration.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/integration/lis/result` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/integration/pacs/report` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/integration/payment/notify` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |

### `integration_outbox.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/integration/outbox` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/integration/outbox/{event_id}/retry` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/integration/reconciliation` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `inventory_adjustment.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/pharmacy/inventoryAdjustment/list` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/inventoryAdjustment/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/inventoryAdjustment/approve` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/pharmacy/inventoryAdjustment/reject` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `lab.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/lab/sampleReceive` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/lab/sampleReject` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| GET | `/api/lab/sampleTracking` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/labResult/create` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/labResult/audit` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| GET | `/api/labResult/getPending` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| GET | `/api/labResult/getList` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| GET | `/api/labResult/getCritical` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/labResult/critical/notify` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/labResult/critical/acknowledge` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/labResult/critical/handle` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/labResult/detail` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |

### `lab_package.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/labPackage/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |
| POST | `/api/labPackage/create` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| PUT | `/api/labPackage/update` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |

### `lab_qc.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/labQc/list` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| POST | `/api/labQc/create` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |
| GET | `/api/labQc/summary` | ✓ | ✓ |  |  |  |  |  |  |  | ✓ |  |  |

### `mdt.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/mdt/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/mdt/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/mdt/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/mdt/approvalList` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/mdt/approval` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |

### `medical_record_archive.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/medicalRecordArchive/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordArchive/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordArchive/archive` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordArchive/borrow` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/medicalRecordArchive/borrowRequests` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordArchive/borrowApprove` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordArchive/return` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordArchive/seal` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |

### `medical_record_home.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/medicalRecordHome/admissions` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/medicalRecordHome/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordHome/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| PUT | `/api/medicalRecordHome/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordHome/submit` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `medical_record_home_quality.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/medicalRecordHomeQuality/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/medicalRecordHomeQuality/check` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/medicalRecordHomeQuality/summary` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `monitor.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/monitor/summary` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `navigation.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/navigation/nodes` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/navigation/route` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/navigation/route/departments` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/navigation/admin/nodes` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/navigation/admin/nodes` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| PUT | `/api/navigation/admin/nodes` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| DELETE | `/api/navigation/admin/nodes` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/navigation/admin/edges` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/navigation/admin/edges` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| PUT | `/api/navigation/admin/edges` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| DELETE | `/api/navigation/admin/edges` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `nursing.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/nursingAssessment/list` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/nursingAssessment/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| PUT | `/api/nursingAssessment/update` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/nursingAssessment/complete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/nursingPlan/list` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/nursingPlan/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| PUT | `/api/nursingPlan/update` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/criticalCareRecord/list` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/criticalCareRecord/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/surgeryNursingRecord/list` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/surgeryNursingRecord/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/nursingRecord/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/nursingRecord/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/nursingRecord/delete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/temperatureRecord/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/temperatureRecord/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/temperatureRecord/delete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `observability.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/health/live` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/health/ready` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/metrics` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |

### `ops_extension.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/cssd/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/cssd/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/cssd/transition` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/pivas/getList` | ✓ | ✓ |  |  | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/pivas/create` | ✓ | ✓ |  |  | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/pivas/transition` | ✓ | ✓ |  |  | ✓ |  | ✓ |  |  |  |  |  |
| GET | `/api/icuScore/getList` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/icuScore/create` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| GET | `/api/pathwayEnrollment/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/pathwayEnrollment/enroll` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/pathwayEnrollment/record` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/pathwayEnrollment/variation` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/pathwayEnrollment/exit` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `patient.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/appointmentManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/appointmentManagement/appointmentList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/appointmentManagement/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/appointmentManagement/cancel` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/registrationManagement/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/registrationManagement/registrationList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/registrationManagement/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/registrationManagement/cancel` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/medicalRecord/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/medicalRecord/detail` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/healthRecord/getProfile` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/healthRecord/getVisits` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/review/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `patient_card.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/patientCard/list` | ✓ | ✓ |  |  |  |  |  |  | ✓ |  | ✓ |  |
| POST | `/api/patientCard/issue` | ✓ | ✓ |  |  |  |  |  |  |  |  | ✓ |  |
| POST | `/api/patientCard/lost` | ✓ | ✓ |  |  |  |  |  |  | ✓ |  | ✓ |  |
| POST | `/api/patientCard/cancel` | ✓ | ✓ |  |  |  |  |  |  |  |  | ✓ |  |

### `performance.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/performance/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/performance/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/performance/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/performance/submit` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/performance/audit` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `pharmacy.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/pharmacy/batch/list` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmacy/batch/ledger` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmacy/dispenseList` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/audit` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/dispense` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmacy/verificationList` | ✓ | ✓ |  |  | ✓ |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/verify` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/pharmacy/return` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/stockCheck` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/pharmacy/review` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmacy/reviewList` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/pharmacy/dispenseStats` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |

### `prescription_template.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/prescriptionTemplate/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/prescriptionTemplate/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| PUT | `/api/prescriptionTemplate/update` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/prescriptionTemplate/delete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/prescriptionTemplate/apply` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `purchase.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/purchase/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/purchase/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/purchase/approve` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/purchase/storage` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/purchase/cancel` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `quality_management.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/rca/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/rca/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/rca/advance` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/hqms/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/hqms/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/hqms/batchImport` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/hqms/submit` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `queue.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/queue/emergency` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/queue/reorder` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/queue/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/queue/progress` |  |  |  |  |  |  |  |  | ✓ |  |  |  |
| POST | `/api/queue/callNext` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/queue/pass` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/queue/skip` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/patrol/create` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/patrol/getList` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |

### `referral.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/referral/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/referral/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/referral/updateStatus` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/referral/approvalList` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/referral/approval` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |

### `report.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/report/outpatientVolume` | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |  |
| POST | `/api/report/finance` | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |  |
| POST | `/api/report/pharmaceutical` | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |  |
| POST | `/api/report/doctorWorkload` | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |  |
| POST | `/api/report/departmentStats` | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |  |  |  |  |  |

### `research.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/research/export/tables` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/research/export` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/research/export/package` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/research/export/audit` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `rx_review_rule.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/rxReviewRule/getList` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/rxReviewRule/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/rxReviewRule/update` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/rxReviewRule/delete` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/rxReviewRule/check` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| GET | `/api/clinicalProfile/{patient_id}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |
| POST | `/api/clinicalProfile/{patient_id}` | ✓ | ✓ | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |

### `schedule_change.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/scheduleChange/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/scheduleChange/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/scheduleChange/approve` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |
| POST | `/api/scheduleChange/reject` | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |  |

### `scheduler.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/scheduler/status` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/scheduler/run/{job_name}` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `shift_handover.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/shiftHandover/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/shiftHandover/list` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/shiftHandover/receive` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `skin_test.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/skinTest/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/skinTest/list` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/skinTest/administer` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/skinTest/assess` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/skinTest/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |

### `special_drug.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/specialDrug/create` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| GET | `/api/specialDrug/list` | ✓ | ✓ |  |  |  |  | ✓ |  |  |  |  |  |
| POST | `/api/specialDrug/approve` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/specialDrug/reject` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |

### `surgery.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/surgery/perioperative/list` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgery/perioperative/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgery/perioperative/status` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/surgeryApplication/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgeryApplication/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgeryApplication/approve` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgeryApplication/cancel` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/surgerySchedule/getList` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgerySchedule/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgerySchedule/start` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| POST | `/api/surgerySchedule/complete` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/anesthesiaRecord/getList` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |
| POST | `/api/anesthesiaRecord/create` | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |  |
| GET | `/api/surgery/antibioticCompliance` | ✓ | ✓ | ✓ | ✓ | ✓ |  |  |  |  |  |  |  |

### `system.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/log/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/log/stats` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/dict/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/dict/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/dict/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/dict/delete` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/config/getList` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/config/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| POST | `/api/message/send` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/message/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/message/read` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `triage.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/navigation/faq` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/navigation/faq/create` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| PUT | `/api/navigation/faq/update` | ✓ | ✓ |  |  |  |  |  |  |  |  |  |  |
| GET | `/api/navigation/departments` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/triage/suggest` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/api/triage/keywords` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |

### `triage_desk.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/triageDesk/create` | ✓ | ✓ |  |  | ✓ |  |  | ✓ |  |  |  |  |
| GET | `/api/triageDesk/getList` | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |  |  |
| POST | `/api/triageDesk/updateStatus` | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |  |  |
| POST | `/api/triageDesk/update` | ✓ | ✓ |  |  |  |  |  | ✓ |  |  |  |  |

### `upload.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/upload/avatar` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/upload/report` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/uploads/avatars/{filename}` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/api/uploads/reports/{filename}` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `user.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/test` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| GET | `/api/publicKey` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/login` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/register` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/userInfo` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |
| POST | `/api/logout` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/user/getList` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/user/updateRole` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/user/resetPassword` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/user/delete` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| GET | `/api/prepaid/getBalance` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |
| POST | `/api/prepaid/recharge` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/prepaid/deduct` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| POST | `/api/prepaid/refund` | ✓ | ✓ |  |  |  | ✓ |  |  |  |  |  |  |
| GET | `/api/prepaid/getTransactions` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |  |

### `version.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/version` |  |  |  |  |  |  |  |  |  |  |  | PUBLIC |

### `vitalsign.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| POST | `/api/vitalSign/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/vitalSign/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |

### `ward.py`

| 方法 | 路径 | admin | super_admin | director | doctor | nurse | cashier | pharmacist | guide | patient | lab_technician | registrar | PUBLIC |
|------|------|------|------|------|------|------|------|------|------|------|------|------|------|
| GET | `/api/ward/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ward/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ward/update` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/ward/delete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| GET | `/api/bed/getList` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/bed/create` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/bed/update` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
| POST | `/api/bed/delete` | ✓ | ✓ |  |  | ✓ |  |  |  |  |  |  |  |
