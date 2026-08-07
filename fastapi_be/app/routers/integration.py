import datetime
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import ImagingOrder, ImagingReport, LabOrder, LabResult, User
from app.routers.lab import check_critical_value
from app.schemas import ImagingReportIntegrationRequest, LabResultIntegrationRequest

router = APIRouter()


def _check_key(received_key: str | None, expected_key: str, system_name: str) -> None:
    if not expected_key:
        raise HTTPException(status_code=503, detail=f"{system_name}对接密钥未配置")
    if not received_key or not secrets.compare_digest(received_key, expected_key):
        raise HTTPException(status_code=401, detail="对接鉴权失败")


def _bind_external_order(order, external_order_id: str | None):
    if not external_order_id:
        return
    external_order_id = external_order_id.strip()
    if order.external_order_id and order.external_order_id != external_order_id:
        raise HTTPException(status_code=409, detail="外部单号与本地申请单绑定不一致")
    order.external_order_id = external_order_id


@router.post("/integration/lis/result")
def receive_lis_result(
    req: LabResultIntegrationRequest,
    x_integration_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """接收 LIS 结果；同一申请单重复回调只返回原结果，不重复生成结果。"""
    _check_key(x_integration_key, settings.LIS_INTEGRATION_KEY, "LIS")
    order = db.query(LabOrder).filter(LabOrder.lab_order_id == req.lab_order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="检验申请单不存在")
    _bind_external_order(order, req.external_order_id)
    existing = order.lab_results[0] if order.lab_results else None
    if existing:
        return {"code": 200, "msg": "结果已同步，重复回调已忽略", "data": {"lab_result_id": existing.lab_result_id, "idempotent": True}}
    if order.sample_status == 2:
        raise HTTPException(status_code=409, detail="样本已拒收，不能同步结果")
    now = datetime.datetime.now()
    order.sample_status = 1
    order.status = 1
    order.integration_status = "synced"
    order.last_sync_time = now
    result = LabResult(
        lab_order_id=order.lab_order_id,
        sample_id=req.sample_id,
        result=req.result,
        abnormal_flag=1 if check_critical_value(order.check_type or "", req.result) else req.abnormal_flag,
        technician_id=None,
        report_time=now,
        audit_status=0,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return {"code": 200, "msg": "LIS结果已接收，等待审核", "data": {"lab_result_id": result.lab_result_id, "idempotent": False}}


@router.post("/integration/pacs/report")
def receive_pacs_report(
    req: ImagingReportIntegrationRequest,
    x_integration_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """接收 PACS 影像报告；报告仍需院内审核后对患者可见。"""
    _check_key(x_integration_key, settings.PACS_INTEGRATION_KEY, "PACS")
    order = db.query(ImagingOrder).filter(ImagingOrder.imaging_order_id == req.imaging_order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="影像申请不存在")
    _bind_external_order(order, req.external_order_id)
    if order.report and order.integration_status == "synced":
        return {"code": 200, "msg": "影像报告已同步，重复回调已忽略", "data": {"report_id": order.report.report_id, "idempotent": True}}
    if order.report and order.report.status in (1, 2):
        raise HTTPException(status_code=409, detail="影像报告已进入院内审核流程，不能覆盖")
    author_id = order.doctor.user_id if order.doctor and order.doctor.user_id else None
    if not author_id:
        author = db.query(User).filter(User.user_role.in_(["admin", "super_admin"])).order_by(User.user_id).first()
        author_id = author.user_id if author else None
    if not author_id:
        raise HTTPException(status_code=503, detail="未找到可记录对接报告的院内操作用户")
    now = datetime.datetime.now()
    report = order.report or ImagingReport(imaging_order_id=order.imaging_order_id, author_id=author_id, status=0)
    report.findings = req.findings
    report.impression = req.impression
    report.report_time = now
    report.status = 0
    order.status = 3
    order.viewer_url = req.viewer_url.strip()[:500] if req.viewer_url and req.viewer_url.strip() else order.viewer_url
    order.integration_status = "synced"
    order.last_sync_time = now
    db.add(report)
    db.commit()
    db.refresh(report)
    return {"code": 200, "msg": "PACS报告已接收，等待审核", "data": {"report_id": report.report_id, "idempotent": False}}
