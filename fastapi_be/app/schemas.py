import re

from pydantic import BaseModel, Field, field_validator


class ResponseModel(BaseModel):
    code: int = 200
    msg: str = "success"
    data: dict | None = None


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=512)


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=24)
    password: str = Field(..., min_length=6, max_length=512)
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
    schedule_id: int | None = None


class AppointmentCreateRequest(BaseModel):
    id: int
    date: str
    department_id: int
    doctor_id: int
    time: str
    specialist: int
    patient_id: int | None = None


class RegistrationCreateRequest(BaseModel):
    id: int
    doctor_id: int
    department_id: int
    specialist: int
    patient_id: int | None = None


class ChargeCommitRequest(BaseModel):
    id: str


class DepartmentCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=24)
    phone: str = Field(default="", max_length=11)
    director: int | None = None
    location: str = Field(default="", max_length=24)
    campus_id: int | None = None


class CampusCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=1, max_length=50)
    address: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=20)
    status: int = Field(default=1, ge=0, le=1)
    sort_order: int = Field(default=0, ge=0, le=9999)


class CampusUpdateRequest(CampusCreateRequest):
    campus_id: int


class CampusDeleteRequest(BaseModel):
    campus_id: int


class NavigationNodeCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=40)
    name: str = Field(..., min_length=1, max_length=80)
    node_type: str = Field(default="waypoint", max_length=20)
    floor: str = Field(default="", max_length=20)
    location: str = Field(default="", max_length=200)
    campus_id: int | None = None
    department_id: int | None = None
    status: int = Field(default=1, ge=0, le=1)


class NavigationNodeUpdateRequest(NavigationNodeCreateRequest):
    node_id: int


class NavigationNodeDeleteRequest(BaseModel):
    node_id: int


class NavigationEdgeCreateRequest(BaseModel):
    from_node_id: int
    to_node_id: int
    distance: float = Field(..., gt=0, le=100000)
    instruction: str = Field(default="", max_length=200)
    bidirectional: int = Field(default=1, ge=0, le=1)
    status: int = Field(default=1, ge=0, le=1)


class NavigationEdgeUpdateRequest(NavigationEdgeCreateRequest):
    edge_id: int


class NavigationEdgeDeleteRequest(BaseModel):
    edge_id: int


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


class ScheduleChangeCreateRequest(BaseModel):
    request_type: str
    target_date: str
    schedule_id: int | None = None
    extra_slots: int = Field(default=0, ge=0, le=100)
    reason: str = Field(..., min_length=1, max_length=200)


class ScheduleChangeActionRequest(BaseModel):
    request_id: str


class EmergencyTriageCreateRequest(BaseModel):
    patient_id: int
    triage_level: int = Field(..., ge=1, le=4)
    chief_complaint: str = Field(..., min_length=1, max_length=500)
    vital_signs: str = Field(default="", max_length=500)
    green_channel: int = Field(default=0, ge=0, le=1)


class EmergencyTriageUpdateRequest(BaseModel):
    triage_id: str
    triage_level: int | None = Field(default=None, ge=1, le=4)
    green_channel: int | None = Field(default=None, ge=0, le=1)
    status: int | None = Field(default=None, ge=0, le=3)


class EmergencyRescueEventCreateRequest(BaseModel):
    triage_id: str
    event_type: str = Field(..., min_length=1, max_length=30)
    description: str = Field(..., min_length=1, max_length=500)
    medication: str = Field(default="", max_length=300)
    event_time: str | None = None


class EmergencyObservationCreateRequest(BaseModel):
    triage_id: str
    condition: str = Field(..., min_length=1, max_length=500)
    medical_advice: str = Field(default="", max_length=500)
    fee_amount: float = Field(default=0, ge=0, le=1000000)


class EmergencyObservationUpdateRequest(BaseModel):
    observation_id: str
    condition: str | None = Field(default=None, min_length=1, max_length=500)
    medical_advice: str | None = Field(default=None, max_length=500)
    fee_amount: float | None = Field(default=None, ge=0, le=1000000)
    fee_status: int | None = Field(default=None, ge=0, le=1)
    status: int | None = Field(default=None, ge=1, le=3)


class EmergencyGreenChannelCreateRequest(BaseModel):
    triage_id: str
    reason: str = Field(..., min_length=1, max_length=500)


class EmergencyGreenChannelActionRequest(BaseModel):
    channel_id: str
    note: str = Field(default="", max_length=500)


class EmergencyMedicalRecordCreateRequest(BaseModel):
    triage_id: str
    chief_complaint: str = Field(..., min_length=1, max_length=500)
    present_illness: str = Field(default="", max_length=1000)
    physical_exam: str = Field(default="", max_length=1000)
    diagnosis: str = Field(default="", max_length=500)
    treatment_plan: str = Field(default="", max_length=1000)


class EmergencyMedicalRecordUpdateRequest(BaseModel):
    record_id: str
    chief_complaint: str | None = Field(default=None, min_length=1, max_length=500)
    present_illness: str | None = Field(default=None, max_length=1000)
    physical_exam: str | None = Field(default=None, max_length=1000)
    diagnosis: str | None = Field(default=None, max_length=500)
    treatment_plan: str | None = Field(default=None, max_length=1000)


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


class PharmacyVerificationRequest(BaseModel):
    verification_id: str
    note: str = Field(default="", max_length=200)


class PrescriptionTemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    items: list[dict]


class PrescriptionTemplateUpdateRequest(PrescriptionTemplateCreateRequest):
    template_id: int


class PrescriptionTemplateIdRequest(BaseModel):
    template_id: int


class DiagnosisTemplateCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=100)


class DiagnosisTemplateUpdateRequest(DiagnosisTemplateCreateRequest):
    template_id: int


class DiagnosisTemplateIdRequest(BaseModel):
    template_id: int


class InfusionCreateRequest(BaseModel):
    patient_id: int
    pharmaceutical_id: int
    dose: str = Field(..., min_length=1, max_length=50)
    batch_no: str = Field(..., min_length=1, max_length=50)
    drip_rate: int | None = Field(default=None, ge=1, le=300)
    note: str = Field(default="", max_length=200)


class InfusionIdRequest(BaseModel):
    infusion_id: str


class InfusionObservationRequest(BaseModel):
    infusion_id: str
    drip_rate: int = Field(..., ge=1, le=300)
    volume: int | None = Field(default=None, ge=0)
    condition: str = Field(..., min_length=1, max_length=200)


class InjectionCreateRequest(BaseModel):
    patient_id: int
    pharmaceutical_id: int
    route: str
    dose: str = Field(..., min_length=1, max_length=50)
    note: str = Field(default="", max_length=200)


class InjectionIdRequest(BaseModel):
    injection_id: str


class SkinTestCreateRequest(BaseModel):
    patient_id: int
    pharmaceutical_id: int
    dose: str = Field(..., min_length=1, max_length=50)
    site: str = Field(..., min_length=1, max_length=30)
    observe_minutes: int = Field(default=15, ge=5, le=120)


class SkinTestIdRequest(BaseModel):
    skin_test_id: str


class SkinTestAssessRequest(BaseModel):
    skin_test_id: str
    result: str
    note: str = Field(default="", max_length=200)


class PatientAllergyCreateRequest(BaseModel):
    patient_id: int
    allergen: str = Field(..., min_length=1, max_length=100)
    reaction: str = Field(..., min_length=1, max_length=200)
    severity: int = Field(default=1, ge=1, le=3)
    note: str = Field(default="", max_length=200)


class PatientAllergyUpdateRequest(PatientAllergyCreateRequest):
    allergy_id: int


class PatientAllergyIdRequest(BaseModel):
    allergy_id: int


class ShiftHandoverCreateRequest(BaseModel):
    shift_type: str = Field(..., min_length=1, max_length=20)
    content: str = Field(..., min_length=1, max_length=2000)


class ShiftHandoverIdRequest(BaseModel):
    handover_id: str


class InventoryAdjustmentCreateRequest(BaseModel):
    pharmaceutical_id: int
    adjustment_type: str
    quantity: int = Field(..., gt=0)
    reason: str = Field(..., min_length=1, max_length=200)


class InventoryAdjustmentActionRequest(BaseModel):
    adjustment_id: int


class SpecialDrugRegisterCreateRequest(BaseModel):
    pharmaceutical_id: int
    patient_id: int | None = None
    action: str
    quantity: int = Field(..., gt=0)
    reason: str = Field(..., min_length=1, max_length=200)


class SpecialDrugRegisterActionRequest(BaseModel):
    register_id: str


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


class FamilyMemberCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=24)
    identity: str = Field(..., min_length=15, max_length=18)
    relation: str = Field(..., min_length=1, max_length=20)
    sex: int = Field(..., ge=0, le=1)
    birthday: str | None = None
    phone: str = Field(default="", max_length=11)
    address: str = Field(default="", max_length=100)
    allergy_history: str = Field(default="", max_length=200)

    @field_validator("identity")
    @classmethod
    def validate_identity(cls, v):
        if not re.match(r"(^\d{15}$)|(^\d{17}([0-9]|X)$)", v, re.I):
            raise ValueError("身份证号格式不正确")
        return v.upper()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        if v and not re.match(r"^1[3-9]\d{9}$", v):
            raise ValueError("手机号格式不正确")
        return v


class FamilyMemberUpdateRequest(FamilyMemberCreateRequest):
    family_member_id: int


class DepartmentUpdateRequest(BaseModel):
    department_id: int
    name: str = Field(..., min_length=1, max_length=24)
    phone: str = Field(default="", max_length=11)
    director: int | None = None
    location: str = Field(default="", max_length=24)
    campus_id: int | None = None


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


class ChargeItemCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=1, max_length=100)
    category: str = Field(..., min_length=1, max_length=30)
    price: float = Field(..., ge=0)
    note: str = Field(default="", max_length=200)


class ChargeItemUpdateRequest(ChargeItemCreateRequest):
    item_id: int


class ChargeItemIdRequest(BaseModel):
    item_id: int


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


class LabCriticalActionRequest(BaseModel):
    lab_result_id: str
    note: str = Field(default="", max_length=500)


class LabResultIntegrationRequest(BaseModel):
    lab_order_id: str = Field(..., min_length=1, max_length=36)
    external_order_id: str | None = Field(default=None, max_length=100)
    sample_id: str = Field(default="", max_length=20)
    result: str = Field(default="", max_length=10000)
    abnormal_flag: int = Field(default=0, ge=0, le=1)


class ImagingReportIntegrationRequest(BaseModel):
    imaging_order_id: str = Field(..., min_length=1, max_length=36)
    external_order_id: str | None = Field(default=None, max_length=100)
    findings: str = Field(default="", max_length=20000)
    impression: str = Field(default="", max_length=10000)
    viewer_url: str | None = Field(default=None, max_length=500)


class InsuranceSettlementIntegrationRequest(BaseModel):
    settlement_id: str = Field(..., min_length=1, max_length=36)
    external_settlement_id: str | None = Field(default=None, max_length=100)
    status: int = Field(..., ge=1, le=2)
    total_amount: float = Field(..., gt=0)
    covered_amount: float = Field(..., ge=0)
    self_amount: float | None = Field(default=None, ge=0)


class LabPackageCreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=1, max_length=100)
    category: str = Field(default="", max_length=50)
    items: str = Field(default="", max_length=1000)
    price: float = Field(default=0, ge=0)


class LabPackageUpdateRequest(BaseModel):
    package_id: int
    code: str | None = Field(default=None, min_length=1, max_length=30)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    category: str | None = Field(default=None, max_length=50)
    items: str | None = Field(default=None, max_length=1000)
    price: float | None = Field(default=None, ge=0)
    status: int | None = Field(default=None, ge=0, le=1)


class LabQcRecordCreateRequest(BaseModel):
    qc_name: str = Field(..., min_length=1, max_length=100)
    level: str = Field(..., min_length=1, max_length=30)
    target_value: float
    measured_value: float
    unit: str = Field(default="", max_length=20)
    remark: str = Field(default="", max_length=300)


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
    username: str | None = None
    role: str | None = None
    action: str | None = None
    target: str | None = None
    result: str | None = None
    method: str | None = None
    ip: str | None = None
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


class PaymentIntegrationRequest(BaseModel):
    payment_no: str
    external_payment_id: str | None = None
    status: int  # 1=支付成功，2=支付失败
    amount: float
    failure_reason: str | None = None


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


class NursingAssessmentCreateRequest(BaseModel):
    admission_id: str
    patient_id: int
    adl_score: int = Field(..., ge=0, le=100)
    pressure_ulcer_risk: int = Field(default=0, ge=0, le=3)
    fall_risk: int = Field(default=0, ge=0, le=3)
    consciousness: int = Field(default=0, ge=0, le=3)
    nutrition_risk: int = Field(default=0, ge=0, le=3)
    note: str = Field(default="", max_length=1000)


class NursingAssessmentUpdateRequest(BaseModel):
    assessment_id: str
    adl_score: int | None = Field(default=None, ge=0, le=100)
    pressure_ulcer_risk: int | None = Field(default=None, ge=0, le=3)
    fall_risk: int | None = Field(default=None, ge=0, le=3)
    consciousness: int | None = Field(default=None, ge=0, le=3)
    nutrition_risk: int | None = Field(default=None, ge=0, le=3)
    note: str | None = Field(default=None, max_length=1000)


class NursingPlanCreateRequest(BaseModel):
    admission_id: str
    patient_id: int
    nursing_diagnosis: str = Field(..., min_length=1, max_length=500)
    goal: str = Field(..., min_length=1, max_length=500)
    measures: str = Field(..., min_length=1, max_length=1000)


class NursingPlanUpdateRequest(BaseModel):
    plan_id: str
    nursing_diagnosis: str | None = Field(default=None, min_length=1, max_length=500)
    goal: str | None = Field(default=None, min_length=1, max_length=500)
    measures: str | None = Field(default=None, min_length=1, max_length=1000)
    status: int | None = Field(default=None, ge=0, le=2)


class CriticalCareRecordCreateRequest(BaseModel):
    admission_id: str
    patient_id: int
    record_time: str | None = None
    consciousness: int = Field(default=0, ge=0, le=3)
    gcs_score: int | None = Field(default=None, ge=3, le=15)
    oxygen_support: str = Field(default="", max_length=200)
    blood_pressure: str = Field(default="", max_length=30)
    pulse: int | None = Field(default=None, ge=0, le=300)
    spo2: float | None = Field(default=None, ge=0, le=100)
    urine_output: str = Field(default="", max_length=100)
    note: str = Field(default="", max_length=1000)


class SurgeryNursingRecordCreateRequest(BaseModel):
    schedule_id: str
    patient_id: int
    phase: int = Field(..., ge=0, le=2)
    checklist: str = Field(..., min_length=1, max_length=1000)
    instrument_count: str = Field(default="", max_length=300)
    specimen: str = Field(default="", max_length=500)
    wound_condition: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=1000)
    record_time: str | None = None


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


class MedicalRecordHomeCreateRequest(BaseModel):
    admission_id: str
    admission_diagnosis: str = Field(..., min_length=1, max_length=500)
    discharge_diagnosis: str = Field(default="", max_length=500)
    other_diagnosis: str = Field(default="", max_length=1000)
    operation_summary: str = Field(default="", max_length=1000)
    complication: str = Field(default="", max_length=1000)
    discharge_status: int = Field(default=0, ge=0, le=4)


class MedicalRecordHomeUpdateRequest(BaseModel):
    home_id: str
    admission_diagnosis: str | None = Field(default=None, min_length=1, max_length=500)
    discharge_diagnosis: str | None = Field(default=None, max_length=500)
    other_diagnosis: str | None = Field(default=None, max_length=1000)
    operation_summary: str | None = Field(default=None, max_length=1000)
    complication: str | None = Field(default=None, max_length=1000)
    discharge_status: int | None = Field(default=None, ge=0, le=4)


class MedicalRecordArchiveCreateRequest(BaseModel):
    home_id: str
    location: str = Field(default="", max_length=100)


class MedicalRecordArchiveActionRequest(BaseModel):
    archive_id: str
    reason: str = Field(default="", max_length=300)


class MedicalRecordHomeQualityCheckRequest(BaseModel):
    home_id: str
    check_item: str = Field(..., min_length=1, max_length=100)
    check_result: int = Field(default=0, ge=0, le=2)
    issue: str = Field(default="", max_length=500)
    score: int = Field(default=100, ge=0, le=100)


class Icd10CreateRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="", max_length=100)


class Icd10UpdateRequest(BaseModel):
    id: int
    code: str | None = Field(default=None, min_length=1, max_length=20)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    status: int | None = Field(default=None, ge=0, le=1)


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
