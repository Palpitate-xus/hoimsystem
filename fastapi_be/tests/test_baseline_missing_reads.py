"""Successful mounted reads for list/summary endpoints absent from the baseline.

Only routes whose query parameters have valid defaults are included. Detail and
state-changing workflows require their own fixtures and are not counted here.
"""

import pytest

from app.models import User
from tests.test_all_protected_routes import MATRIX

DEFAULT_READS = ['/api/campusManagement/getList',
 '/api/admission/getAvailableBeds',
 '/api/admission/getInpatientList',
 '/api/adverseEvent/getList',
 '/api/ai/admin/aki-assessments',
 '/api/ai/admin/bed-series',
 '/api/ai/coding-evidence/packages',
 '/api/ai/admin/news2-assessments',
 '/api/ai/admin/qsofa-assessments',
 '/api/ai/admin/roster-plans',
 '/api/ai/admin/supply-series',
 '/api/analytics/operations',
 '/api/antibiotic/ddds',
 '/api/antibiotic/submissionRate',
 '/api/blood/request/list',
 '/api/blood/reaction/list',
 '/api/breach/getList',
 '/api/clinicalPathway/getList',
 '/api/consumable/getList',
 '/api/discharge/getDischargedList',
 '/api/slotPool/getList',
 '/api/pharmacy/drugDamage/list',
 '/api/emar/list',
 '/api/emrTemplate/getList',
 '/api/medicalRecordQuality/getList',
 '/api/medicalRecordQuality/summary',
 '/api/equipment/maintenance/list',
 '/api/equipment/inspection/list',
 '/api/equipment/trace/list',
 '/api/examItem/getList',
 '/api/examRecord/getList',
 '/api/imaging/order/list',
 '/api/imaging/report/list',
 '/api/imaging/template/list',
 '/api/infection/case/list',
 '/api/infection/outbreakAlert',
 '/api/infection/disinfection/list',
 '/api/infection/exposure/list',
 '/api/mdro/getList',
 '/api/handHygiene/getList',
 '/api/notifiableDisease/getList',
 '/api/inpatientCharge/getSummary',
 '/api/ai/admin/gcs-sources',
 '/api/insurance/chronic/list',
 '/api/insurance/drg/rules',
 '/api/insurance/drg/analysis',
 '/api/insuranceCatalog/template',
 '/api/integration/outbox',
 '/api/integration/reconciliation',
 '/api/mdt/getList',
 '/api/navigation/nodes',
 '/api/navigation/admin/nodes',
 '/api/navigation/admin/edges',
 '/api/nursingRecord/getList',
 '/api/temperatureRecord/getList',
 '/api/cssd/getList',
 '/api/pivas/getList',
 '/api/rca/getList',
 '/api/patrol/getList',
 '/api/referral/getList',
 '/api/rxReviewRule/getList',
 '/api/surgery/perioperative/list',
 '/api/surgerySchedule/getList',
 '/api/anesthesiaRecord/getList',
 '/api/triage/keywords',
 '/api/triageDesk/getList',
 '/api/ward/getList']
POLICIES = {row["path"]: row["auth"] for row in MATRIX if row["method"] == "GET"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", DEFAULT_READS)
async def test_authorized_default_read_reaches_successful_handler(async_client, seed_data, auth_headers, path):
    users = {value.user_role: value for value in seed_data.values() if isinstance(value, User)}
    roles = POLICIES[path]
    headers = {}
    if roles != "PUBLIC":
        role = "super_admin" if roles == "ANY" or "super_admin" in roles else next(role for role in users if role in roles)
        headers = auth_headers(users[role].username)
    response = await async_client.get(path, headers=headers)
    assert response.status_code == 200, (path, response.status_code, response.text[:500])
    if "application/json" in response.headers.get("content-type", ""):
        data = response.json()
        if isinstance(data, dict) and "code" in data:
            assert data["code"] == 200, (path, data)
    else:
        assert response.content
