"""用血安全回归测试：ABO 相容性、超量发血拦截、血袋防重。"""
import datetime

import pytest

from app.models import BloodCrossMatch, BloodIssue, BloodRequest


def _make_request(db, patient_id, blood_type, volume=2, status=1, verified=1):
    req = BloodRequest(
        patient_id=patient_id,
        applicant_id=1,
        blood_type=blood_type,
        component="红细胞",
        volume=volume,
        reason="手术备血",
        status=status,
        blood_type_verified=verified,
        create_time=datetime.datetime.now(),
    )
    db.add(req)
    db.commit()
    return req


@pytest.mark.asyncio
class TestBloodSafety:
    async def test_crossmatch_rejects_abo_incompatible(self, async_client, seed_data, auth_headers, db_session):
        """A 型受血者配 B 型血必须被拒绝（防急性溶血）。"""
        req = _make_request(db_session, seed_data["patient"].patient_id, "A")
        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/blood/crossMatch",
            headers=headers,
            json={"request_id": req.request_id, "donor_blood_type": "B", "result": "相合", "pass_flag": 1},
        )
        assert r.json()["code"] == 400
        assert "不相容" in r.json()["msg"]
        assert db_session.query(BloodCrossMatch).count() == 0, "不相容配血记录不得落库"

    async def test_crossmatch_accepts_compatible(self, async_client, seed_data, auth_headers, db_session):
        req = _make_request(db_session, seed_data["patient"].patient_id, "A+")
        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/blood/crossMatch",
            headers=headers,
            json={"request_id": req.request_id, "donor_blood_type": "O-", "result": "相合", "pass_flag": 1},
        )
        assert r.json()["code"] == 200

    async def test_issue_rejects_over_volume(self, async_client, seed_data, auth_headers, db_session):
        """申请 2U 发 99U 必须被拒绝。"""
        req = _make_request(db_session, seed_data["patient"].patient_id, "A", volume=2)
        db_session.add(BloodCrossMatch(request_id=req.request_id, donor_blood_type="A", result="相合", pass_flag=1, operator_id=1, match_time=datetime.datetime.now()))
        db_session.commit()
        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post(
            "/api/blood/issue",
            headers=headers,
            json={"request_id": req.request_id, "unit_no": "U-OK-1", "volume": 99},
        )
        assert r.json()["code"] == 400
        assert "超出申请量" in r.json()["msg"]
        assert db_session.query(BloodIssue).count() == 0

    async def test_issue_rejects_duplicate_unit_no(self, async_client, seed_data, auth_headers, db_session):
        """同一血袋不得重复发放。"""
        req = _make_request(db_session, seed_data["patient2"].patient_id, "O", volume=10)
        db_session.add(BloodCrossMatch(request_id=req.request_id, donor_blood_type="O", result="相合", pass_flag=1, operator_id=1, match_time=datetime.datetime.now()))
        db_session.commit()
        headers = auth_headers(seed_data["nurse_user"].username)
        r1 = await async_client.post("/api/blood/issue", headers=headers, json={"request_id": req.request_id, "unit_no": "DUP-BAG", "volume": 2})
        assert r1.json()["code"] == 200
        # 第二次发（同一血袋号）
        db_session.expire_all()
        req2 = db_session.query(BloodRequest).filter(BloodRequest.request_id == req.request_id).first()
        req2.status = 1
        db_session.commit()
        r2 = await async_client.post("/api/blood/issue", headers=headers, json={"request_id": req.request_id, "unit_no": "DUP-BAG", "volume": 2})
        assert r2.json()["code"] == 400
        assert "重复发放" in r2.json()["msg"]

    async def test_partial_issue_keeps_request_open(self, async_client, seed_data, auth_headers, db_session):
        """分次发血未发满时申请单保持"发血中"，发满才终态化。"""
        req = _make_request(db_session, seed_data["patient"].patient_id, "AB", volume=4)
        db_session.add(BloodCrossMatch(request_id=req.request_id, donor_blood_type="AB", result="相合", pass_flag=1, operator_id=1, match_time=datetime.datetime.now()))
        db_session.commit()
        headers = auth_headers(seed_data["nurse_user"].username)
        r1 = await async_client.post("/api/blood/issue", headers=headers, json={"request_id": req.request_id, "unit_no": "PART-1", "volume": 2})
        assert r1.json()["code"] == 200
        db_session.expire_all()
        first = db_session.query(BloodRequest).filter(BloodRequest.request_id == req.request_id).first()
        assert first.status != 3, "未发满不应终态化"
        # 继续发剩余
        first.status = 1
        db_session.commit()
        r2 = await async_client.post("/api/blood/issue", headers=headers, json={"request_id": req.request_id, "unit_no": "PART-2", "volume": 2})
        assert r2.json()["code"] == 200
        db_session.expire_all()
        done = db_session.query(BloodRequest).filter(BloodRequest.request_id == req.request_id).first()
        assert done.status == 3, "发满后应终态化"
