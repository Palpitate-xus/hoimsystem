"""HIS 补齐模块回归测试：审方规则/医保对照/MDRO/传染病/RCA/HQMS/CSSD/PIVAS/评分/路径。

全部走 API 层验证业务规则，不造预置数据（符合"用户手动录入"设计）。
"""
import datetime

import pytest


@pytest.mark.asyncio
class TestRxReviewRule:
    async def test_rule_crud_and_check_engine(self, async_client, seed_data, auth_headers):
        headers = auth_headers("admin")
        # 药师创建一条配伍禁忌（禁止级）
        r = await async_client.post("/api/rxReviewRule/create", headers=headers, json={
            "rule_type": "interaction", "drug_a": "头孢", "drug_b": "酒精",
            "severity": 3, "message": "头孢与酒精同用可致双硫仑反应",
        })
        assert r.json()["code"] == 200, r.json()
        rule_id = r.json()["data"]["rule_id"]

        # 剂量规则（警告级）
        r = await async_client.post("/api/rxReviewRule/create", headers=headers, json={
            "rule_type": "dose", "drug_a": "地高辛", "max_dose": 0.5,
            "severity": 2, "message": "地高辛每日剂量超限",
        })
        assert r.json()["code"] == 200

        # 预检：同时命中两条（配伍禁止 + 剂量超限）
        r = await async_client.post("/api/rxReviewRule/check", headers=headers, json={
            "items": [
                {"name": "头孢曲松钠注射液", "dosage": 1.0, "frequency": "qd"},
                {"name": "藿香正气水(含酒精)", "dosage": 10, "frequency": "tid"},
                {"name": "地高辛片", "dosage": 0.8, "frequency": "qd"},
            ]
        })
        assert r.json()["code"] == 200
        data = r.json()["data"]
        assert data["blocked"] is True, "命中禁止级规则必须 blocked"
        messages = [f["message"] for f in data["findings"]]
        assert any("双硫仑" in m for m in messages)
        assert any("地高辛" in m for m in messages)
        # 禁止级排在最前
        assert data["findings"][0]["severity"] == 3

        # 停用规则后不再命中
        r = await async_client.post("/api/rxReviewRule/update", headers=headers, json={"rule_id": rule_id, "status": 0})
        assert r.json()["code"] == 200
        r = await async_client.post("/api/rxReviewRule/check", headers=headers, json={
            "items": [{"name": "头孢曲松钠", "dosage": 1, "frequency": "qd"}, {"name": "酒精棉球", "dosage": 1, "frequency": "st"}],
        })
        assert r.json()["data"]["findings"] == []

        # 无效类型拒绝
        r = await async_client.post("/api/rxReviewRule/create", headers=headers, json={"rule_type": "bad", "message": "x"})
        assert r.json()["code"] == 400

    async def test_rule_requires_drug_keywords(self, async_client, seed_data, auth_headers):
        headers = auth_headers("admin")
        r = await async_client.post("/api/rxReviewRule/create", headers=headers, json={
            "rule_type": "interaction", "drug_a": "头孢", "severity": 3, "message": "缺 drug_b",
        })
        assert r.json()["code"] == 400


@pytest.mark.asyncio
class TestInsuranceCatalog:
    async def test_mapping_crud_and_import(self, async_client, seed_data, auth_headers):
        headers = auth_headers("admin")
        r = await async_client.post("/api/insuranceCatalog/create", headers=headers, json={
            "local_item_type": "drug", "local_item_name": "阿莫西林胶囊",
            "insurance_code": "XA01AB001", "insurance_name": "阿莫西林口服常释剂型",
            "insurance_category": "甲类", "self_pay_ratio": 0.1,
        })
        assert r.json()["code"] == 200, r.json()
        mid = r.json()["data"]["mapping_id"]

        # 自付比例越界拒绝
        r = await async_client.post("/api/insuranceCatalog/create", headers=headers, json={
            "local_item_type": "drug", "local_item_name": "测试", "insurance_code": "X1", "insurance_name": "t", "self_pay_ratio": 1.5,
        })
        assert r.json()["code"] == 400

        # 批量导入（重复行跳过）
        r = await async_client.post("/api/insuranceCatalog/import", headers=headers, json={
            "rows": [
                {"本院项目类型": "药品", "本院项目名称": "阿莫西林胶囊", "医保编码": "XA01AB001", "医保名称": "阿莫西林", "类别": "甲类", "自付比例": "0.1"},
                {"本院项目类型": "检验", "本院项目名称": "血常规", "医保编码": "XA02", "医保名称": "血常规", "类别": "甲类", "自付比例": "0"},
            ]
        })
        data = r.json()["data"]
        assert data["imported"] == 1 and data["skipped"] == 1

        # 搜索
        r = await async_client.get("/api/insuranceCatalog/getList", headers=headers, params={"keyword": "血常规"})
        assert len(r.json()["data"]) == 1

        # 删除
        r = await async_client.post("/api/insuranceCatalog/delete", headers=headers, json={"mapping_id": mid})
        assert r.json()["code"] == 200


@pytest.mark.asyncio
class TestMdro:
    async def test_mdro_isolation_lifecycle(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["nurse_user"].username)
        patient = seed_data["patient"]
        r = await async_client.post("/api/mdro/create", headers=headers, json={
            "patient_id": patient.patient_id, "pathogen": "MRSA(耐甲氧西林金黄色葡萄球菌)",
            "specimen": "痰液", "isolation_type": "接触隔离",
            "start_date": datetime.date.today().isoformat(),
        })
        assert r.json()["code"] == 200, r.json()
        mdro_id = r.json()["data"]["mdro_id"]

        # 重复登记拒绝
        r = await async_client.post("/api/mdro/create", headers=headers, json={
            "patient_id": patient.patient_id, "pathogen": "MRSA(耐甲氧西林金黄色葡萄球菌)",
            "start_date": datetime.date.today().isoformat(),
        })
        assert r.json()["code"] == 500

        # 解除（日期早于开始拒绝）
        r = await async_client.post("/api/mdro/release", headers=headers, json={
            "mdro_id": mdro_id, "end_date": "2020-01-01",
        })
        assert r.json()["code"] == 400
        # 正常解除
        r = await async_client.post("/api/mdro/release", headers=headers, json={"mdro_id": mdro_id})
        assert r.json()["code"] == 200
        # 再解除拒绝
        r = await async_client.post("/api/mdro/release", headers=headers, json={"mdro_id": mdro_id})
        assert r.json()["code"] == 500


@pytest.mark.asyncio
class TestNotifiableDisease:
    async def test_report_card_state_machine(self, async_client, seed_data, auth_headers):
        doc_headers = auth_headers("doc01")
        admin_headers = auth_headers("admin")
        patient = seed_data["patient"]
        # 填报：自动判类
        r = await async_client.post("/api/notifiableDisease/create", headers=doc_headers, json={
            "patient_id": patient.patient_id, "disease_name": "肺结核",
            "diagnosis_date": datetime.date.today().isoformat(),
            "case_classification": "实验室确诊病例",
        })
        assert r.json()["code"] == 200
        assert r.json()["data"]["disease_class"] == "乙类"
        report_id = r.json()["data"]["report_id"]

        # 上报必须填卡号
        r = await async_client.post("/api/notifiableDisease/submit", headers=doc_headers, json={"report_id": report_id})
        assert r.json()["code"] == 400
        r = await async_client.post("/api/notifiableDisease/submit", headers=doc_headers, json={"report_id": report_id, "report_card_no": "CARD-001"})
        assert r.json()["code"] == 200

        # 审核（医生不可 → HTTP 403；admin 可）
        r = await async_client.post("/api/notifiableDisease/audit", headers=doc_headers, json={"report_id": report_id})
        assert r.status_code == 403
        r = await async_client.post("/api/notifiableDisease/audit", headers=admin_headers, json={"report_id": report_id})
        assert r.json()["code"] == 200

        # 订正 → 再上报闭环
        r = await async_client.post("/api/notifiableDisease/correct", headers=doc_headers, json={"report_id": report_id, "disease_name": "手足口病"})
        assert r.json()["code"] == 200
        from app.models import NotifiableDiseaseReport
        from tests.conftest import TestingSessionLocal

        s = TestingSessionLocal()
        try:
            row = s.query(NotifiableDiseaseReport).filter(NotifiableDiseaseReport.report_id == report_id).first()
            assert row.disease_class == "丙类", "订正后分类应更新为丙类"
        finally:
            s.close()


@pytest.mark.asyncio
class TestRcaHqms:
    async def test_rca_pdca_flow(self, async_client, seed_data, auth_headers):
        headers = auth_headers("admin")
        from app.models import AdverseEvent
        from tests.conftest import TestingSessionLocal

        s = TestingSessionLocal()
        try:
            ev = AdverseEvent(event_type="跌倒", patient_id=seed_data["patient"].patient_id,
                              description="测试事件", severity=1, reporter_id=seed_data["admin_user"].user_id,
                              report_time=datetime.datetime.now(), status=2)
            s.add(ev)
            s.commit()
            event_id = ev.event_id
        finally:
            s.close()

        r = await async_client.post("/api/rca/create", headers=headers, json={
            "event_id": event_id, "root_cause": "地面湿滑未设警示", "corrective_actions": "增设防滑垫与警示牌",
            "responsible_dept": "后勤科", "due_date": "2026-12-31",
        })
        assert r.json()["code"] == 200, r.json()
        rca_id = r.json()["data"]["rca_id"]

        # 重复创建拒绝
        r = await async_client.post("/api/rca/create", headers=headers, json={"event_id": event_id, "root_cause": "x", "corrective_actions": "y"})
        assert r.json()["code"] == 500

        # 跳级拒绝（P→C）
        r = await async_client.post("/api/rca/advance", headers=headers, json={"rca_id": rca_id, "pdca_cycle": "C"})
        assert r.json()["code"] == 400
        # P→D→C
        for stage in ("D", "C"):
            r = await async_client.post("/api/rca/advance", headers=headers, json={"rca_id": rca_id, "pdca_cycle": stage})
            assert r.json()["code"] == 200
        # C→A 必须效果评价
        r = await async_client.post("/api/rca/advance", headers=headers, json={"rca_id": rca_id, "pdca_cycle": "A"})
        assert r.json()["code"] == 400
        r = await async_client.post("/api/rca/advance", headers=headers, json={"rca_id": rca_id, "pdca_cycle": "A", "effect_evaluation": "三个月无再发"})
        assert r.json()["code"] == 200

    async def test_hqms_create_import_submit(self, async_client, seed_data, auth_headers):
        headers = auth_headers("admin")
        r = await async_client.post("/api/hqms/create", headers=headers, json={
            "period": "2026-08", "indicator_code": "A01", "indicator_name": "住院死亡率",
            "numerator": 3, "denominator": 1000, "unit": "‰",
        })
        assert r.json()["code"] == 200
        # 百分比指标自动换算（分子/分母×100）
        r = await async_client.post("/api/hqms/create", headers=headers, json={
            "period": "2026-08", "indicator_code": "A02", "indicator_name": "再入院率",
            "numerator": 10, "denominator": 200, "unit": "%", "department": "心内科",
        })
        row = [x for x in (await async_client.get("/api/hqms/getList", headers=headers, params={"period": "2026-08"})).json()["data"] if x["indicator_code"] == "A02"][0]
        assert abs(row["indicator_value"] - 5.0) < 0.001

        # 重复指标拒绝（同期间合同室）
        r = await async_client.post("/api/hqms/create", headers=headers, json={
            "period": "2026-08", "indicator_code": "A02", "indicator_name": "再入院率",
            "numerator": 10, "denominator": 200, "unit": "%", "department": "心内科",
        })
        assert r.json()["code"] == 500, f"dup 应被拒绝: {r.json()}"

        # 批量导入 + 上报
        r = await async_client.post("/api/hqms/batchImport", headers=headers, json={
            "rows": [{"统计期": "2026-08", "指标编码": "B01", "指标名称": "平均住院日", "分子": "850", "分母": "100", "单位": "天"}]
        })
        assert r.json()["data"]["imported"] == 1
        r = await async_client.get("/api/hqms/getList", headers=headers, params={"period": "2026-08", "report_status": 0})
        ids = [x["indicator_id"] for x in r.json()["data"]]
        r = await async_client.post("/api/hqms/submit", headers=headers, json={"ids": ids})
        assert r.json()["data"]["updated"] == len(ids)


@pytest.mark.asyncio
class TestCssdPivas:
    async def test_cssd_full_cycle(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post("/api/cssd/create", headers=headers, json={
            "package_name": "清创缝合包", "package_code": f"PKG-{datetime.datetime.now().strftime('%H%M%S%f')}",
            "contents": "弯盘×1 持针器×1 缝线×2",
        })
        assert r.json()["code"] == 200
        iid = r.json()["data"]["instrument_id"]

        # 跳级拒绝（0→2）
        r = await async_client.post("/api/cssd/transition", headers=headers, json={"instrument_id": iid, "status": 2})
        assert r.json()["code"] == 400
        # 0→1→2
        for st in (1, 2):
            r = await async_client.post("/api/cssd/transition", headers=headers, json={"instrument_id": iid, "status": st})
            assert r.json()["code"] == 200
        # 灭菌（BD 试验通过）
        r = await async_client.post("/api/cssd/transition", headers=headers, json={"instrument_id": iid, "status": 3, "bd_test": 1})
        assert r.json()["code"] == 200
        r = await async_client.post("/api/cssd/transition", headers=headers, json={"instrument_id": iid, "status": 4, "biological_monitor": 0})
        assert r.json()["code"] == 400, "生物监测未通过不能置无菌可用"
        r = await async_client.post("/api/cssd/transition", headers=headers, json={
            "instrument_id": iid, "status": 4, "biological_monitor": 1, "expire_date": "2026-12-31"})
        assert r.json()["code"] == 200
        # 发放
        r = await async_client.post("/api/cssd/transition", headers=headers, json={"instrument_id": iid, "status": 5, "current_location": "手术室3间"})
        assert r.json()["code"] == 200

    async def test_pivas_dual_check(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post("/api/pivas/create", headers=headers, json={
            "batch_no": f"B{datetime.datetime.now().strftime('%H%M%S')}", "plan_date": datetime.date.today().isoformat(),
            "label_count": 30, "cytotoxic": True,
        })
        assert r.json()["code"] == 200
        bid = r.json()["data"]["batch_id"]

        # 排药
        r = await async_client.post("/api/pivas/transition", headers=headers, json={"batch_id": bid, "status": 1})
        assert r.json()["code"] == 200
        # 配置（本人）
        r = await async_client.post("/api/pivas/transition", headers=headers, json={"batch_id": bid, "status": 2})
        assert r.json()["code"] == 200
        # 核对（同一人 → 拒绝双人复核）
        r = await async_client.post("/api/pivas/transition", headers=headers, json={"batch_id": bid, "status": 3})
        assert r.json()["code"] == 400
        # 另一人核对
        other = auth_headers(seed_data["pharmacist_user"].username)
        r = await async_client.post("/api/pivas/transition", headers=other, json={"batch_id": bid, "status": 3})
        assert r.json()["code"] == 200
        # 配送 → 签收
        for st in (4, 5):
            r = await async_client.post("/api/pivas/transition", headers=headers, json={"batch_id": bid, "status": st})
            assert r.json()["code"] == 200


@pytest.mark.asyncio
class TestIcuScorePathway:
    async def test_gcs_scoring(self, async_client, seed_data, auth_headers):
        headers = auth_headers(seed_data["nurse_user"].username)
        r = await async_client.post("/api/icuScore/create", headers=headers, json={
            "patient_id": seed_data["patient"].patient_id, "score_type": "gcs", "scene": "icu",
            "detail": {"eye": 3, "verbal": 4, "motor": 5},
        })
        assert r.json()["code"] == 200
        assert r.json()["data"]["total_score"] == 12
        assert "中度" in r.json()["data"]["interpretation"], "GCS 9-12 为中度意识障碍"

        # 越界拒绝
        r = await async_client.post("/api/icuScore/create", headers=headers, json={
            "patient_id": seed_data["patient"].patient_id, "score_type": "gcs",
            "detail": {"eye": 5, "verbal": 4, "motor": 5},
        })
        assert r.json()["code"] == 400

    async def test_aldrete_pacu_discharge_criteria(self, async_client, seed_data, auth_headers):
        headers = auth_headers("doc01")
        r = await async_client.post("/api/icuScore/create", headers=headers, json={
            "patient_id": seed_data["patient"].patient_id, "score_type": "aldrete", "scene": "pacu",
            "detail": {"activity_score": 2, "respiration_score": 2, "circulation_score": 2, "consciousness_score": 2, "color_score": 1},
        })
        assert r.json()["data"]["total_score"] == 9
        assert "达" in r.json()["data"]["interpretation"]

    async def test_pathway_enrollment_flow(self, async_client, seed_data, auth_headers):
        from app.models import ClinicalPathway
        from tests.conftest import TestingSessionLocal

        s = TestingSessionLocal()
        try:
            pw = ClinicalPathway(name="社区获得性肺炎路径", disease_name="肺炎", expected_days=7, status=0,
                                 steps="[]", create_time=datetime.datetime.now())
            s.add(pw)
            s.commit()
            pathway_id = pw.pathway_id
        finally:
            s.close()

        headers = auth_headers("doc01")
        patient = seed_data["patient"]
        r = await async_client.post("/api/pathwayEnrollment/enroll", headers=headers, json={
            "pathway_id": pathway_id, "patient_id": patient.patient_id, "total_items": 5,
        })
        assert r.json()["code"] == 200, r.json()
        eid = r.json()["data"]["enrollment_id"]

        # 重复入组拒绝
        r = await async_client.post("/api/pathwayEnrollment/enroll", headers=headers, json={
            "pathway_id": pathway_id, "patient_id": patient.patient_id,
        })
        assert r.json()["code"] == 500

        # 未完成全部节点不能出径
        r = await async_client.post("/api/pathwayEnrollment/record", headers=headers, json={"enrollment_id": eid, "completed_items": 3})
        assert r.json()["code"] == 200
        r = await async_client.post("/api/pathwayEnrollment/exit", headers=headers, json={"enrollment_id": eid, "status": 3})
        assert r.json()["code"] == 400
        # 变异登记（变异状态仍需完成全部节点才能出径）
        r = await async_client.post("/api/pathwayEnrollment/variation", headers=headers, json={
            "enrollment_id": eid, "variation_reason": "合并脓毒症", "variation_type": "病情变异"})
        assert r.json()["code"] == 200
        r = await async_client.post("/api/pathwayEnrollment/record", headers=headers, json={"enrollment_id": eid, "completed_items": 5})
        assert r.json()["code"] == 200
        r = await async_client.post("/api/pathwayEnrollment/exit", headers=headers, json={"enrollment_id": eid, "status": 3})
        assert r.json()["code"] == 200


@pytest.mark.asyncio
class TestRxEngineIntegration:
    async def test_engine_blocks_prescription_and_dispense(self, async_client, seed_data, auth_headers):
        """审方规则命中禁止级 → 开方被拒；药师审核同样拦截。"""
        admin_headers = auth_headers("admin")
        doctor_headers = auth_headers(seed_data["doctor_user"].username)
        pha_name = seed_data["pharmaceutical"].name

        # 建一条禁止级禁忌规则（以种子药品名做关键词）
        r = await async_client.post("/api/rxReviewRule/create", headers=admin_headers, json={
            "rule_type": "contraindication", "drug_a": pha_name,
            "severity": 3, "message": f"{pha_name} 禁用测试规则",
        })
        assert r.json()["code"] == 200
        rule_id = r.json()["data"]["rule_id"]

        # 开方被拒
        r = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={
            "patient": seed_data["patient2"].patient_id,
            "phas": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 1}],
        })
        assert r.json()["code"] == 500
        assert "审方规则禁止" in r.json()["msg"]

        # 停用规则后可正常开方
        await async_client.post("/api/rxReviewRule/update", headers=admin_headers, json={"rule_id": rule_id, "status": 0})
        r = await async_client.post("/api/prescriptionManagement/create", headers=doctor_headers, json={
            "patient": seed_data["patient2"].patient_id,
            "phas": [{"id": seed_data["pharmaceutical"].pharmaceutical_id, "number": 1}],
        })
        assert r.json()["code"] == 200, r.json()
        pre_id = r.json()["data"]["uuid"]

        # 重新启用规则 → 药师审核拦截
        await async_client.post("/api/rxReviewRule/update", headers=admin_headers, json={"rule_id": rule_id, "status": 1})
        r = await async_client.post("/api/pharmacy/audit", headers=auth_headers(seed_data["pharmacist_user"].username), json={"prescription_id": pre_id})
        assert r.json()["code"] == 500
        assert "审方规则禁止" in r.json()["msg"]

        # 清理：停用规则并取消该处方，避免影响其他测试
        await async_client.post("/api/rxReviewRule/update", headers=admin_headers, json={"rule_id": rule_id, "status": 0})
        await async_client.post("/api/prescriptionManagement/cancel", headers=doctor_headers, json={"uuid": pre_id})
