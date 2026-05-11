import re

from pydantic import BaseModel, Field, field_validator


class ResponseModel(BaseModel):
    code: int = 200
    msg: str = "success"
    data: dict | None = None


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=50)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=24)
    password: str = Field(..., min_length=6, max_length=20)
    identity: str = Field(..., min_length=15, max_length=18)
    address: str = Field(default="", max_length=100)
    sex: int = Field(..., ge=0, le=1)
    phone: str = Field(..., min_length=11, max_length=11)
    birthday: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if not re.match(r"^1[3-9]\d{9}$", v):
            raise ValueError("手机号格式不正确")
        return v

    @field_validator("identity")
    @classmethod
    def validate_identity(cls, v):
        if not re.match(r"(^\d{15}$)|(^\d{17}([0-9]|X)$)", v, re.I):
            raise ValueError("身份证号格式不正确")
        return v


class UserInfoRequest(BaseModel):
    accesstoken: str


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
    schedule: list[str]
    specialist: int
    number: int
    doctor: int


class PharmaceuticalCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=24)
    stock: int = Field(..., ge=0)
    price: str
    expireddate: str
    supplier: str = Field(..., min_length=1, max_length=24)
    remark: str = Field(default="", max_length=100)

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        try:
            p = float(v)
            if p < 0:
                raise ValueError("价格不能为负数")
            return v
        except ValueError:
            raise ValueError("价格必须是有效数字")


class PharmaceuticalUpdateRequest(BaseModel):
    pharmaceutical_id: int
    name: str = Field(..., min_length=1, max_length=24)
    stock: int = Field(..., ge=0)
    price: str
    expireddate: str
    supplier: str = Field(..., min_length=1, max_length=24)
    remark: str = Field(default="", max_length=100)

    @field_validator("price")
    @classmethod
    def validate_price(cls, v):
        try:
            p = float(v)
            if p < 0:
                raise ValueError("价格不能为负数")
            return v
        except ValueError:
            raise ValueError("价格必须是有效数字")


class PharmaceuticalStockQueryRequest(BaseModel):
    id: int


class PrescriptionCreateRequest(BaseModel):
    patient: int
    phas: list[dict]


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
    allergy_history: str | None = None


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
    temperature: float = Field(..., gt=30, lt=45)
    blood_pressure_systolic: int = Field(..., gt=0, lt=300)
    blood_pressure_diastolic: int = Field(..., gt=0, lt=200)
    pulse: int = Field(..., gt=0, lt=300)
    weight: float = Field(..., gt=0, lt=500)


class LabOrderCreateRequest(BaseModel):
    patient_id: int
    check_type: str
    check_items: list[str]
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
    score: int = Field(..., ge=1, le=5)
    comment: str | None = Field(default="", max_length=500)


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
    user_id: int | None = None
    action: str | None = None
    start_time: str | None = None
    end_time: str | None = None
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
    doctor_id: int | None = None


class PaymentCreateRequest(BaseModel):
    charge_id: str
    channel: str  # wechat, alipay, cash
    amount: float


class PaymentQueryRequest(BaseModel):
    payment_no: str


class PaymentMockNotifyRequest(BaseModel):
    payment_no: str


class TestRequest(BaseModel):
    data: str | None = None


# ===== 住院管理 Schemas =====


class WardCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    department_id: int
    bed_count: int = Field(default=0, ge=0)
    nurse_station_phone: str | None = Field(default=None, max_length=11)
    location: str | None = Field(default=None, max_length=50)


class WardUpdateRequest(BaseModel):
    ward_id: int
    name: str | None = Field(default=None, min_length=1, max_length=50)
    department_id: int | None = None
    bed_count: int | None = Field(default=None, ge=0)
    nurse_station_phone: str | None = Field(default=None, max_length=11)
    location: str | None = Field(default=None, max_length=50)
    status: int | None = Field(default=None, ge=0, le=1)


class BedCreateRequest(BaseModel):
    ward_id: int
    bed_no: str = Field(..., min_length=1, max_length=10)
    room_no: str | None = Field(default=None, max_length=10)
    bed_type: str = Field(default="普通", max_length=10)
    price_per_day: float = Field(default=0, ge=0)


class BedUpdateRequest(BaseModel):
    bed_id: int
    bed_no: str | None = Field(default=None, min_length=1, max_length=10)
    room_no: str | None = Field(default=None, max_length=10)
    bed_type: str | None = Field(default=None, max_length=10)
    price_per_day: float | None = Field(default=None, ge=0)
    status: int | None = Field(default=None, ge=0, le=3)


class AdmissionCreateRequest(BaseModel):
    patient_id: int
    doctor_id: int
    department_id: int
    ward_id: int
    bed_id: int
    admission_type: int = Field(default=0, ge=0, le=3)
    admission_diagnosis: str | None = Field(default=None, max_length=200)
    chief_complaint: str | None = Field(default=None, max_length=200)
    present_illness: str | None = Field(default=None, max_length=500)
    past_history: str | None = Field(default=None, max_length=300)
    deposit_amount: float = Field(default=0, ge=0)


class AdmissionUpdateRequest(BaseModel):
    admission_id: str
    bed_id: int | None = None
    admission_diagnosis: str | None = Field(default=None, max_length=200)
    status: int | None = Field(default=None, ge=0, le=3)


class InpatientOrderCreateRequest(BaseModel):
    admission_id: str
    patient_id: int
    doctor_id: int
    order_type: int = Field(..., ge=0, le=1)  # 0=长期 1=临时
    category: str = Field(..., max_length=10)
    priority: int = Field(default=0, ge=0, le=2)
    note: str | None = Field(default=None, max_length=200)
    items: list[dict] = Field(default_factory=list)


class InpatientOrderStopRequest(BaseModel):
    order_id: str


class InpatientOrderItemCreateRequest(BaseModel):
    order_id: str
    item_name: str = Field(..., max_length=50)
    item_type: str = Field(default="drug", max_length=10)
    item_id_ref: int | None = None
    dose: str | None = Field(default=None, max_length=20)
    unit: str | None = Field(default=None, max_length=10)
    frequency: str | None = Field(default=None, max_length=20)
    route: str | None = Field(default=None, max_length=20)
    days: int = Field(default=1, ge=1)
    quantity: int = Field(default=1, ge=1)
    unit_price: float = Field(default=0, ge=0)


class OrderExecutionRequest(BaseModel):
    order_id: str
    status: int = Field(..., ge=0, le=3)
    note: str | None = Field(default=None, max_length=200)


class NursingRecordCreateRequest(BaseModel):
    admission_id: str
    patient_id: int
    record_time: str
    consciousness: str | None = Field(default=None, max_length=10)
    temperature: float | None = Field(default=None, ge=30, le=45)
    pulse: int | None = Field(default=None, ge=0, le=300)
    respiration: int | None = Field(default=None, ge=0, le=100)
    blood_pressure: str | None = Field(default=None, max_length=20)
    spo2: float | None = Field(default=None, ge=0, le=100)
    intake: str | None = Field(default=None, max_length=50)
    output: str | None = Field(default=None, max_length=50)
    skin_condition: str | None = Field(default=None, max_length=50)
    drainage: str | None = Field(default=None, max_length=50)
    note: str | None = Field(default=None, max_length=500)


class TemperatureRecordCreateRequest(BaseModel):
    admission_id: str
    patient_id: int
    record_date: str
    time_point: str = Field(default="06:00", max_length=5)
    temperature: float | None = Field(default=None, ge=30, le=45)
    pulse: int | None = Field(default=None, ge=0, le=300)
    respiration: int | None = Field(default=None, ge=0, le=100)
    blood_pressure: str | None = Field(default=None, max_length=20)
    stool_count: int | None = Field(default=None, ge=0)
    weight: float | None = Field(default=None, ge=0)
    intake: float | None = Field(default=None, ge=0)
    output: float | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=100)


class InpatientChargeCreateRequest(BaseModel):
    admission_id: str
    patient_id: int
    item_name: str = Field(..., max_length=50)
    item_type: str = Field(..., max_length=10)
    quantity: float = Field(default=1, ge=0)
    unit_price: float = Field(..., ge=0)
    charge_date: str
    related_order_id: str | None = None


class DischargeSummaryCreateRequest(BaseModel):
    admission_id: str
    patient_id: int
    doctor_id: int
    discharge_diagnosis: str | None = Field(default=None, max_length=200)
    treatment_summary: str | None = Field(default=None, max_length=1000)
    discharge_status: int = Field(default=0, ge=0, le=4)
    discharge_instruction: str | None = Field(default=None, max_length=500)
    follow_up_plan: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=300)


# ===== 结构化电子病历 Schemas =====


class MedicalRecordTemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    category: str = Field(..., max_length=20)
    content: str = Field(default="")
    department_id: int | None = None
    is_default: int = Field(default=0, ge=0, le=1)


class MedicalRecordTemplateUpdateRequest(BaseModel):
    template_id: int
    name: str | None = Field(default=None, min_length=1, max_length=50)
    category: str | None = Field(default=None, max_length=20)
    content: str | None = None
    department_id: int | None = None
    is_default: int | None = Field(default=None, ge=0, le=1)
    status: int | None = Field(default=None, ge=0, le=1)


class StructuredMedicalRecordCreateRequest(BaseModel):
    admission_id: str | None = None
    patient_id: int
    doctor_id: int
    record_type: int = Field(default=0, ge=0, le=3)
    chief_complaint: str | None = Field(default=None, max_length=300)
    present_illness: str | None = None
    past_history: str | None = Field(default=None, max_length=500)
    personal_history: str | None = Field(default=None, max_length=300)
    family_history: str | None = Field(default=None, max_length=300)
    physical_exam: str | None = None
    auxiliary_exam: str | None = None
    diagnosis: str | None = Field(default=None, max_length=300)
    treatment_plan: str | None = None


class StructuredMedicalRecordUpdateRequest(BaseModel):
    record_id: str
    chief_complaint: str | None = Field(default=None, max_length=300)
    present_illness: str | None = None
    past_history: str | None = Field(default=None, max_length=500)
    personal_history: str | None = Field(default=None, max_length=300)
    family_history: str | None = Field(default=None, max_length=300)
    physical_exam: str | None = None
    auxiliary_exam: str | None = None
    diagnosis: str | None = Field(default=None, max_length=300)
    treatment_plan: str | None = None
    status: int | None = Field(default=None, ge=0, le=2)


class ProgressNoteCreateRequest(BaseModel):
    admission_id: str
    patient_id: int
    doctor_id: int
    note_date: str
    content: str = Field(..., min_length=1)


class WardRoundCreateRequest(BaseModel):
    admission_id: str
    patient_id: int
    doctor_id: int
    round_type: int = Field(default=2, ge=0, le=2)
    content: str = Field(..., min_length=1)
    round_time: str | None = None


class MedicalRecordQualityCheckRequest(BaseModel):
    admission_id: str
    record_id: str | None = None
    check_item: str = Field(..., max_length=50)
    check_result: int = Field(default=0, ge=0, le=2)
    issue: str | None = Field(default=None, max_length=200)
    score: int = Field(default=100, ge=0, le=100)


# ===== 体检系统 Schemas =====


class ExamPackageCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    category: str = Field(..., max_length=20)
    price: float = Field(default=0, ge=0)
    items: str = Field(default="")
    description: str | None = Field(default=None, max_length=200)


class ExamPackageUpdateRequest(BaseModel):
    package_id: int
    name: str | None = Field(default=None, min_length=1, max_length=50)
    category: str | None = Field(default=None, max_length=20)
    price: float | None = Field(default=None, ge=0)
    items: str | None = None
    description: str | None = Field(default=None, max_length=200)
    status: int | None = Field(default=None, ge=0, le=1)


class ExamItemCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    category: str = Field(..., max_length=20)
    unit: str | None = Field(default=None, max_length=10)
    reference_range: str | None = Field(default=None, max_length=50)
    price: float = Field(default=0, ge=0)


class ExamItemUpdateRequest(BaseModel):
    item_id: int
    name: str | None = Field(default=None, min_length=1, max_length=50)
    category: str | None = Field(default=None, max_length=20)
    unit: str | None = Field(default=None, max_length=10)
    reference_range: str | None = Field(default=None, max_length=50)
    price: float | None = Field(default=None, ge=0)
    status: int | None = Field(default=None, ge=0, le=1)


class ExamAppointmentCreateRequest(BaseModel):
    patient_id: int
    package_id: int
    exam_date: str
    note: str | None = Field(default=None, max_length=200)


class ExamRecordUpdateRequest(BaseModel):
    record_id: str
    overall_result: str | None = Field(default=None, max_length=20)
    overall_advice: str | None = Field(default=None, max_length=500)
    doctor_id: int | None = None
    status: int | None = Field(default=None, ge=0, le=3)


class ExamResultCreateRequest(BaseModel):
    record_id: str
    item_id: int
    result_value: str | None = Field(default=None, max_length=100)
    unit: str | None = Field(default=None, max_length=10)
    reference_range: str | None = Field(default=None, max_length=50)
    abnormal_flag: int = Field(default=0, ge=0, le=3)
    note: str | None = Field(default=None, max_length=200)
