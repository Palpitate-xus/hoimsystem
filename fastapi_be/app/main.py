import datetime
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import settings

MICROSECOND_PATTERN = re.compile(rb'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})\.\d+')


# 操作日志：路径到中文操作名的映射
ACTION_MAP = {
    "login": "登录",
    "register": "注册",
    "logout": "退出",
    "create": "新增",
    "update": "更新",
    "delete": "删除",
    "audit": "审核",
    "cancel": "取消",
    "stop": "停止",
    "apply": "申请",
    "checkIn": "签到/报到",
    "dispense": "发药",
    "refund": "退费",
    "settle": "结算",
    "send": "发送",
    "upload": "上传",
    "restore": "还原",
    "backup": "备份",
    "sign": "签名",
    "review": "点评",
    "doDischarge": "出院办理",
    "windowRegistration": "窗口挂号",
    "transferBed": "换床",
}

# 路径模块名到中文对象的映射（按精确度排序，长的优先）
TARGET_MAP_ORDERED = [
    ("patientmanagement", "患者"),
    ("doctormanagement", "医生"),
    ("departmentmanagement", "科室"),
    ("pharmaceuticalmanagement", "药品"),
    ("noticemanagement", "公告"),
    ("appointmentmanagement", "预约"),
    ("registrationmanagement", "挂号"),
    ("prescriptionmanagement", "处方"),
    ("medicalrecordmanagement", "病历"),
    ("inpatientorder", "住院医嘱"),
    ("inpatientcharge", "住院费用"),
    ("clinicalpathway", "临床路径"),
    ("adversereaction", "药品不良反应"),
    ("adverseevent", "不良事件"),
    ("digitalsignature", "数字签名"),
    ("vitalsign", "生命体征"),
    ("triagedesk", "分诊台"),
    ("checkin", "签到"),
    ("breach", "违约"),
    ("labresult", "检验结果"),
    ("laborder", "检验申请"),
    ("exam", "体检"),
    ("admission", "入院"),
    ("discharge", "出院"),
    ("surgery", "手术"),
    ("nursing", "护理"),
    ("followup", "随访"),
    ("referral", "转诊"),
    ("mdt", "多学科会诊"),
    ("emr", "电子病历"),
    ("invoice", "发票"),
    ("charge", "收费"),
    ("ward", "病区"),
    ("queue", "排队"),
    ("triage", "导诊"),
    ("message", "消息"),
    ("backup", "备份"),
    ("config", "配置"),
    ("dict", "字典"),
    ("notice", "公告"),
    ("consumable", "耗材"),
    ("purchase", "采购"),
    ("pharmacy", "药房"),
    ("upload", "文件"),
    ("doctor", "医生"),
    ("patient", "患者"),
    ("user", "用户"),
    ("log", "日志"),
    ("report", "报表"),
    ("login", "系统"),
    ("logout", "系统"),
    ("register", "用户"),
]


def parse_action_target(path: str) -> tuple[str, str]:
    """从API路径解析出操作和对象，例如：
    /api/patientManagement/create -> ("新增", "患者")
    /api/login -> ("登录", "系统")
    """
    parts = path.strip("/").split("/")
    # 去掉 api 前缀
    if parts and parts[0] == "api":
        parts = parts[1:]
    if not parts:
        return ("访问", "系统")

    # 单段路径：通常是登录/注册/登出等
    if len(parts) == 1:
        action = ACTION_MAP.get(parts[0], parts[0])
        return (action, "系统")

    # 最后一段通常是动作
    last = parts[-1]
    action = ACTION_MAP.get(last, last)

    # 第一段是模块名，按降序匹配
    module_segment = parts[0].lower()
    target = "系统"
    for keyword, name in TARGET_MAP_ORDERED:
        if module_segment.startswith(keyword) or keyword in module_segment:
            target = name
            break
    return (action, target)


class StripMicrosecondMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("application/json"):
            body = b""
            async for chunk in response.body_iterator:
                body += chunk
            body = MICROSECOND_PATTERN.sub(rb'\1', body)
            return Response(content=body, status_code=response.status_code, headers=dict(response.headers), media_type=response.media_type)
        return response


class OperationLogMiddleware(BaseHTTPMiddleware):
    """自动记录用户操作日志中间件"""

    # 只记录这些方法的请求
    LOG_METHODS = {"POST", "PUT", "DELETE"}
    # 不记录的路径关键词
    SKIP_PATHS = {"/log/", "/getList", "/getDetail", "/getPending"}

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        # 只记录指定方法的请求
        if request.method not in self.LOG_METHODS:
            return response

        path = request.url.path
        # 跳过日志查询、列表查询等GET-like POST操作
        if any(skip in path for skip in self.SKIP_PATHS):
            return response

        # 解析用户ID
        user_id = None
        access_token = request.headers.get("accesstoken")
        if access_token:
            try:
                from app.database import SessionLocal
                from app.dependencies import decode_access_token
                from app.models import User

                username = decode_access_token(access_token)
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.username == username).first()
                    if user:
                        user_id = user.user_id
                finally:
                    db.close()
            except Exception:
                pass

        # 解析IP
        client_ip = request.client.host if request.client else ""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        # 解析操作和对象
        action, target = parse_action_target(path)

        # 记录结果
        result = "成功" if 200 <= response.status_code < 400 else "失败"

        # 写入数据库
        try:
            from app.database import SessionLocal
            from app.models import OperationLog

            db = SessionLocal()
            try:
                log = OperationLog(
                    user_id=user_id,
                    action=action,
                    target=target,
                    result=result,
                    ip=client_ip,
                    create_time=datetime.datetime.now(),
                )
                db.add(log)
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

        return response


app = FastAPI(title="HOIM System FastAPI")

from app.routers import (
    admin,
    admission,
    adverse_event,
    adverse_reaction,
    backup,
    charge,
    checkin,
    clinical_pathway,
    consumable,
    digital_signature,
    discharge,
    doctor,
    emr,
    exam,
    followup,
    inpatient_charge,
    inpatient_order,
    lab,
    mdt,
    nursing,
    patient,
    pharmacy,
    purchase,
    queue,
    referral,
    report,
    research,
    surgery,
    system,
    triage,
    triage_desk,
    upload,
    user,
    vitalsign,
    ward,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=[
        "accept",
        "accept-encoding",
        "authorization",
        "content-type",
        "dnt",
        "origin",
        "user-agent",
        "x-csrftoken",
        "x-requested-with",
        "accesstoken",
    ],
)
app.add_middleware(StripMicrosecondMiddleware)
app.add_middleware(OperationLogMiddleware)

app.include_router(user.router, prefix="/api")
app.include_router(patient.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(doctor.router, prefix="/api")
app.include_router(pharmacy.router, prefix="/api")
app.include_router(charge.router, prefix="/api")
app.include_router(queue.router, prefix="/api")
app.include_router(checkin.router, prefix="/api")
app.include_router(vitalsign.router, prefix="/api")
app.include_router(lab.router, prefix="/api")
app.include_router(followup.router, prefix="/api")
app.include_router(report.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(triage.router, prefix="/api")
app.include_router(backup.router, prefix="/api")
app.include_router(triage_desk.router, prefix="/api")
app.include_router(consumable.router, prefix="/api")
app.include_router(purchase.router, prefix="/api")
app.include_router(adverse_reaction.router, prefix="/api")
app.include_router(adverse_event.router, prefix="/api")
app.include_router(digital_signature.router, prefix="/api")
app.include_router(referral.router, prefix="/api")
app.include_router(mdt.router, prefix="/api")
app.include_router(clinical_pathway.router, prefix="/api")
app.include_router(ward.router, prefix="/api")
app.include_router(admission.router, prefix="/api")
app.include_router(inpatient_order.router, prefix="/api")
app.include_router(nursing.router, prefix="/api")
app.include_router(inpatient_charge.router, prefix="/api")
app.include_router(discharge.router, prefix="/api")
app.include_router(emr.router, prefix="/api")
app.include_router(surgery.router, prefix="/api")
app.include_router(exam.router, prefix="/api")
app.include_router(research.router, prefix="/api")

import os

from fastapi.staticfiles import StaticFiles

upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")

# 自动创建数据库表（所有模型导入完成后）
from app.database import Base, engine

Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return {"message": "HOIM System FastAPI"}
