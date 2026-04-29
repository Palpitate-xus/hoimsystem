from pydantic import BaseModel
from typing import Optional, List
from datetime import date, datetime


class ResponseModel(BaseModel):
    code: int = 200
    msg: str = "success"
    data: Optional[dict] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    identity: str
    address: str
    sex: int
    phone: str
    birthday: str


class UserInfoRequest(BaseModel):
    accessToken: str


class IdRequest(BaseModel):
    id: int


class UuidRequest(BaseModel):
    uuid: str


class AppointmentCreateRequest(BaseModel):
    id: int
    date: str
    department_id: int
    doctor_id: int
    time: str
    specialist: int


class RegistrationCreateRequest(BaseModel):
    id: int
    doctor_id: int
    department_id: int
    specialist: int


class ChargeCommitRequest(BaseModel):
    id: str


class DepartmentCreateRequest(BaseModel):
    name: str
    phone: str
    director: int
    location: str


class NoticeCreateRequest(BaseModel):
    title: str
    content: str
    isemergency: int
    towho: list
    expiredtime: str


class DoctorCreateRequest(BaseModel):
    username: str
    password: str
    name: str
    title: str
    sex: str
    phone: str
    department: int
    permission: str
    education: str


class DoctorUpdateRequest(BaseModel):
    doctor_id: int
    name: str
    title: str
    sex: str
    phone: str
    department: int
    permission: str
    education: str


class DoctorScheduleCreateRequest(BaseModel):
    schedule: List[str]
    specialist: int
    number: int
    doctor: int


class PharmaceuticalCreateRequest(BaseModel):
    name: str
    stock: int
    price: str
    expireddate: str
    supplier: str
    remark: str


class PharmaceuticalUpdateRequest(BaseModel):
    pharmaceutical_id: int
    name: str
    stock: int
    price: str
    expireddate: str
    supplier: str
    remark: str


class PharmaceuticalStockQueryRequest(BaseModel):
    id: int


class PrescriptionCreateRequest(BaseModel):
    patient: int
    phas: List[dict]


class PrescriptionCancelRequest(BaseModel):
    prescription_id: str


class MedicalRecordCreateRequest(BaseModel):
    patient_id: int
    symptom: str
    result: str


class MedicalRecordUpdateRequest(BaseModel):
    medical_record_id: str
    symptom: str
    result: str


class MedicalRecordDetailRequest(BaseModel):
    medical_record_id: str


class PatientUpdateRequest(BaseModel):
    patient_id: int
    name: str
    sex: int
    phone: str
    address: str


class DepartmentUpdateRequest(BaseModel):
    department_id: int
    name: str
    phone: str
    director: int
    location: str


class NoticeUpdateRequest(BaseModel):
    notice_id: str
    title: str
    content: str
    isemergency: int
    towho: list
    expiredtime: str


class NoticeDeleteRequest(BaseModel):
    notice_id: str


class DoctorDeleteRequest(BaseModel):
    doctor_id: int


class DepartmentDeleteRequest(BaseModel):
    department_id: int


class PharmaceuticalDeleteRequest(BaseModel):
    pharmaceutical_id: int


class ChargeRefundRequest(BaseModel):
    charge_id: str
    reason: str


class InvoiceCreateRequest(BaseModel):
    charge_id: str


class InvoicePrintRequest(BaseModel):
    invoice_id: str


class QueueCallNextRequest(BaseModel):
    doctor_id: int


class QueuePassRequest(BaseModel):
    queue_id: int


class QueueSkipRequest(BaseModel):
    queue_id: int


class CheckInRequest(BaseModel):
    appointment_uuid: str
    identity: str


class VitalSignCreateRequest(BaseModel):
    patient_id: int
    temperature: float
    blood_pressure_systolic: int
    blood_pressure_diastolic: int
    pulse: int
    weight: float


class LabOrderCreateRequest(BaseModel):
    patient_id: int
    check_type: str
    check_items: List[str]
    urgent: int


class LabResultCreateRequest(BaseModel):
    lab_order_id: str
    sample_id: str
    result: str
    abnormal_flag: int


class LabResultAuditRequest(BaseModel):
    lab_result_id: str


class FollowUpCreatePlanRequest(BaseModel):
    patient_id: int
    plan_date: str
    content: str


class FollowUpRecordRequest(BaseModel):
    follow_up_id: int
    result: str
    patient_feedback: str


class ReviewCreateRequest(BaseModel):
    doctor_id: int
    visit_id: str
    score: int
    comment: Optional[str] = ""


class FollowUpAppointmentCreateRequest(BaseModel):
    patient_id: int
    doctor_id: int
    date: str
    time: str


class PharmacyAuditRequest(BaseModel):
    prescription_id: str


class PharmacyDispenseRequest(BaseModel):
    prescription_id: str


class PharmacyReturnRequest(BaseModel):
    prescription_id: str
    pha_id: int
    number: int
    reason: str


class LogListRequest(BaseModel):
    user_id: Optional[int] = None
    action: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    page: int
    page_size: int


class DictListRequest(BaseModel):
    dict_type: str


class DictCreateRequest(BaseModel):
    dict_type: str
    dict_code: str
    dict_value: str
    sort_order: int


class DictUpdateRequest(BaseModel):
    dict_id: int
    dict_code: str
    dict_value: str
    sort_order: int


class DictDeleteRequest(BaseModel):
    dict_id: int


class ConfigUpdateRequest(BaseModel):
    config_key: str
    config_value: str


class ReportOutpatientRequest(BaseModel):
    start_date: str
    end_date: str
    group_by: str


class ReportFinanceRequest(BaseModel):
    start_date: str
    end_date: str


class ReportPharmaceuticalRequest(BaseModel):
    start_date: str
    end_date: str


class ReportDoctorWorkloadRequest(BaseModel):
    start_date: str
    end_date: str
    doctor_id: Optional[int] = None


class TestRequest(BaseModel):
    data: Optional[str] = None
