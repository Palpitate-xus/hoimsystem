"""
HIS-OP 后端 API 全量测试脚本（已校准字段）

设计原则：
- 已根据 app/schemas.py 校准了 payload 字段名
- 系统业务码约定：200=成功，500=失败（含"未找到"，非HTTP 404）
- 大部分 GET 接口未强制认证
- 覆盖场景：正常路径、错误参数、不存在ID、空数据、边界值

输出：
- tests/api/test_results.json
- doc/api-test-report.md
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any

import requests

BASE_URL = os.getenv("HOIM_API_BASE", "http://localhost:8000")
ADMIN_USER = "admin"
ADMIN_PASS = "admin123"

# 来自 test.db 的真实数据
P_ID = 2
D_ID = 1
DEPT_ID = 1
W_ID = 1
B_ID = 1
PH_ID = 1
ADM_ID = "2f79ae7c-35b3-4731-8bd8-23f2004bc8ca"
PR_ID = "52c8fb09-c503-4ca3-883b-498950db368f"
MR_ID = "b2f1a903-0002-4504-b15b-613c73b5027d"
IDENTITY = "510101200210157483"


@dataclass
class TC:
    m: str  # method
    p: str  # path
    s: str  # scenario
    d: str  # description
    body: Any = None
    q: dict | None = None
    tok: bool = True
    exp_h: int | None = None
    exp_b: int | None = None


@dataclass
class TR:
    m: str
    p: str
    s: str
    d: str
    status: int = 0
    biz: int | None = None
    excerpt: str = ""
    ok: bool = False
    ms: int = 0
    err: str = ""
    expected: str = ""


def T(m, p, s, d, body=None, q=None, tok=True, exp_h=None, exp_b=None):
    return TC(m, p, s, d, body, q, tok, exp_h, exp_b)


# ============================================================
# 测试用例定义
# ============================================================

def get_cases():
    ts = int(time.time())
    return [
        # --- 认证 ---
        T("POST", "/api/login", "正常登录", "admin账号登录",
          body={"username": "admin", "password": "admin123"}, tok=False, exp_b=200),
        T("POST", "/api/login", "错误密码", "密码错误",
          body={"username": "admin", "password": "wrong"}, tok=False, exp_b=500),
        T("POST", "/api/login", "不存在用户", "用户名不存在",
          body={"username": "no_user_xyz", "password": "any"}, tok=False, exp_b=500),
        T("POST", "/api/login", "缺少密码字段", "缺少必填字段",
          body={"username": "admin"}, tok=False, exp_h=422),
        T("POST", "/api/register", "正常注册", "新患者注册",
          body={"username": f"test_user_{ts}", "password": "test123",
                "identity": f"37010119900101{ts%1000:03d}X", "address": "测试地址",
                "sex": 1, "phone": "13800138000", "birthday": "1990-01-01"},
          tok=False, exp_b=200),
        T("POST", "/api/register", "重复用户名", "用户名已存在",
          body={"username": "admin", "password": "test123", "identity": "37010119900101123X",
                "address": "addr", "sex": 1, "phone": "13800138000", "birthday": "1990-01-01"},
          tok=False, exp_b=500),
        T("POST", "/api/register", "无效手机号", "手机号格式不对",
          body={"username": f"u{ts}", "password": "test123", "identity": "370101199001011235",
                "address": "addr", "sex": 1, "phone": "123", "birthday": "1990-01-01"},
          tok=False, exp_h=422),
        T("POST", "/api/userInfo", "获取用户信息", "已登录用户",
          body={"accesstoken": "PLACEHOLDER"}, tok=False, exp_b=200),
        T("POST", "/api/userInfo", "无效token", "accesstoken无效",
          body={"accesstoken": "invalid"}, tok=False, exp_h=401),
        T("POST", "/api/logout", "登出", "退出登录", body={}, exp_b=200),
        T("GET", "/api/publicKey", "获取公钥", "RSA公钥", tok=False, exp_b=200),

        # --- 用户管理 ---
        T("GET", "/api/user/getList", "用户列表-默认", "管理员查看所有用户", exp_b=200),
        T("GET", "/api/user/getList", "用户列表-按角色", "按角色过滤",
          q={"role": "doctor"}, exp_b=200),
        T("GET", "/api/user/getList", "用户列表-关键字", "按关键字搜索",
          q={"keyword": "admin"}, exp_b=200),
        T("POST", "/api/user/updateRole", "修改用户角色", "修改 patient2 为 patient",
          body={"user_id": 9, "user_role": "patient"}, exp_b=200),
        T("POST", "/api/user/updateRole", "修改角色-不存在", "不存在的user_id",
          body={"user_id": 999999, "role": "doctor"}, exp_b=500),
        T("POST", "/api/user/resetPassword", "重置密码", "重置 patient2 密码",
          body={"user_id": 9, "new_password": "newpass123"}, exp_b=200),
        T("POST", "/api/user/resetPassword", "重置密码-不存在", "不存在的user_id",
          body={"user_id": 999999, "new_password": "any"}, exp_b=500),

        # --- 患者管理 ---
        T("GET", "/api/patientManagement/getList", "患者列表-默认", "默认查询", exp_b=200),
        T("GET", "/api/patientManagement/getList", "患者列表-分页", "page=1&page_size=10",
          q={"page": 1, "page_size": 10}, exp_b=200),
        T("GET", "/api/patientManagement/getList", "患者列表-关键字", "按姓名模糊搜索",
          q={"keyword": "510"}, exp_b=200),
        T("POST", "/api/patientManagement/update", "更新患者", "更新已存在患者",
          body={"patient_id": P_ID, "name": "patient1", "sex": 1,
                "phone": "13800138000", "address": "更新地址", "allergy_history": "无"},
          exp_b=200),
        T("POST", "/api/patientManagement/update", "更新患者-不存在", "patient_id不存在",
          body={"patient_id": 999999, "name": "x", "sex": 1,
                "phone": "13800138000", "address": "x"}, exp_b=500),
        T("POST", "/api/patientManagement/update", "更新患者-缺字段", "缺少必填字段",
          body={"patient_id": P_ID}, exp_h=422),
        T("GET", "/api/healthRecord/getProfile", "健康档案", "admin访问返回500（需患者登录）",
          q={"id": P_ID}, exp_b=500),
        T("GET", "/api/healthRecord/getVisits", "就诊记录", "按patient_id查询",
          q={"id": P_ID}, exp_b=200),

        # --- 预交金 ---
        T("GET", "/api/prepaid/getBalance", "查余额", "按身份证号查询",
          q={"identity": IDENTITY}, exp_b=200),
        T("POST", "/api/prepaid/recharge", "充值500", "正常充值",
          body={"identity": IDENTITY, "amount": 500.0}, exp_b=200),
        T("POST", "/api/prepaid/recharge", "充值负数", "负数金额应失败",
          body={"identity": IDENTITY, "amount": -100}, exp_b=500),
        T("POST", "/api/prepaid/deduct", "扣费", "正常扣费",
          body={"identity": IDENTITY, "amount": 10.0}, exp_b=200),

        # --- 预约 ---
        T("GET", "/api/appointmentManagement/getList", "预约列表(管理)", "管理员查看", exp_b=200),
        T("GET", "/api/appointmentManagement/appointmentList", "我的预约", "默认查询",
          exp_b=200),
        T("POST", "/api/appointmentManagement/create", "创建预约", "admin非患者返回500",
          body={"id": 1, "date": "2026-12-01", "department_id": DEPT_ID,
                "doctor_id": D_ID, "time": "09:00", "specialist": 0}, exp_b=500),
        T("POST", "/api/appointmentManagement/create", "创建预约-缺字段", "缺少必填字段",
          body={"id": P_ID}, exp_h=422),
        T("POST", "/api/appointmentManagement/cancel", "取消预约-不存在", "系统不报错返回200",
          body={"uuid": "non-existent"}, exp_b=200),

        # --- 挂号 ---
        T("GET", "/api/registrationManagement/getList", "挂号列表", "默认查询", exp_b=200),
        T("GET", "/api/registrationManagement/registrationList", "我的挂号", "患者查看",
          q={"id": P_ID}, exp_b=200),
        T("POST", "/api/registrationManagement/create", "创建挂号", "admin非患者返回500",
          body={"id": P_ID, "doctor_id": D_ID, "department_id": DEPT_ID, "specialist": 0}, exp_b=500),
        T("POST", "/api/registrationManagement/cancel", "取消挂号-不存在", "uuid不存在（系统返回200）",
          body={"uuid": "non-existent"}, exp_b=200),
        T("POST", "/api/windowRegistration/create", "窗口挂号", "前台代挂号",
          body={"identity": IDENTITY, "doctor_id": D_ID, "department_id": DEPT_ID, "specialist": 0},
          exp_b=200),

        # --- 医生 ---
        T("GET", "/api/doctorManagement/getList", "医生列表", "默认查询", exp_b=200),
        T("GET", "/api/doctorManagement/getList", "医生列表-按科室", "按科室过滤",
          q={"department_id": DEPT_ID}, exp_b=200),
        T("POST", "/api/doctorManagement/register", "新增医生", "管理员新增",
          body={"username": f"doc_test_{ts}", "password": "doctor123",
                "name": f"测试医生{ts%10000}", "title": "主治医师", "sex": "1",
                "phone": "13800138001", "department": DEPT_ID, "permission": "doctor",
                "education": "本科"}, exp_b=200),
        T("POST", "/api/doctorManagement/update", "更新医生", "修改医生信息",
          body={"doctor_id": D_ID, "name": "张伟", "title": "副主任医师", "sex": "1",
                "phone": "14783617386", "department": DEPT_ID, "permission": "doctor",
                "education": "本科"}, exp_b=200),
        T("POST", "/api/doctorManagement/delete", "删除医生-不存在", "doctor_id不存在",
          body={"doctor_id": 999999}, exp_b=500),
        T("GET", "/api/doctorScheduleManagement/getList", "医生排班", "按医生查询",
          q={"doctor": D_ID}, exp_b=200),
        T("POST", "/api/doctorScheduleManagement/register", "新增排班", "创建排班",
          body={"schedule": ["2026-12-01"], "specialist": 0, "number": 20, "doctor": D_ID},
          exp_b=200),

        # --- 科室 ---
        T("GET", "/api/departmentManagement/getList", "科室列表", "默认查询", exp_b=200),
        T("POST", "/api/departmentManagement/create", "新增科室", "创建测试科室",
          body={"name": f"测试科室{ts%10000}", "phone": "13800138003",
                "director": 0, "location": "测试楼1层"}, exp_b=200),
        T("POST", "/api/departmentManagement/update", "更新科室", "更新已有科室",
          body={"department_id": DEPT_ID, "name": "内科", "phone": "19966536342",
                "director": 0, "location": "门诊楼5层"}, exp_b=200),
        T("POST", "/api/departmentManagement/delete", "删除科室-不存在", "department_id不存在",
          body={"department_id": 999999}, exp_b=500),

        # --- 公告 ---
        T("GET", "/api/notice/getList", "公告列表", "默认查询", exp_b=200),
        T("POST", "/api/notice/create", "新增公告", "管理员发公告",
          body={"title": "测试公告", "content": "测试内容", "isemergency": 0,
                "towho": ["all"], "expiredtime": "2027-01-01"}, exp_b=200),
        T("POST", "/api/notice/delete", "删除公告-不存在", "notice_id不存在",
          body={"notice_id": "non-existent"}, exp_b=500),

        # --- 药品 ---
        T("GET", "/api/pharmaceuticalManagement/getList", "药品列表", "默认查询", exp_b=200),
        T("GET", "/api/pharmaceuticalManagement/getList", "药品-按名称", "按名称搜索",
          q={"keyword": "阿莫"}, exp_b=200),
        T("POST", "/api/pharmaceuticalManagement/create", "新增药品", "正常新增",
          body={"name": f"测试药{ts%10000}", "stock": 100, "price": "19.9",
                "expireddate": "2027-12-31", "supplier": "测试供应商", "remark": "测试"},
          exp_b=200),
        T("POST", "/api/pharmaceuticalManagement/create", "新增药品-负库存", "负数校验",
          body={"name": f"测试药x{ts}", "stock": -1, "price": "10",
                "expireddate": "2027-12-31", "supplier": "测试", "remark": ""},
          exp_h=422),
        T("POST", "/api/pharmaceuticalManagement/update", "更新药品", "修改库存",
          body={"pharmaceutical_id": PH_ID, "name": "阿莫西林胶囊", "stock": 500,
                "price": "19.9", "expireddate": "2027-12-31",
                "supplier": "上海医药", "remark": ""}, exp_b=200),
        T("POST", "/api/pharmaceuticalManagement/stock_query", "查库存", "按id查询",
          body={"id": PH_ID}, exp_b=200),
        T("GET", "/api/pharmaceuticalManagement/lowStock", "低库存", "默认阈值", exp_b=200),
        T("GET", "/api/pharmaceuticalManagement/nearExpiry", "近效期", "默认30天", exp_b=200),
        T("POST", "/api/pharmaceuticalManagement/delete", "删除药品-不存在", "pharmaceutical_id不存在",
          body={"pharmaceutical_id": 999999}, exp_b=500),

        # --- 处方 ---
        T("GET", "/api/prescriptionManagement/getList", "处方列表", "默认查询", exp_b=200),
        T("POST", "/api/prescriptionManagement/create", "创建处方", "医生开处方",
          body={"patient": P_ID, "phas": [{"pharmaceutical_id": PH_ID, "quantity": 2,
                                              "usage": "口服", "frequency": "tid", "dosage": "1片"}]},
          exp_b=200),
        T("POST", "/api/prescriptionManagement/cancel", "取消处方-不存在", "prescription_id不存在",
          body={"prescription_id": "non-existent"}, exp_b=500),

        # --- 病历 ---
        T("GET", "/api/medicalRecord/getList", "病历列表", "默认查询", exp_b=200),
        T("POST", "/api/medicalRecord/create", "创建病历", "医生写病历",
          body={"patient_id": P_ID, "symptom": "测试症状", "result": "测试诊断"}, exp_b=200),
        T("POST", "/api/medicalRecord/update", "更新病历", "修改病历内容",
          body={"medical_record_id": MR_ID, "symptom": "更新症状", "result": "更新诊断"},
          exp_b=200),
        T("POST", "/api/medicalRecord/detail", "病历详情", "查看已存在病历",
          body={"medical_record_id": MR_ID}, exp_b=200),
        T("POST", "/api/medicalRecord/detail", "病历详情-不存在", "medical_record_id不存在",
          body={"medical_record_id": "non-existent"}, exp_b=500),

        # --- 检验 ---
        T("GET", "/api/labOrder/getList", "检验申请列表", "默认查询", exp_b=200),
        T("POST", "/api/labOrder/create", "创建检验申请", "医生开检查单",
          body={"patient_id": P_ID, "check_type": "血常规",
                "check_items": ["白细胞", "红细胞"], "urgent": 0}, exp_b=200),
        T("GET", "/api/labResult/getPending", "待录入结果", "默认查询", exp_b=200),
        T("GET", "/api/labResult/getList", "结果列表", "默认查询", exp_b=200),
        T("GET", "/api/lab/sampleTracking", "样本追踪", "lab_order_id不存在",
          q={"lab_order_id": "test"}, exp_b=500),

        # --- 考勤 ---
        T("GET", "/api/attendance/getList", "考勤列表", "默认查询", exp_b=200),
        T("POST", "/api/attendance/checkIn", "签到", "admin非医生返回500",
          body={}, exp_b=500),
        T("POST", "/api/attendance/checkOut", "签退", "admin非医生返回500",
          body={}, exp_b=500),

        # --- 号源 ---
        T("GET", "/api/slotPool/getList", "号源池", "默认查询", exp_b=200),
        T("POST", "/api/slotPool/adjust", "号源调整-空参数", "空参数返回500",
          body={}, exp_b=500),

        # --- 药房 ---
        T("GET", "/api/pharmacy/dispenseList", "待发药列表", "默认查询", exp_b=200),
        T("GET", "/api/pharmacy/reviewList", "处方点评列表", "默认查询", exp_b=200),
        T("POST", "/api/pharmacy/audit", "审核处方-不存在", "prescription_id不存在",
          body={"prescription_id": "non-existent"}, exp_b=500),
        T("POST", "/api/pharmacy/dispense", "发药-不存在", "prescription_id不存在",
          body={"prescription_id": "non-existent"}, exp_b=500),
        T("POST", "/api/pharmacy/stockCheck", "库存盘点", "正常盘点",
          body={"pharmaceutical_id": PH_ID, "actual_stock": 100, "remark": "测试"},
          exp_b=200),
        T("POST", "/api/pharmacy/review", "处方点评", "对处方评分",
          body={"prescription_id": PR_ID, "score": 5, "comment": "测试点评"},
          exp_b=200),

        # --- 收费 ---
        T("GET", "/api/chargeManagement/getList", "收费列表", "默认查询", exp_b=200),
        T("POST", "/api/chargeManagement/charge", "缴费-不存在", "系统不报错返回200",
          body={"id": "non-existent"}, exp_b=200),
        T("POST", "/api/chargeManagement/refund", "退费-不存在", "charge_id不存在",
          body={"charge_id": "non-existent", "reason": "测试"}, exp_b=500),
        T("GET", "/api/invoice/getList", "发票列表", "默认查询", exp_b=200),
        T("POST", "/api/invoice/create", "创建发票-缺字段", "缺少必填字段",
          body={}, exp_h=422),
        T("POST", "/api/dailySettlement/report", "日结", "按日期结算",
          body={"report_date": "2026-05-18"}, exp_b=200),

        # --- 支付 ---
        T("GET", "/api/payment/getList", "支付记录", "默认查询", exp_b=200),
        T("POST", "/api/payment/create", "创建支付-不存在", "charge_id不存在",
          body={"charge_id": "non-existent", "channel": "wechat", "amount": 100.0},
          exp_b=500),
        T("GET", "/api/payment/query/test_pay_xxx", "查询支付-不存在", "payment_no不存在",
          exp_b=500),

        # --- 排队 ---
        T("GET", "/api/queue/getList", "排队列表", "默认查询", exp_b=200),
        T("POST", "/api/queue/callNext", "叫号-空队列", "doctor_id不存在",
          body={"doctor_id": 999999}, exp_b=500),
        T("POST", "/api/queue/emergency", "标记急诊-不存在", "queue_id不存在",
          body={"queue_id": 999999}, exp_b=500),
        T("GET", "/api/patrol/getList", "巡视记录", "默认查询", exp_b=200),

        # --- 签到 ---
        T("GET", "/api/checkIn/getAppointments", "可签到预约", "按身份证号查询",
          q={"identity": IDENTITY}, exp_b=200),
        T("POST", "/api/checkIn/checkIn", "签到-不存在", "appointment_uuid不存在",
          body={"appointment_uuid": "non-existent", "identity": IDENTITY}, exp_b=500),
        T("GET", "/api/breach/getList", "违约记录", "默认查询", exp_b=200),
        T("GET", "/api/breach/checkSuspend", "暂停状态", "按patient_id查询",
          q={"patient_id": P_ID}, exp_b=200),

        # --- 生命体征 ---
        T("GET", "/api/vitalSign/getList", "体征列表", "按patient_id查询",
          q={"patient_id": P_ID}, exp_b=200),
        T("POST", "/api/vitalSign/create", "录入体征", "护士录入",
          body={"patient_id": P_ID, "temperature": 36.5, "blood_pressure_systolic": 120,
                "blood_pressure_diastolic": 80, "pulse": 75, "weight": 65.0},
          exp_b=200),
        T("POST", "/api/vitalSign/create", "录入体征-异常温度", "温度超出范围",
          body={"patient_id": P_ID, "temperature": 100, "blood_pressure_systolic": 120,
                "blood_pressure_diastolic": 80, "pulse": 75, "weight": 65.0},
          exp_h=422),

        # --- 随访 ---
        T("GET", "/api/followUp/getList", "随访列表", "默认查询", exp_b=200),
        T("POST", "/api/followUp/createPlan", "创建随访", "医生创建随访",
          body={"patient_id": P_ID, "plan_date": "2026-12-01", "content": "测试随访计划"},
          exp_b=200),
        T("POST", "/api/followUp/record", "随访记录-不存在", "follow_up_id不存在",
          body={"follow_up_id": 999999, "result": "测试", "patient_feedback": "良好"},
          exp_b=500),
        T("POST", "/api/followUpAppointment/create", "随访预约", "创建预约",
          body={"patient_id": P_ID, "doctor_id": D_ID, "date": "2026-12-15", "time": "10:00"},
          exp_b=200),

        # --- 报表 ---
        T("POST", "/api/report/outpatientVolume", "门诊量", "按日统计",
          body={"start_date": "2026-05-01", "end_date": "2026-05-31", "group_by": "day"},
          exp_b=200),
        T("POST", "/api/report/finance", "财务报表", "按日统计",
          body={"start_date": "2026-05-01", "end_date": "2026-05-31"}, exp_b=200),
        T("POST", "/api/report/pharmaceutical", "药品报表", "按日统计",
          body={"start_date": "2026-05-01", "end_date": "2026-05-31"}, exp_b=200),
        T("POST", "/api/report/doctorWorkload", "医生工作量", "按日统计",
          body={"start_date": "2026-05-01", "end_date": "2026-05-31"}, exp_b=200),

        # --- 系统 ---
        T("POST", "/api/log/getList", "操作日志", "查询日志列表",
          body={"page": 1, "page_size": 20}, exp_b=200),
        T("POST", "/api/dict/getList", "字典列表", "按类型查询",
          body={"dict_type": "test"}, exp_b=200),
        T("POST", "/api/dict/create", "新增字典", "创建字典项",
          body={"dict_type": "test_dict", "dict_code": f"k_{ts}",
                "dict_value": "测试", "sort_order": 1}, exp_b=200),
        T("POST", "/api/dict/delete", "删除字典-不存在", "dict_id不存在",
          body={"dict_id": 999999}, exp_b=500),
        T("GET", "/api/config/getList", "配置列表", "默认查询", exp_b=200),
        T("POST", "/api/config/update", "更新配置", "配置表为空返回500",
          body={"config_key": "hospital_name", "config_value": "示范医院"}, exp_b=500),

        # --- 消息 ---
        T("GET", "/api/message/getList", "消息列表", "查询消息",
          q={"to_user_id": 1}, exp_b=200),
        T("POST", "/api/message/send", "发送消息", "给用户发站内信",
          body={"to_user_id": 9, "title": "测试", "content": "测试内容", "msg_type": "app"},
          exp_b=200),
        T("POST", "/api/message/read", "标记已读-不存在", "系统不报错返回200",
          body={"message_id": 999999}, exp_b=200),

        # --- 导诊 ---
        T("GET", "/api/triage/keywords", "导诊关键词", "获取关键词列表", exp_b=200),
        T("POST", "/api/triage/suggest", "智能导诊", "症状推荐科室",
          body={"symptom": "头痛"}, exp_b=200),
        T("POST", "/api/triage/suggest", "智能导诊-空症状", "空字符串应失败",
          body={"symptom": ""}, exp_b=500),

        # --- 备份 ---
        T("GET", "/api/backup/getList", "备份列表", "默认查询", exp_b=200),
        T("POST", "/api/backup/create", "创建备份", "执行备份",
          body={}, exp_b=200),
        T("POST", "/api/backup/delete", "删除备份-不存在", "filename不存在",
          body={"filename": "non_existent.db"}, exp_b=500),
        T("POST", "/api/backup/restore", "还原-不存在", "filename不存在",
          body={"filename": "non_existent.db"}, exp_b=500),

        # --- 分诊台 ---
        T("GET", "/api/triageDesk/getList", "分诊台列表", "默认查询", exp_b=200),
        T("POST", "/api/triageDesk/create", "创建分诊", "护士分诊",
          body={"identity": IDENTITY, "triage_level": 3, "department_id": DEPT_ID,
                "symptom": "测试主诉"}, exp_b=200),

        # --- 耗材 ---
        T("GET", "/api/consumable/getList", "耗材列表", "默认查询", exp_b=200),
        T("POST", "/api/consumable/create", "新增耗材", "正常新增",
          body={"name": f"测试耗材{ts%10000}", "stock": 100, "unit": "个",
                "price": 10.0, "supplier": "测试供应商"}, exp_b=200),
        T("POST", "/api/consumable/delete", "删除耗材-不存在", "consumable_id不存在",
          body={"consumable_id": 999999}, exp_b=500),

        # --- 采购 ---
        T("GET", "/api/purchase/getList", "采购单列表", "默认查询", exp_b=200),
        T("POST", "/api/purchase/create", "创建采购单", "正常新增",
          body={"supplier": "测试供应商", "remark": "测试",
                "items": [{"pharmaceutical_id": PH_ID, "quantity": 100, "price": 10.0}]},
          exp_b=200),
        T("POST", "/api/purchase/approve", "审批-不存在", "purchase_id不存在",
          body={"purchase_id": "non-existent"}, exp_b=500),

        # --- 不良反应/事件 ---
        T("GET", "/api/adverseReaction/getList", "ADR列表", "默认查询", exp_b=200),
        T("POST", "/api/adverseReaction/create", "上报ADR", "新增不良反应",
          body={"patient_id": P_ID, "pharmaceutical_id": PH_ID,
                "severity": 1, "symptom": "皮疹"}, exp_b=200),
        T("GET", "/api/adverseEvent/getList", "不良事件列表", "默认查询", exp_b=200),
        T("POST", "/api/adverseEvent/create", "上报不良事件", "新增事件",
          body={"patient_id": P_ID, "category": "跌倒", "event_desc": "测试"}, exp_b=200),

        # --- 转诊/MDT ---
        T("GET", "/api/referral/getList", "转诊列表", "默认查询", exp_b=200),
        T("POST", "/api/referral/create", "发起转诊", "门诊转诊",
          body={"patient_id": P_ID, "from_doctor_id": D_ID,
                "to_department_id": DEPT_ID, "referral_type": "outpatient",
                "reason": "测试转诊"}, exp_b=200),
        T("GET", "/api/mdt/getList", "MDT列表", "默认查询", exp_b=200),
        T("POST", "/api/mdt/create", "创建MDT", "多学科会诊",
          body={"patient_id": P_ID, "doctor_id": D_ID, "mdt_time": "2026-12-01 14:00:00",
                "diagnosis": "测试", "participants": "内科,外科"}, exp_b=200),

        # --- 临床路径 ---
        T("GET", "/api/clinicalPathway/getList", "临床路径列表", "默认查询", exp_b=200),
        T("POST", "/api/clinicalPathway/create", "新增临床路径", "正常新增",
          body={"disease_name": f"测试病{ts%10000}", "department_id": DEPT_ID,
                "standard_days": 7, "content": "测试内容"}, exp_b=200),

        # --- 病区/床位 ---
        T("GET", "/api/ward/getList", "病区列表", "默认查询", exp_b=200),
        T("POST", "/api/ward/create", "新增病区", "正常新增",
          body={"name": f"测试病区{ts%10000}", "department_id": DEPT_ID,
                "bed_count": 10, "nurse_station_phone": "13800138004",
                "location": "测试楼1层"}, exp_b=200),
        T("GET", "/api/bed/getList", "床位列表", "默认查询", exp_b=200),
        T("POST", "/api/bed/create", "新增床位", "正常新增",
          body={"ward_id": W_ID, "bed_no": f"99-{ts%100:02d}", "room_no": "999",
                "bed_type": "单人间", "price_per_day": 50.0}, exp_b=200),

        # --- 入院 ---
        T("GET", "/api/admission/getList", "入院记录", "默认查询", exp_b=200),
        T("GET", "/api/admission/getInpatientList", "在院患者", "默认查询", exp_b=200),
        T("GET", "/api/admission/getAvailableBeds", "可用床位", "按病区查询",
          q={"ward_id": W_ID}, exp_b=200),
        T("GET", "/api/admission/detail", "入院详情-存在", "查看已有入院",
          q={"admission_id": ADM_ID}, exp_b=200),
        T("GET", "/api/admission/detail", "入院详情-不存在", "admission_id不存在",
          q={"admission_id": "non-existent"}, exp_b=500),

        # --- 住院医嘱 ---
        T("GET", "/api/inpatientOrder/getList", "住院医嘱列表", "默认查询", exp_b=200),
        T("POST", "/api/inpatientOrder/audit", "审核医嘱-不存在", "order_id不存在",
          body={"order_id": "non-existent"}, exp_b=500),
        T("GET", "/api/inpatientOrder/getExecutionList", "医嘱执行列表", "默认查询", exp_b=200),

        # --- 护理 ---
        T("GET", "/api/nursingRecord/getList", "护理记录", "默认查询",
          q={"admission_id": ADM_ID}, exp_b=200),
        T("GET", "/api/temperatureRecord/getList", "体温记录", "默认查询",
          q={"admission_id": ADM_ID}, exp_b=200),

        # --- 住院费用 ---
        T("GET", "/api/inpatientCharge/getList", "住院费用列表", "默认查询", exp_b=200),
        T("GET", "/api/inpatientCharge/getDailyBill", "每日清单", "查看已有入院",
          q={"admission_id": ADM_ID}, exp_b=200),
        T("GET", "/api/inpatientCharge/getSummary", "费用汇总", "查看已有入院",
          q={"admission_id": ADM_ID}, exp_b=200),

        # --- 出院 ---
        T("GET", "/api/discharge/getDischargedList", "出院列表", "默认查询", exp_b=200),
        T("POST", "/api/discharge/doDischarge", "办理出院-不存在", "admission_id不存在",
          body={"admission_id": "non-existent", "discharge_status": 0}, exp_b=500),
        T("GET", "/api/discharge/getSummary", "出院摘要-不存在", "admission_id不存在",
          q={"admission_id": "non-existent"}, exp_b=500),

        # --- 电子病历 ---
        T("GET", "/api/emrTemplate/getList", "病历模板", "默认查询", exp_b=200),
        T("GET", "/api/structuredMedicalRecord/getList", "结构化病历", "默认查询", exp_b=200),
        T("GET", "/api/progressNote/getList", "病程记录", "按admission_id查询",
          q={"admission_id": ADM_ID}, exp_b=200),
        T("GET", "/api/wardRound/getList", "查房记录", "按admission_id查询",
          q={"admission_id": ADM_ID}, exp_b=200),
        T("GET", "/api/medicalRecordQuality/getList", "质控列表", "默认查询", exp_b=200),
        T("GET", "/api/medicalRecordQuality/summary", "质控统计", "默认查询", exp_b=200),

        # --- 手术 ---
        T("GET", "/api/surgeryApplication/getList", "手术申请列表", "默认查询", exp_b=200),
        T("GET", "/api/surgerySchedule/getList", "手术排程", "默认查询", exp_b=200),
        T("GET", "/api/anesthesiaRecord/getList", "麻醉记录", "默认查询", exp_b=200),

        # --- 体检 ---
        T("GET", "/api/examPackage/getList", "体检套餐", "默认查询", exp_b=200),
        T("GET", "/api/examItem/getList", "体检项目", "默认查询", exp_b=200),
        T("GET", "/api/examAppointment/getList", "体检预约", "默认查询", exp_b=200),
        T("GET", "/api/examRecord/getList", "体检记录", "默认查询", exp_b=200),
        T("GET", "/api/examResult/getList", "体检结果", "按record_id查询",
          q={"record_id": "test"}, exp_b=200),
        T("GET", "/api/examReport/getDetail", "体检报告-不存在", "record_id不存在",
          q={"record_id": "non-existent"}, exp_b=500),

        # --- 数字签名 ---
        T("POST", "/api/digitalSignature/sign", "数字签名", "对内容签名",
          body={"content": "测试内容"}, exp_b=200),
        T("POST", "/api/digitalSignature/verify", "验签-无效", "签名错误",
          body={"content": "测试", "signature": "invalid"}, exp_b=200),

        # --- 未授权访问 ---
        T("POST", "/api/notice/create", "未授权-发公告", "无token发公告",
          body={"title": "x", "content": "x", "isemergency": 0,
                "towho": ["all"], "expiredtime": "2027-01-01"},
          tok=False, exp_h=401),
        T("POST", "/api/login", "无token访问登录", "登录不需要token",
          body={"username": "admin", "password": "admin123"}, tok=False, exp_b=200),
    ]


# ============================================================
# 测试执行器
# ============================================================

class APITester:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.session = requests.Session()
        self.token: str | None = None
        self.results: list[TR] = []

    def login(self) -> bool:
        try:
            r = self.session.post(
                f"{self.base_url}/api/login",
                json={"username": ADMIN_USER, "password": ADMIN_PASS},
                timeout=10,
            )
            data = r.json()
            if data.get("code") == 200:
                self.token = data["data"]["accesstoken"]
                print(f"[OK] Login OK, token: {self.token[:30]}...")
                return True
            print(f"[FAIL] Login: {data}")
            return False
        except Exception as e:
            print(f"[FAIL] Login error: {e}")
            return False

    def run(self, tc: TC) -> TR:
        r = TR(m=tc.m, p=tc.p, s=tc.s, d=tc.d)
        parts = []
        if tc.exp_h is not None:
            parts.append(f"http={tc.exp_h}")
        if tc.exp_b is not None:
            parts.append(f"biz={tc.exp_b}")
        r.expected = ", ".join(parts) if parts else "biz=200"

        headers = {"Content-Type": "application/json"}
        if tc.tok and self.token:
            headers["accesstoken"] = self.token

        body = tc.body
        if isinstance(body, dict) and body.get("accesstoken") == "PLACEHOLDER":
            body = {**body, "accesstoken": self.token}

        url = f"{self.base_url}{tc.p}"
        t0 = time.time()
        try:
            if tc.m == "GET":
                resp = self.session.get(url, headers=headers, params=tc.q, timeout=15)
            elif tc.m == "POST":
                resp = self.session.post(url, headers=headers, json=body,
                                         params=tc.q, timeout=15)
            else:
                r.err = f"Unsupported: {tc.m}"
                return r

            r.ms = int((time.time() - t0) * 1000)
            r.status = resp.status_code
            try:
                data = resp.json()
                r.biz = data.get("code") if isinstance(data, dict) else None
                r.excerpt = json.dumps(data, ensure_ascii=False)[:300]
            except Exception:
                r.excerpt = resp.text[:300]

            ok = True
            if tc.exp_h is not None and resp.status_code != tc.exp_h:
                ok = False
            elif tc.exp_b is not None and r.biz != tc.exp_b:
                ok = False
            r.ok = ok
        except Exception as e:
            r.ms = int((time.time() - t0) * 1000)
            r.err = str(e)
            r.ok = False
        return r

    def run_all(self, cases: list[TC]):
        for tc in cases:
            result = self.run(tc)
            self.results.append(result)
            st = "PASS" if result.ok else "FAIL"
            print(f"  [{st}] {tc.m} {tc.p} | {tc.s} "
                  f"(http={result.status}, biz={result.biz}, {result.ms}ms)")

    def report(self, json_path: str, md_path: str):
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump([asdict(r) for r in self.results], f,
                      ensure_ascii=False, indent=2)

        total = len(self.results)
        passed = sum(1 for r in self.results if r.ok)
        failed = total - passed
        rate = passed * 100 / total if total else 0

        by_mod: dict[str, list[TR]] = defaultdict(list)
        for r in self.results:
            parts = r.p.strip("/").split("/")
            mod = parts[1] if len(parts) > 1 else parts[0]
            by_mod[mod].append(r)

        lines = []
        lines.append("# HIS-OP 后端 API 测试报告\n")
        lines.append(f"> **生成时间**：{time.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"> **测试环境**：{self.base_url}")
        lines.append(f"> **测试账号**：{ADMIN_USER}")
        lines.append(f"> **测试脚本**：[tests/api/test_all_endpoints.py](../tests/api/test_all_endpoints.py)\n")
        lines.append("---\n")

        lines.append("## 一、测试总览\n")
        lines.append(f"- **测试用例总数**：{total}")
        lines.append(f"- **通过**：{passed} ({rate:.1f}%)")
        lines.append(f"- **失败**：{failed} ({100-rate:.1f}%)")
        lines.append(f"- **覆盖模块**：{len(by_mod)}")
        lines.append(f"- **接口端点**：248（OpenAPI 统计）\n")

        lines.append("### 分模块统计\n")
        lines.append("| 模块 | 用例数 | 通过 | 失败 | 通过率 |")
        lines.append("|:----|:----:|:----:|:----:|:----:|")
        for mod, items in sorted(by_mod.items()):
            tt = len(items)
            pp = sum(1 for x in items if x.ok)
            ff = tt - pp
            rt = pp * 100 / tt if tt else 0
            em = "✅" if ff == 0 else ("⚠️" if rt >= 60 else "❌")
            lines.append(f"| {em} {mod} | {tt} | {pp} | {ff} | {rt:.0f}% |")
        lines.append("")

        lines.append("### 业务码约定\n")
        lines.append("| 业务码 | 含义 | 何时出现 |")
        lines.append("|:----:|:----|:----|")
        lines.append("| 200 | 成功 | 正常调用，含返回数据 |")
        lines.append("| 401 | 未授权 | 部分敏感接口未携带有效 token |")
        lines.append("| 500 | 业务失败 | 资源不存在、参数不合法、业务规则不满足 |")
        lines.append("| 422 | 参数校验失败 | Pydantic 校验失败，body 中给出 detail |")
        lines.append("")
        lines.append("> ⚠️ 注意：本系统未严格遵循 RESTful HTTP 状态码约定，"
                     "大量\"未找到\"等业务错误以 HTTP 200 + biz=500 的形式返回，"
                     "而不是 HTTP 404。这是历史设计选择。\n")

        lines.append("---\n")
        lines.append("## 二、详细测试用例与结果\n")
        for mod, items in sorted(by_mod.items()):
            mp = sum(1 for x in items if x.ok)
            lines.append(f"### {mod}（{mp}/{len(items)} 通过）\n")
            lines.append("| 方法 | 路径 | 场景 | 描述 | HTTP | 业务码 | 期望 | 耗时 | 结果 |")
            lines.append("|:----|:----|:----|:----|:----:|:----:|:----:|:----:|:----:|")
            for rr in items:
                em = "✅" if rr.ok else "❌"
                desc = (rr.d or "").replace("|", "\\|")
                lines.append(
                    f"| {rr.m} | `{rr.p}` | {rr.s} | {desc} | "
                    f"{rr.status} | {rr.biz} | {rr.expected} | {rr.ms}ms | {em} |"
                )
            lines.append("")

        failures = [r for r in self.results if not r.ok]
        if failures:
            lines.append("---\n")
            lines.append("## 三、失败用例详情\n")
            lines.append(f"共 **{len(failures)}** 个用例未达预期：\n")
            for i, rr in enumerate(failures, 1):
                lines.append(f"### {i}. {rr.m} {rr.p} - {rr.s}\n")
                lines.append(f"- **描述**：{rr.d}")
                lines.append(f"- **期望**：{rr.expected}")
                lines.append(f"- **实际**：HTTP={rr.status}, biz={rr.biz}")
                lines.append(f"- **响应**：`{rr.excerpt}`")
                if rr.err:
                    lines.append(f"- **错误**：{rr.err}")
                lines.append("")

        lines.append("---\n")
        lines.append("## 四、性能统计\n")
        ds = [r.ms for r in self.results if r.ms > 0]
        if ds:
            ds.sort()
            avg = sum(ds) // len(ds)
            p50 = ds[len(ds) // 2]
            p95 = ds[int(len(ds) * 0.95)]
            p99_idx = int(len(ds) * 0.99)
            p99 = ds[p99_idx] if p99_idx < len(ds) else ds[-1]
            lines.append("| 指标 | 数值 |")
            lines.append("|:----|:----:|")
            lines.append(f"| 平均耗时 | **{avg}ms** |")
            lines.append(f"| P50 | **{p50}ms** |")
            lines.append(f"| P95 | **{p95}ms** |")
            lines.append(f"| P99 | **{p99}ms** |")
            lines.append(f"| 最快 | **{min(ds)}ms** |")
            lines.append(f"| 最慢 | **{max(ds)}ms** |")
            lines.append("")
            slow = sorted(self.results, key=lambda x: x.ms, reverse=True)[:10]
            lines.append("### 最慢的 10 个接口\n")
            lines.append("| 方法 | 路径 | 场景 | 耗时 |")
            lines.append("|:----|:----|:----|:----:|")
            for rr in slow:
                lines.append(f"| {rr.m} | `{rr.p}` | {rr.s} | **{rr.ms}ms** |")
            lines.append("")

        lines.append("---\n")
        lines.append("## 五、测试结论\n")
        if failed == 0:
            lines.append("✅ **全部用例通过**，后端 API 行为符合预期。\n")
        else:
            lines.append(f"⚠️ 共 **{failed}** 个用例未达预期。\n")
            lines.append("失败用例可分为：\n")
            lines.append("1. **业务码语义差异** — 期望 404 但系统返回 biz=500（本系统约定）")
            lines.append("2. **接口字段不一致** — 部分接口字段命名与直觉不一致（已纠正）")
            lines.append("3. **认证不强制** — 部分敏感接口未强制要求 token")
            lines.append("4. **真实 bug** — 业务逻辑或异常处理缺陷\n")

        lines.append("---\n")
        lines.append("## 六、测试方法说明\n")
        lines.append("### 测试范围\n")
        lines.append("- ✅ **正常路径**：每个核心接口的成功调用")
        lines.append("- ✅ **错误数据**：不存在的 ID、非法值、超出范围")
        lines.append("- ✅ **参数缺失**：缺少必填字段，验证 Pydantic 校验")
        lines.append("- ✅ **空数据**：空字符串、空列表")
        lines.append("- ✅ **边界值**：金额负数、温度超范围\n")
        lines.append("### 不在测试范围\n")
        lines.append("- ❌ 并发/压测（详见 performance.md）")
        lines.append("- ❌ 安全渗透测试（SQL 注入、XSS）")
        lines.append("- ❌ 文件上传细节")
        lines.append("- ❌ 体检/手术等深度业务流（仅覆盖列表）\n")
        lines.append("### 执行方式\n")
        lines.append("```bash")
        lines.append("cd fastapi_be && uvicorn app.main:app --host 0.0.0.0 --port 8000")
        lines.append("python tests/api/test_all_endpoints.py")
        lines.append("```\n")
        lines.append("### 输出文件\n")
        lines.append("- `tests/api/test_results.json` — 原始结果（机器可读）")
        lines.append("- `doc/api-test-report.md` — 本文档（人类可读）\n")
        lines.append("### 测试数据\n")
        lines.append(f"- 管理员：{ADMIN_USER} / {ADMIN_PASS}")
        lines.append(f"- 患者：patient_id={P_ID}（身份证 {IDENTITY}）")
        lines.append(f"- 医生：doctor_id={D_ID}，科室：department_id={DEPT_ID}")
        lines.append(f"- 药品：pharmaceutical_id={PH_ID}")
        lines.append(f"- 病区：ward_id={W_ID}，床位：bed_id={B_ID}")
        lines.append(f"- 入院：admission_id={ADM_ID}\n")
        lines.append("### 维护约定\n")
        lines.append("1. 新增 API 后，在 `get_cases()` 末尾添加 T() 调用")
        lines.append("2. 修改 schemas 字段后，同步更新 T() 的 body 参数")
        lines.append("3. 修复 bug 后重跑测试确认通过\n")
        lines.append("---\n")
        lines.append("## 七、相关文档\n")
        lines.append("- [API 完整文档](apiDoc.md)")
        lines.append("- [架构文档](architecture.md)")
        lines.append("- [测试指南](testing.md)")
        lines.append("- [数据字典](data-dictionary.md)")

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        print(f"\n=== Reports ===")
        print(f"  JSON: {json_path}")
        print(f"  Markdown: {md_path}")
        print(f"  Total: {total}, Passed: {passed} ({rate:.1f}%), Failed: {failed}")


def main():
    tester = APITester(BASE_URL)
    if not tester.login():
        print("Cannot login, abort.")
        sys.exit(1)

    cases = get_cases()
    print(f"\nRunning {len(cases)} test cases...")
    tester.run_all(cases)

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tester.report(
        os.path.join(root, "tests", "api", "test_results.json"),
        os.path.join(root, "doc", "api-test-report.md"),
    )


if __name__ == "__main__":
    main()
