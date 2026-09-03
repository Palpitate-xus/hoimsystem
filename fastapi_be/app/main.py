import datetime
import json
import re
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.background import BackgroundTasks
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings
from app.observability import ObservabilityMiddleware

MICROSECOND_PATTERN = re.compile(rb'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})\.\d+')

# 旧接口把业务错误放在 JSON ``code`` 中但仍返回 HTTP 200。统一响应类在不改变
# 响应体契约的前提下修正传输层状态码；旧的 code=500 多为参数/状态冲突，而不是
# 服务崩溃，因此映射为 400，真正的未处理异常仍由 FastAPI 返回 HTTP 500。
LEGACY_BUSINESS_HTTP_STATUS = {
    400: 400,
    401: 401,
    403: 403,
    404: 404,
    409: 409,
    422: 422,
    429: 429,
    500: 400,
    501: 501,
}


class APIJSONResponse(JSONResponse):
    """Serialize API JSON once and preserve meaningful HTTP semantics."""

    def __init__(self, content, status_code=200, *args, **kwargs):
        if status_code == 200 and isinstance(content, dict):
            status_code = LEGACY_BUSINESS_HTTP_STATUS.get(content.get("code"), status_code)
        super().__init__(content=content, status_code=status_code, *args, **kwargs)

    def render(self, content) -> bytes:
        return MICROSECOND_PATTERN.sub(rb'\1', super().render(content))


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


class OriginValidationMiddleware(BaseHTTPMiddleware):
    """Reject cross-site state changes before they reach business handlers."""

    STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

    async def dispatch(self, request, call_next):
        origin = request.headers.get("origin")
        if request.method in self.STATE_CHANGING_METHODS and origin and origin not in settings.cors_origins:
            return JSONResponse(status_code=403, content={"code": 403, "msg": "请求来源不受信任"})
        return await call_next(request)


class OperationLogMiddleware(BaseHTTPMiddleware):
    """全量操作审计中间件。

    记录维度:
    - 谁(username + role)
    - 什么时候(create_time)
    - 从哪里(ip + x-forwarded-for)
    - 做了什么(method + path + action + target)
    - 涉及什么对象(detail: 患者ID/处方ID等)
    - 结果如何(result + status_code)

    审计策略:
    - 所有 POST/PUT/DELETE 全量记录
    - GET 仅记录敏感路径(查看病历/处方/患者详情/导出/打印)
    - 排除静态资源、健康检查、token 心跳
    """

    # 始终跳过的路径(无业务含义)
    SKIP_PATHS = {
        "/docs", "/openapi.json", "/favicon.ico",
        "/api/logout", "/api/test", "/api/publicKey",
    }
    # 登录/注册本身需要审计：记录成功与失败（含 401/403），否则暴力破解不留痕迹。
    # 用户名从请求体提取，密码绝不落日志。
    AUTH_BODY_PATHS = {"/api/login", "/api/register"}
    # GET 也记录的敏感路径(医疗合规:谁看了什么)
    SENSITIVE_GET_PATHS = {
        "/api/medicalRecord/detail",
        "/api/prescriptionManagement/getList",
        "/api/chargeManagement/getList",
        "/api/patientManagement/getList",
        "/api/medicalRecord/getList",
        "/api/labResult/detail",
        "/api/examReport/getDetail",
        "/api/research/export",
        "/api/invoice/print",
        "/api/backup/download",
    }

    async def dispatch(self, request, call_next):
        started_at = time.perf_counter()
        # 登录/注册请求体需在 call_next 之前缓存（之后流已被消费），
        # 用于审计用户名；密码绝不落日志。
        auth_attempted_username = ""
        if request.url.path in self.AUTH_BODY_PATHS:
            try:
                raw = await request.body()
                parsed = json.loads(raw) if raw else {}
                if isinstance(parsed, dict):
                    auth_attempted_username = str(parsed.get("username") or parsed.get("identity") or "")[:64]
            except Exception:
                auth_attempted_username = ""
        response = await call_next(request)
        response_time_ms = round((time.perf_counter() - started_at) * 1000, 2)
        path = request.url.path
        method = request.method

        # 跳过静态资源
        if any(path.startswith(p) for p in self.SKIP_PATHS):
            return response
        if path.startswith("/uploads/"):
            return response

        # 判断是否需要记录
        should_log = False
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            should_log = True
        elif method == "GET":
            # GET 仅记录敏感路径
            if any(path.startswith(p) for p in self.SENSITIVE_GET_PATHS):
                should_log = True
        if not should_log:
            return response

        # 解析用户
        user_id = None
        username = ""
        role = ""
        auth_identity = getattr(request.state, "auth_identity", None)
        if auth_identity is not None:
            user_id, username, role = auth_identity

        # 登录/注册请求：使用进入中间件前缓存的用户名（密码绝不落日志）
        if path in self.AUTH_BODY_PATHS and not username and auth_attempted_username:
            username = f"{auth_attempted_username}(attempt)"

        # 解析IP
        client_ip = request.client.host if request.client else ""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            client_ip = forwarded_for.split(",")[0].strip()

        # 解析操作和对象
        action, target = parse_action_target(path)

        # 提取 detail: 从 query params 取 id 类参数
        detail_parts = []
        for k in ("id", "uuid", "patient_id", "prescription_id", "charge_id",
                  "admission_id", "medical_record_id", "schedule_id"):
            v = request.query_params.get(k)
            if v:
                detail_parts.append(f"{k}={v}")
        detail = ",".join(detail_parts)[:500]

        # 结果
        status_code = response.status_code
        result = "成功" if 200 <= status_code < 400 else "失败"

        # 写入数据库（挂到响应后台任务：响应发送完毕、请求级依赖均已释放后再写，
        # 避免与处理器会话争用同一连接导致审计丢失；失败只记日志不影响主请求）
        def _write_audit_log() -> None:
            try:
                from app.database import SessionLocal
                from app.models import OperationLog

                db = SessionLocal()
                try:
                    log = OperationLog(
                        user_id=user_id,
                        username=username or "anonymous",
                        role=role or "unknown",
                        action=action,
                        target=target,
                        detail=detail,
                        result=result,
                        status_code=status_code,
                        response_time_ms=response_time_ms,
                        ip=client_ip,
                        method=method,
                        path=path,
                        create_time=datetime.datetime.now(),
                    )
                    db.add(log)
                    db.commit()
                except Exception:
                    db.rollback()
                finally:
                    db.close()
            except Exception:
                import logging
                logging.getLogger("audit").warning("写入审计日志失败", exc_info=True)

        # 合并已有 background（如依赖注入的清理任务），保证不互相覆盖
        existing_background = getattr(response, "background", None)
        tasks = BackgroundTasks()
        if isinstance(existing_background, BackgroundTasks):
            tasks = existing_background
        elif existing_background is not None:
            tasks.add_task(existing_background.run)
        tasks.add_task(_write_audit_log)
        response.background = tasks
        return response


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.AUTO_CREATE_SCHEMA:
        from app.database import Base, engine
        from app.schema_compat import ensure_operation_log_schema

        Base.metadata.create_all(bind=engine)
        ensure_operation_log_schema(engine)

    if settings.SCHEDULER_ENABLED:
        from app.scheduler import start_scheduler

        start_scheduler()
    try:
        yield
    finally:
        if settings.SCHEDULER_ENABLED:
            from app.scheduler import stop_scheduler

            stop_scheduler()


app = FastAPI(title="HOIM System FastAPI", default_response_class=APIJSONResponse, lifespan=lifespan)

from app.routers import (
    admin,
    admission,
    adverse_event,
    adverse_reaction,
    allergy,
    antibiotic,
    backup,
    blood,
    charge,
    charge_item,
    checkin,
    clinical_pathway,
    consumable,
    data_import_export,
    diagnosis_template,
    digital_signature,
    discharge,
    doctor,
    drug_damage,
    emergency,
    emr,
    equipment,
    exam,
    family_member,
    followup,
    home_icd,
    icd10,
    imaging,
    infection,
    infection_control,
    infusion,
    injection,
    inpatient_charge,
    inpatient_order,
    insurance,
    insurance_catalog,
    integration,
    inventory_adjustment,
    lab,
    lab_package,
    lab_qc,
    mdt,
    medical_record_archive,
    medical_record_home,
    medical_record_home_quality,
    monitor,
    navigation,
    nursing,
    ops_extension,
    patient,
    patient_card,
    performance,
    pharmacy,
    prescription_template,
    purchase,
    quality_management,
    queue,
    referral,
    report,
    research,
    rx_review_rule,
    schedule_change,
    scheduler,
    shift_handover,
    skin_test,
    special_drug,
    surgery,
    system,
    triage,
    triage_desk,
    upload,
    user,
    version,
    vitalsign,
    ward,
)
from app.routers import (
    observability as observability_routes,
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
    expose_headers=["x-request-id"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(OriginValidationMiddleware)
app.add_middleware(OperationLogMiddleware)
app.add_middleware(ObservabilityMiddleware)

app.include_router(observability_routes.router)
app.include_router(performance.router, prefix="/api")
app.include_router(home_icd.router, prefix="/api")
app.include_router(version.router, prefix="/api")
app.include_router(rx_review_rule.router, prefix="/api")
app.include_router(insurance_catalog.router, prefix="/api")
app.include_router(infection_control.router, prefix="/api")
app.include_router(quality_management.router, prefix="/api")
app.include_router(ops_extension.router, prefix="/api")
app.include_router(user.router, prefix="/api")
app.include_router(patient.router, prefix="/api")
app.include_router(patient_card.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(doctor.router, prefix="/api")
app.include_router(drug_damage.router, prefix="/api")
app.include_router(diagnosis_template.router, prefix="/api")
app.include_router(emergency.router, prefix="/api")
app.include_router(equipment.router, prefix="/api")
app.include_router(pharmacy.router, prefix="/api")
app.include_router(prescription_template.router, prefix="/api")
app.include_router(charge.router, prefix="/api")
app.include_router(charge_item.router, prefix="/api")
app.include_router(queue.router, prefix="/api")
app.include_router(checkin.router, prefix="/api")
app.include_router(vitalsign.router, prefix="/api")
app.include_router(lab.router, prefix="/api")
app.include_router(lab_package.router, prefix="/api")
app.include_router(lab_qc.router, prefix="/api")
app.include_router(followup.router, prefix="/api")
app.include_router(family_member.router, prefix="/api")
app.include_router(report.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(triage.router, prefix="/api")
app.include_router(backup.router, prefix="/api")
app.include_router(blood.router, prefix="/api")
app.include_router(triage_desk.router, prefix="/api")
app.include_router(consumable.router, prefix="/api")
app.include_router(purchase.router, prefix="/api")
app.include_router(adverse_reaction.router, prefix="/api")
app.include_router(allergy.router, prefix="/api")
app.include_router(antibiotic.router, prefix="/api")
app.include_router(adverse_event.router, prefix="/api")
app.include_router(digital_signature.router, prefix="/api")
app.include_router(data_import_export.router, prefix="/api")
app.include_router(referral.router, prefix="/api")
app.include_router(mdt.router, prefix="/api")
app.include_router(monitor.router, prefix="/api")
app.include_router(navigation.router, prefix="/api")
app.include_router(clinical_pathway.router, prefix="/api")
app.include_router(ward.router, prefix="/api")
app.include_router(admission.router, prefix="/api")
app.include_router(inpatient_order.router, prefix="/api")
app.include_router(imaging.router, prefix="/api")
app.include_router(inventory_adjustment.router, prefix="/api")
app.include_router(infusion.router, prefix="/api")
app.include_router(integration.router, prefix="/api")
app.include_router(insurance.router, prefix="/api")
app.include_router(infection.router, prefix="/api")
app.include_router(injection.router, prefix="/api")
app.include_router(skin_test.router, prefix="/api")
app.include_router(shift_handover.router, prefix="/api")
app.include_router(schedule_change.router, prefix="/api")
app.include_router(scheduler.router, prefix="/api")
app.include_router(special_drug.router, prefix="/api")
app.include_router(nursing.router, prefix="/api")
app.include_router(inpatient_charge.router, prefix="/api")
app.include_router(discharge.router, prefix="/api")
app.include_router(emr.router, prefix="/api")
app.include_router(medical_record_home.router, prefix="/api")
app.include_router(medical_record_home_quality.router, prefix="/api")
app.include_router(medical_record_archive.router, prefix="/api")
app.include_router(icd10.router, prefix="/api")
app.include_router(surgery.router, prefix="/api")
app.include_router(exam.router, prefix="/api")
app.include_router(research.router, prefix="/api")

import os

# 上传文件不再通过无鉴权的 StaticFiles 目录对外暴露。
# 统一走 /api/uploads/... 路由：报告下载需登录，且返回带 nosniff + attachment 头，
# 防止上传 HTML/SVG 造成存储型 XSS 以及未授权读取上传文件。
upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(os.path.join(upload_dir, "avatars"), exist_ok=True)
os.makedirs(os.path.join(upload_dir, "reports"), exist_ok=True)


from app.routers.version import APP_VERSION  # noqa: E402


@app.get("/")
def root():
    return {"message": "HOIM System FastAPI", "version": APP_VERSION}
