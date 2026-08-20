# 09 - HIS 补齐模块流程（2026-08-21 第一批交付）

> 11 个新模块全部**零预置数据**：规则/目录/记录由用户手工录入或批量导入。
> 覆盖：审方规则引擎、医保目录对照、CSSD、PIVAS、ICU/PACU 评分、临床路径执行、MDRO 隔离、手卫生、传染病报告卡、RCA、HQMS。

## 1. 审方规则引擎（用药安全底线）

```
药师维护规则(rx_review_rule)
  ├─ 配伍禁忌 interaction: 药A关键词 × 药B关键词
  ├─ 禁忌 contraindication: 单药关键词
  ├─ 剂量 dose: min/max_dose(每次) + max_daily_dose
  ├─ 重复用药 duplicate: 同成分两药
  └─ 过敏关键词 allergy_key: 过敏史匹配
        │ severity: 1提示 / 2警告 / 3禁止, status 0停用/1启用
        ▼
医生开方(doctor.py 处方前置审核第3步)
  └─ check_prescription(db, items, allergy_history)
       ├─ 命中 severity=3 ──❌ 阻断开方「审方规则禁止：…」
       └─ 1/2 级 ──────────✅ 放行（药师审方环节二次把关）
                                ▼
药师审核(pharmacy.py /pharmacy/audit)
  └─ 同引擎再检（基于已存 PrePha 明细）
       ├─ 命中 severity=3 ──❌ 拒绝发药（医生需修改处方）
       └─ 无命中 ────────────✅ status 0→1 → 缴费 → 发药
```

- 规则未配置时引擎零命中 → 存量流程完全不受影响（兼容开关语义）
- 剂量检查按频次换算日剂量：qd=1/bid=2/tid=3/qid=4/q8h=3/q6h=4/q12h=2/qn=1（`app/rx_review_engine.py: freq_per_day`）
- 预检接口 `POST /api/rxReviewRule/check` 供开方界面实时调用

## 2. 医保目录对照

```
收费员维护映射(insurance_catalog_mapping)
  本院项目(drug/consumable/lab/exam/bed/surgery/anesthesia/registration)
    ↔ insurance_code/insurance_name + 甲/乙/丙类 + self_pay_ratio + unit_price_limit
        │
        ├─ 手工新增/编辑（同 type+name 唯一）
        ├─ 模板下载 GET /insuranceCatalog/template（openpyxl xlsx）
        └─ 粘贴批量导入 POST /insuranceCatalog/import（幂等：重复行跳过并计数）
```

## 3. CSSD 消毒供应状态机

```
登记(status=0 待回收)
  0 ──回收──▶ 1 清洗中 ──▶ 2 检查打包 ──▶ 3 灭菌中 ──▶ 4 无菌可用 ──发放──▶ 5 使用中
                                     │            │              │            │
                                     │   ❌ BD试验未过不能进灭菌    │   ❌ 生物监测未过/  ├─回收──▶ 0（闭环）
                                     │            │              │   未填无菌效期不能置4  └─报损──▶ 6(终态)
                                     └─报损────────┴──报损────────┴──报损──▶ 6
```

- 进入 3 时登记 BD 试验结果；进入 4 时强制生物监测通过 + `expire_date`（自动回填灭菌日期）
- 5→0 周转闭环；任何在用状态可报损（6 终态）

## 4. PIVAS 静配批次

```
创建批次(0 待排药, batch_no+plan_date 唯一, cytotoxic/tpn 标记)
  0 ──排药贴签──▶ 1 ──配置(dispenser=当前人)──▶ 2 ──成品核对──▶ 3 ──配送──▶ 4 ──病区签收──▶ 5(终态)
                                                  │
                                  ❌ checker == dispenser 拒绝（双人复核硬约束）
```

## 5. ICU/PACU 专科评分（服务端汇总）

```
录入分项(detail_json) ──服务端 _compute_score──▶ total_score + interpretation 落库
  ├─ APACHE II: 年龄分(0-6)+APS(0-60)+慢性健康(0/2/5) → 0-71 + 死亡风险分级
  ├─ SOFA: 六脏器各 0-4 → 0-24（<6 良好 / <11 损伤 / ≥11 衰竭风险）
  ├─ GCS: 睁眼1-4+语言1-5+运动1-6 → 3-15（≥13 轻度 / ≥9 中度 / <9 重度）
  ├─ Aldrete(PACU): 五项各 0-2 → 0-10（≥9 达转出标准）
  └─ Steward(PACU): 三项各 0-2 → 0-6（≥4 达转出标准）
```

## 6. 临床路径入组执行

```
入组(status=1 在径, 同患者仅一条 1/2 态记录)
  ├─ record: 登记完成节点数(0≤completed≤total)
  ├─ variation: 变异登记(1→2, 四分类: 病情/医方/患方/系统 + 原因必填)
  │     └─ 变异后继续完成节点
  ├─ exit(3 完成出径): ❌ completed < total 拒绝（全部节点完成才可出径）
  └─ exit(4 退出): 必填 exit_reason
```

## 7. MDRO 隔离闭环

```
检验发现耐药菌 → 登记(1 隔离中, 同患者+同菌种不可重复登记, 床头标识 bed_label)
  └─ 解除: end_date ≥ start_date（早于开始日期拒绝）→ status=0 已解除
```

## 8. 手卫生依从性

```
观察员录入: observe_date + department + moment(五时刻) + opportunities(应执行>0) + actions(≤opportunities)
  ──▶ 自动依从率 = actions/opportunities×100%（getList 返回 compliance）
```

## 9. 传染病报告卡状态机（法定报告闭环）

```
医生填报(0 待上报): disease_name ──服务端自动判甲/乙/丙类(法定 40+ 病种词典)──▶ disease_class
  0 ──submit(必填网直卡号)──▶ 1 已上报网直
  1 ──audit(仅 ADMIN)──▶ 2 已审核
  2 ──correct(可订正病种, 重新判类)──▶ 3 订正 ──submit(新卡号)──▶ 1（闭环）
```

## 10. 不良事件 RCA（PDCA 闭环）

```
一事件一 RCA: create(P 阶段, root_cause/corrective_actions 必填, 可选 timeline 时间线还原)
  P ──▶ D ──▶ C ──▶ A
  └─ 只能按序推进（跳级拒绝）
     A 阶段: 必填 effect_evaluation 效果评价, completed_date 默认当天
```

## 11. HQMS 质量指标上报

```
录入(period+code+dept 唯一): numerator/denominator ──自动计算──▶ indicator_value（单位 % 时 ×100）
  ├─ 粘贴批量导入 batchImport（重复行跳过）
  └─ submit(ids 批量): report_status 0 待上报 ──▶ 1 已上报（仅 ADMIN）
```

---

- 代码位置：`fastapi_be/app/routers/{rx_review_rule,insurance_catalog,infection_control,quality_management,ops_extension}.py`、`fastapi_be/app/rx_review_engine.py`
- 测试：`fastapi_be/tests/test_his_modules.py`（13 项：CRUD + 状态机 + 规则阻断 + RBAC）
- 迁移：`alembic/versions/20260821_his_modules.py`（11 张表，head）

## 12. 病案借阅审批流（2026-08-22）

```
医生申请(status=1 待审批, 病案仍在库)
  ├─ 重复申请拒绝；审批中不可封存冲突由状态机保证
  ├─ 病案管理员(admin/director) 批准 → status=2 借阅中 + borrow_status=2 + borrow_time
  └─ 驳回(必填原因) → borrow_status=3, 病案保持已归档
归还 → status=1 已归档 + borrow_status=0 重置（可再次申请）
```

## 13. 科室绩效核算（2026-08-22）

```
录入明细（全部手工）：workload_items[{项目,数量,单价|小计}] + cost_items[{科目,金额}]
  ──服务端求和──▶ total_workload / total_cost
  ──公式──▶ performance_amount = (工作量 − 成本) × coefficient   （负值如实保留=亏损）
状态机：0 草稿(可改) ──submit──▶ 1 已提交(锁定) ──audit approve──▶ 2 已审核发放
                                      └──audit reject──▶ 退回 0 草稿
```

## 14. 病案 ICD 编码工作台（2026-08-23）

```
待编码工作台（首页 status∈{已提交,已归档} 且无诊断编码绑定）
  └─ 编码员绑定：kind=diagnosis/operation
       ├─ ICD 码须在字典内（统一大写匹配；字典由院方维护，无预置）
       ├─ 主诊断标记：同首页同类型唯一（置主前自动清旧主）
       └─ 重复编码绑定拒绝
统计：覆盖率 = 已编码首页/应编码首页；主诊断 TOP10
```

## 15. 围术期抗菌药依从 + 报损批次台账（2026-08-23）

```
依从判定（GET /surgery/antibioticCompliance）：
  手术开始时间 − 给药时间 ∈ [30, 120] 分钟 → 依从
  >120 过早；<30 过晚；未执行不计入

报损审批（inventoryAdjustment/approve，loss 分支）：
  总量扣减（原逻辑）
    └─ 有启用批次 → FEFO 逐批扣减 + 每批写台账（adjustment）
       └─ 批次合计 < 报损量 → 拒绝（防批次串账）
```
