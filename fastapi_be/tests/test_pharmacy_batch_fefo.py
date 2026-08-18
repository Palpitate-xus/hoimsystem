"""药房批次 FEFO 出库与退药回冲回归测试。

对应药房域审计发现：
1. 发药不扣库存、不写台账（高危）→ 有批次的药品发药必须按 FEFO 扣批次并留台账
2. 退药凭空造库存、不回批次（高危）→ 退药必须回冲批次并写台账
"""
import datetime

import pytest

from app.models import (
    Patient,
    Pharmaceutical,
    PharmaceuticalBatch,
    PharmaceuticalStockLedger,
    PrePha,
    Prescription,
)


def _make_batch(db, pha_id, batch_no, stock, expiry, status=0):
    batch = PharmaceuticalBatch(
        pharmaceutical_id=pha_id,
        batch_no=batch_no,
        expiry_date=expiry,
        stock=stock,
        status=status,
        create_time=datetime.datetime.now(),
        update_time=datetime.datetime.now(),
    )
    db.add(batch)
    db.flush()
    return batch


@pytest.mark.asyncio
class TestFefoDispense:
    async def test_dispense_deducts_earliest_batch_and_writes_ledger(self, async_client, seed_data, auth_headers, db_session):
        """两个批次时必须先扣近效期（FEFO），并写出库台账。"""
        pha = Pharmaceutical(name="FEFO测试药", price=10, stock=200, status=0)
        db_session.add(pha)
        db_session.flush()
        near = _make_batch(db_session, pha.pharmaceutical_id, "NEAR", 10, datetime.date(2026, 12, 31))
        far = _make_batch(db_session, pha.pharmaceutical_id, "FAR", 100, datetime.date(2027, 12, 31))
        patient = Patient(name="批次患者", identity="110101199001018888", sex=1)
        db_session.add(patient)
        db_session.flush()
        doctor = seed_data["doctor"]
        pre = Prescription(patient_id=patient.patient_id, doctor_id=doctor.doctor_id, status=1, create_time=datetime.datetime.now())
        db_session.add(pre)
        db_session.flush()
        db_session.add(PrePha(prescription_id=str(pre.prescription_id), pharmaceutical_id=pha.pharmaceutical_id, number=6))
        db_session.commit()

        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pharmacy/dispense", headers=headers, json={"prescription_id": str(pre.prescription_id)})
        assert r.json()["code"] == 200, r.json()

        db_session.expire_all()
        db_session.refresh(near)
        db_session.refresh(far)
        db_session.refresh(pha)
        assert near.stock == 4, "FEFO：应先扣近效期批次"
        assert far.stock == 100, "近效期足够时不扣远效期批次"
        assert int(pha.stock) == 194, "总量库存同步扣减"
        ledger = (
            db_session.query(PharmaceuticalStockLedger)
            .filter(PharmaceuticalStockLedger.reference_id == str(pre.prescription_id), PharmaceuticalStockLedger.transaction_type == "outbound")
            .all()
        )
        assert ledger and sum(e.quantity for e in ledger) == 6, "必须有出库台账"
        assert ledger[0].batch_id == near.batch_id

    async def test_dispense_spills_to_next_batch_when_first_insufficient(self, async_client, seed_data, auth_headers, db_session):
        pha = Pharmaceutical(name="跨批次药", price=10, stock=200, status=0)
        db_session.add(pha)
        db_session.flush()
        near = _make_batch(db_session, pha.pharmaceutical_id, "N2", 2, datetime.date(2026, 12, 31))
        far = _make_batch(db_session, pha.pharmaceutical_id, "F2", 100, datetime.date(2027, 12, 31))
        patient = Patient(name="跨批次患者", identity="110101199001017777", sex=1)
        db_session.add(patient)
        db_session.flush()
        pre = Prescription(patient_id=patient.patient_id, doctor_id=seed_data["doctor"].doctor_id, status=1, create_time=datetime.datetime.now())
        db_session.add(pre)
        db_session.flush()
        db_session.add(PrePha(prescription_id=str(pre.prescription_id), pharmaceutical_id=pha.pharmaceutical_id, number=5))
        db_session.commit()

        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pharmacy/dispense", headers=headers, json={"prescription_id": str(pre.prescription_id)})
        assert r.json()["code"] == 200, r.json()

        db_session.expire_all()
        db_session.refresh(near)
        db_session.refresh(far)
        assert near.stock == 0 and far.stock == 97, "不足部分溢出到下一批次"

    async def test_dispense_rejects_when_batches_insufficient(self, async_client, seed_data, auth_headers, db_session):
        pha = Pharmaceutical(name="缺货药", price=10, stock=1, status=0)
        db_session.add(pha)
        db_session.flush()
        _make_batch(db_session, pha.pharmaceutical_id, "LOW", 1, datetime.date(2026, 12, 31))
        patient = Patient(name="缺货患者", identity="110101199001016666", sex=1)
        db_session.add(patient)
        db_session.flush()
        pre = Prescription(patient_id=patient.patient_id, doctor_id=seed_data["doctor"].doctor_id, status=1, create_time=datetime.datetime.now())
        db_session.add(pre)
        db_session.flush()
        db_session.add(PrePha(prescription_id=str(pre.prescription_id), pharmaceutical_id=pha.pharmaceutical_id, number=3))
        db_session.commit()

        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pharmacy/dispense", headers=headers, json={"prescription_id": str(pre.prescription_id)})
        assert r.json()["code"] == 500
        assert "不足" in r.json()["msg"]
        # 处方状态应保持已审核（事务回滚）
        db_session.expire_all()
        db_session.refresh(pre)
        assert pre.status == 1

    async def test_return_medicine_writes_return_ledger(self, async_client, seed_data, auth_headers, db_session):
        """退药必须回冲批次并写 return 台账（原缺陷：只加总量凭空造库存）。"""
        pha = Pharmaceutical(name="退药批次药", price=10, stock=100, status=0)
        db_session.add(pha)
        db_session.flush()
        _make_batch(db_session, pha.pharmaceutical_id, "RET-B", 50, datetime.date(2027, 6, 30))
        patient = Patient(name="退药患者", identity="110101199001015555", sex=1)
        db_session.add(patient)
        db_session.flush()
        pre = Prescription(patient_id=patient.patient_id, doctor_id=seed_data["doctor"].doctor_id, status=2, create_time=datetime.datetime.now())
        db_session.add(pre)
        db_session.flush()
        db_session.add(PrePha(prescription_id=str(pre.prescription_id), pharmaceutical_id=pha.pharmaceutical_id, number=3))
        db_session.commit()

        headers = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post(
            "/api/pharmacy/return",
            headers=headers,
            json={"prescription_id": str(pre.prescription_id), "pha_id": pha.pharmaceutical_id, "number": 2, "reason": "患者不适"},
        )
        assert r.json()["code"] == 200, r.json()

        ledger = (
            db_session.query(PharmaceuticalStockLedger)
            .filter(PharmaceuticalStockLedger.reference_id == str(pre.prescription_id), PharmaceuticalStockLedger.transaction_type == "return")
            .all()
        )
        assert ledger and ledger[0].quantity == 2, "退药必须写 return 台账"
        batch = db_session.query(PharmaceuticalBatch).filter(PharmaceuticalBatch.batch_no == "RET-B").first()
        db_session.refresh(batch)
        assert batch.stock == 52, "退药回冲到批次（50+2）"
