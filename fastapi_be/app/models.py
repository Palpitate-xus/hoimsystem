import uuid

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "hoimsystem_users"

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(20))
    password = Column(String(128))
    user_role = Column(String(20))

    notices = relationship("Notice", back_populates="writer")
    doctors = relationship("Doctor", back_populates="user")
    operation_logs = relationship("OperationLog", back_populates="user")


class Patient(Base):
    __tablename__ = "hoimsystem_patient"

    patient_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(24))
    sex = Column(Integer)
    identity = Column(String(20))
    birthday = Column(Date)
    phone = Column(String(11))
    address = Column(String(100))
    permission = Column(String(10))
    allergy_history = Column(String(200))
    prepaid_balance = Column(Float, default=0)  # 预交金余额

    registrations = relationship("Registration", back_populates="patient")
    appointments = relationship("Appointment", back_populates="patient")
    prescriptions = relationship("Prescription", back_populates="patient")
    medical_records = relationship("MedicalRecord", back_populates="patient")
    vital_signs = relationship("VitalSign", back_populates="patient")
    queue_items = relationship("Queue", back_populates="patient")
    lab_orders = relationship("LabOrder", back_populates="patient")
    follow_ups = relationship("FollowUp", back_populates="patient")
    reviews = relationship("Review", back_populates="patient")


class Doctor(Base):
    __tablename__ = "hoimsystem_doctor"

    doctor_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(24))
    sex = Column(Integer)
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"))
    title = Column(String(10))
    education = Column(String(10))
    phone = Column(String(11))
    permission = Column(String(10))
    user_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))

    department = relationship("Department", back_populates="doctors")
    user = relationship("User", back_populates="doctors")
    schedules = relationship("DoctorSchedule", back_populates="doctor")
    registrations = relationship("Registration", back_populates="doctor")
    appointments = relationship("Appointment", back_populates="doctor")
    prescriptions = relationship("Prescription", back_populates="doctor")
    medical_records = relationship("MedicalRecord", back_populates="doctor")
    queue_items = relationship("Queue", back_populates="doctor")
    lab_orders = relationship("LabOrder", back_populates="doctor")
    follow_ups = relationship("FollowUp", back_populates="doctor")
    reviews = relationship("Review", back_populates="doctor")


class Department(Base):
    __tablename__ = "hoimsystem_department"

    department_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(24))
    phone = Column(String(11))
    location = Column(String(24))
    director = Column(Integer)

    doctors = relationship("Doctor", back_populates="department")


class Timeslot(Base):
    __tablename__ = "hoimsystem_timeslot"

    timeslot_id = Column(Integer, primary_key=True, autoincrement=True)
    time = Column(String(20))


class Notice(Base):
    __tablename__ = "hoimsystem_notice"

    notice_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = Column(String(12))
    content = Column(Text)
    isemergency = Column(Integer)
    towho = Column(String(100))
    sendtime = Column(DateTime)
    expiredtime = Column(DateTime)
    readnum = Column(Integer)
    writer_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))

    writer = relationship("User", back_populates="notices")


class DoctorSchedule(Base):
    __tablename__ = "hoimsystem_doctor_schedule"

    schedule_id = Column(Integer, primary_key=True, autoincrement=True)
    week = Column(String(5))
    time = Column(String(2))
    number = Column(Integer)
    specialist = Column(Integer)
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))

    doctor = relationship("Doctor", back_populates="schedules")


class Registration(Base):
    __tablename__ = "hoimsystem_registration"

    registration_uuid = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    registration_id = Column(Integer)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    specialist = Column(Integer)
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"))
    time = Column(DateTime)
    status = Column(Integer)

    patient = relationship("Patient", back_populates="registrations")
    doctor = relationship("Doctor", back_populates="registrations")
    department = relationship("Department")


class Appointment(Base):
    __tablename__ = "hoimsystem_appointment"

    registration_uuid = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    specialist = Column(Integer)
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"))
    prefer_time = Column(String(5))
    appointment_time = Column(DateTime)
    time = Column(Date)
    status = Column(Integer)

    patient = relationship("Patient", back_populates="appointments")
    doctor = relationship("Doctor", back_populates="appointments")
    department = relationship("Department")


class BreachRecord(Base):
    __tablename__ = "hoimsystem_breach_record"

    breach_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    registration_id = Column(String(36), ForeignKey("hoimsystem_registration.registration_uuid"))
    breach_time = Column(DateTime)
    breach_type = Column(String(20))


class Charge(Base):
    __tablename__ = "hoimsystem_charge"

    charge_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    charge_time = Column(DateTime)
    time = Column(DateTime)
    prescription_id = Column(String(36), ForeignKey("hoimsystem_prescription.prescription_id"))
    amount = Column(Float)
    status = Column(Integer)

    prescription = relationship("Prescription", back_populates="charges")
    invoices = relationship("Invoice", back_populates="charge")


class Prescription(Base):
    __tablename__ = "hoimsystem_prescription"

    prescription_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    status = Column(Integer, default=0)
    create_time = Column(DateTime)
    review_score = Column(Integer, nullable=True)
    review_comment = Column(String(500), nullable=True)
    review_time = Column(DateTime, nullable=True)

    patient = relationship("Patient", back_populates="prescriptions")
    doctor = relationship("Doctor", back_populates="prescriptions")
    charges = relationship("Charge", back_populates="prescription")
    pre_phas = relationship("PrePha", back_populates="prescription", primaryjoin="PrePha.prescription_id == Prescription.prescription_id", foreign_keys="PrePha.prescription_id")


class PrePha(Base):
    __tablename__ = "hoimsystem_pre_pha"

    pre_pha_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    prescription_id = Column(String(50))
    pharmaceutical_id = Column(Integer, ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"))
    number = Column(Integer)

    pharmaceutical = relationship("Pharmaceutical")
    prescription = relationship("Prescription", back_populates="pre_phas", primaryjoin="PrePha.prescription_id == Prescription.prescription_id", foreign_keys="PrePha.prescription_id")


class MedicalRecord(Base):
    __tablename__ = "hoimsystem_medical_record"

    medical_record_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    consultation_time = Column(DateTime)
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    symptom = Column(String(100))
    result = Column(String(100))
    registration_uuid = Column(String(36), ForeignKey("hoimsystem_registration.registration_uuid"))

    doctor = relationship("Doctor", back_populates="medical_records")
    patient = relationship("Patient", back_populates="medical_records")


class Pharmaceutical(Base):
    __tablename__ = "hoimsystem_pharmaceutical"

    pharmaceutical_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(24))
    stock = Column(Integer)
    price = Column(Float)
    expireddate = Column(Date)
    purchasing_time = Column(DateTime)
    supplier = Column(String(24))
    remark = Column(String(100))
    status = Column(Integer, default=0)
    antibiotic_level = Column(Integer, default=0)  # 0=非抗菌药 1=非限制级 2=限制级 3=特殊使用级


# ===== 新增表 =====


class Queue(Base):
    __tablename__ = "hoimsystem_queue"

    queue_id = Column(Integer, primary_key=True, autoincrement=True)
    queue_number = Column(Integer)
    registration_uuid = Column(String(36), ForeignKey("hoimsystem_registration.registration_uuid"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    type = Column(Integer)
    status = Column(Integer, default=0)
    call_time = Column(DateTime)
    create_time = Column(DateTime)

    patient = relationship("Patient", back_populates="queue_items")
    doctor = relationship("Doctor", back_populates="queue_items")


class VitalSign(Base):
    __tablename__ = "hoimsystem_vital_sign"

    vital_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    nurse_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    temperature = Column(Float)
    blood_pressure_systolic = Column(Integer)
    blood_pressure_diastolic = Column(Integer)
    pulse = Column(Integer)
    weight = Column(Float)
    check_time = Column(DateTime)

    patient = relationship("Patient", back_populates="vital_signs")
    nurse = relationship("User")


class LabOrder(Base):
    __tablename__ = "hoimsystem_lab_order"

    lab_order_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    check_type = Column(String(20))
    check_items = Column(String(200))
    urgent = Column(Integer)
    status = Column(Integer, default=0)
    sample_status = Column(Integer, default=0)  # 0=待接收, 1=已接收, 2=已拒收
    create_time = Column(DateTime)

    patient = relationship("Patient", back_populates="lab_orders")
    doctor = relationship("Doctor", back_populates="lab_orders")
    lab_results = relationship("LabResult", back_populates="lab_order")


class LabResult(Base):
    __tablename__ = "hoimsystem_lab_result"

    lab_result_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lab_order_id = Column(String(36), ForeignKey("hoimsystem_lab_order.lab_order_id"))
    sample_id = Column(String(20))
    result = Column(Text)
    abnormal_flag = Column(Integer)
    technician_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    report_time = Column(DateTime)
    audit_status = Column(Integer, default=0)

    lab_order = relationship("LabOrder", back_populates="lab_results")
    technician = relationship("User")


class Invoice(Base):
    __tablename__ = "hoimsystem_invoice"

    invoice_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    charge_id = Column(String(36), ForeignKey("hoimsystem_charge.charge_id"))
    invoice_no = Column(String(24))
    amount = Column(Float)
    tax = Column(Float)
    invoice_time = Column(DateTime)
    status = Column(Integer, default=0)

    charge = relationship("Charge", back_populates="invoices")


class FollowUp(Base):
    __tablename__ = "hoimsystem_follow_up"

    follow_up_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    plan_date = Column(Date)
    content = Column(String(200))
    status = Column(Integer, default=0)
    result = Column(String(200))
    patient_feedback = Column(String(200))
    create_time = Column(DateTime)

    patient = relationship("Patient", back_populates="follow_ups")
    doctor = relationship("Doctor", back_populates="follow_ups")


class Review(Base):
    __tablename__ = "hoimsystem_review"

    review_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    visit_id = Column(String(36))
    score = Column(Integer)
    comment = Column(String(500))
    review_time = Column(DateTime)

    patient = relationship("Patient", back_populates="reviews")
    doctor = relationship("Doctor", back_populates="reviews")


class OperationLog(Base):
    __tablename__ = "hoimsystem_operation_log"

    log_id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    action = Column(String(50))
    target = Column(String(100))
    result = Column(String(20))
    ip = Column(String(40))
    create_time = Column(DateTime)

    user = relationship("User", back_populates="operation_logs")


class Dict(Base):
    __tablename__ = "hoimsystem_dict"

    dict_id = Column(Integer, primary_key=True, autoincrement=True)
    dict_type = Column(String(20))
    dict_code = Column(String(20))
    dict_value = Column(String(50))
    sort_order = Column(Integer)
    status = Column(Integer, default=0)


class Config(Base):
    __tablename__ = "hoimsystem_config"

    config_id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(50))
    config_value = Column(String(200))
    description = Column(String(200))


class Attendance(Base):
    __tablename__ = "hoimsystem_attendance"

    attendance_id = Column(Integer, primary_key=True, autoincrement=True)
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    date = Column(Date)
    check_in_time = Column(DateTime)
    check_out_time = Column(DateTime)
    status = Column(Integer, default=0)  # 0=正常, 1=迟到, 2=早退, 3=缺勤

    doctor = relationship("Doctor")


class PatrolRecord(Base):
    __tablename__ = "hoimsystem_patrol_record"

    patrol_id = Column(Integer, primary_key=True, autoincrement=True)
    nurse_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    content = Column(String(500))
    status = Column(Integer, default=0)  # 0=正常, 1=需关注, 2=急诊绿色通道
    create_time = Column(DateTime)

    nurse = relationship("User")
    patient = relationship("Patient")


class Message(Base):
    __tablename__ = "hoimsystem_message"

    message_id = Column(Integer, primary_key=True, autoincrement=True)
    recipient_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    title = Column(String(100))
    content = Column(String(500))
    msg_type = Column(String(20))  # sms, app, email
    is_read = Column(Integer, default=0)
    create_time = Column(DateTime)

    recipient = relationship("User")


class Payment(Base):
    __tablename__ = "hoimsystem_payment"

    payment_id = Column(Integer, primary_key=True, autoincrement=True)
    payment_no = Column(String(32), unique=True)
    charge_id = Column(String(36), ForeignKey("hoimsystem_charge.charge_id"))
    channel = Column(String(10))  # wechat, alipay, cash
    amount = Column(Float)
    status = Column(Integer, default=0)  # 0=待支付, 1=支付成功, 2=支付失败, 3=已退款
    qr_code_data = Column(String(200))
    paid_time = Column(DateTime, nullable=True)
    create_time = Column(DateTime)

    charge = relationship("Charge")


class TriageRecord(Base):
    __tablename__ = "hoimsystem_triage_record"

    triage_record_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    nurse_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    symptom = Column(String(500))
    level = Column(Integer, default=3)  # 1=危急(红) 2=急症(橙) 3=普通(黄) 4=非急(绿)
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"), nullable=True)
    temperature = Column(Float, nullable=True)
    blood_pressure_systolic = Column(Integer, nullable=True)
    blood_pressure_diastolic = Column(Integer, nullable=True)
    pulse = Column(Integer, nullable=True)
    status = Column(Integer, default=0)  # 0=待就诊 1=已就诊 2=已转诊 3=已取消
    note = Column(String(200), nullable=True)
    create_time = Column(DateTime)

    patient = relationship("Patient")
    nurse = relationship("User")
    department = relationship("Department")


class Consumable(Base):
    __tablename__ = "hoimsystem_consumable"

    consumable_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50))
    category = Column(String(20))  # 耗材分类：注射类、敷料类、检验类、手术类等
    stock = Column(Integer, default=0)
    unit = Column(String(10))  # 单位：个、包、支、套
    price = Column(Float)
    supplier = Column(String(50))
    remark = Column(String(200))
    status = Column(Integer, default=0)  # 0=正常 1=停用
    create_time = Column(DateTime)


class PurchaseOrder(Base):
    __tablename__ = "hoimsystem_purchase_order"

    purchase_id = Column(Integer, primary_key=True, autoincrement=True)
    order_no = Column(String(32), unique=True)
    supplier = Column(String(50))
    total_amount = Column(Float, default=0)
    status = Column(Integer, default=0)  # 0=待审批 1=已审批 2=已入库 3=已取消
    create_by = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    create_time = Column(DateTime)
    approve_time = Column(DateTime, nullable=True)
    storage_time = Column(DateTime, nullable=True)

    creator = relationship("User")
    items = relationship("PurchaseOrderItem", back_populates="order", cascade="all, delete-orphan")


class PurchaseOrderItem(Base):
    __tablename__ = "hoimsystem_purchase_order_item"

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    purchase_id = Column(Integer, ForeignKey("hoimsystem_purchase_order.purchase_id"))
    item_type = Column(String(10))  # drug=药品 consumable=耗材
    item_id_ref = Column(Integer)  # 药品ID或耗材ID
    item_name = Column(String(50))
    quantity = Column(Integer)
    unit_price = Column(Float)
    total_price = Column(Float)

    order = relationship("PurchaseOrder", back_populates="items")


class AdverseReaction(Base):
    __tablename__ = "hoimsystem_adverse_reaction"

    reaction_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    pharmaceutical_id = Column(Integer, ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"))
    symptom = Column(String(500))
    severity = Column(Integer, default=1)  # 1=轻度 2=中度 3=重度
    report_time = Column(DateTime)
    reporter_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    status = Column(Integer, default=0)  # 0=待审核 1=已确认 2=已处理
    note = Column(String(200))

    patient = relationship("Patient")
    pharmaceutical = relationship("Pharmaceutical")
    reporter = relationship("User")


class AdverseEvent(Base):
    __tablename__ = "hoimsystem_adverse_event"

    event_id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(50))  # 用药错误/跌倒/压疮/其他
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"), nullable=True)
    description = Column(String(500))
    severity = Column(Integer, default=1)  # 1=轻度 2=中度 3=重度
    reporter_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    report_time = Column(DateTime)
    status = Column(Integer, default=0)  # 0=待处理 1=处理中 2=已闭环
    handle_result = Column(String(500))

    patient = relationship("Patient")
    reporter = relationship("User")


class Referral(Base):
    __tablename__ = "hoimsystem_referral"

    referral_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    from_department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"))
    to_department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"))
    referral_type = Column(String(10))  # up=上转 down=下转
    reason = Column(String(200))
    status = Column(Integer, default=0)  # 0=待接收 1=已接收 2=已退回
    create_time = Column(DateTime)

    patient = relationship("Patient")
    from_department = relationship("Department", foreign_keys=[from_department_id])
    to_department = relationship("Department", foreign_keys=[to_department_id])


class MdtCase(Base):
    __tablename__ = "hoimsystem_mdt_case"

    mdt_id = Column(Integer, primary_key=True, autoincrement=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    diagnosis = Column(String(200))
    department_ids = Column(String(100))  # 逗号分隔的科室ID
    status = Column(Integer, default=0)  # 0=待会诊 1=会诊中 2=已完成
    result = Column(String(500))
    create_time = Column(DateTime)

    patient = relationship("Patient")


class ClinicalPathway(Base):
    __tablename__ = "hoimsystem_clinical_pathway"

    pathway_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100))
    disease_code = Column(String(20))
    disease_name = Column(String(50))
    steps = Column(String(1000))  # JSON格式的步骤
    expected_days = Column(Integer)
    status = Column(Integer, default=0)  # 0=启用 1=停用
    create_time = Column(DateTime)


# ===== 结构化电子病历模块 =====


class MedicalRecordTemplate(Base):
    __tablename__ = "hoimsystem_medical_record_template"

    template_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50))
    category = Column(String(20))  # admission=入院记录 progress=病程记录 discharge=出院记录
    content = Column(Text)  # JSON格式模板内容
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"), nullable=True)
    is_default = Column(Integer, default=0)  # 0=否 1=是
    status = Column(Integer, default=0)  # 0=启用 1=停用
    create_time = Column(DateTime)

    department = relationship("Department")


class StructuredMedicalRecord(Base):
    __tablename__ = "hoimsystem_structured_medical_record"

    record_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"), nullable=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    record_type = Column(Integer, default=0)  # 0=入院记录 1=首次病程 2=日常病程 3=出院记录

    # 主诉与病史
    chief_complaint = Column(String(300), nullable=True)  # 主诉
    present_illness = Column(Text, nullable=True)  # 现病史
    past_history = Column(String(500), nullable=True)  # 既往史
    personal_history = Column(String(300), nullable=True)  # 个人史
    family_history = Column(String(300), nullable=True)  # 家族史

    # 体格检查
    physical_exam = Column(Text, nullable=True)  # 体格检查（JSON）

    # 辅助检查
    auxiliary_exam = Column(Text, nullable=True)  # 辅助检查

    # 诊断与计划
    diagnosis = Column(String(300), nullable=True)  # 初步诊断
    treatment_plan = Column(Text, nullable=True)  # 诊疗计划

    # 病历状态
    status = Column(Integer, default=0)  # 0=草稿 1=已完成 2=已归档
    sign_time = Column(DateTime, nullable=True)  # 医生签名时间
    create_time = Column(DateTime)
    update_time = Column(DateTime, nullable=True)

    patient = relationship("Patient")
    doctor = relationship("Doctor")
    admission = relationship("Admission")


class ProgressNote(Base):
    __tablename__ = "hoimsystem_progress_note"

    note_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    note_date = Column(Date)  # 病程日期
    content = Column(Text)  # 病程内容
    record_time = Column(DateTime)
    create_time = Column(DateTime)

    patient = relationship("Patient")
    doctor = relationship("Doctor")
    admission = relationship("Admission")


class WardRound(Base):
    __tablename__ = "hoimsystem_ward_round"

    round_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))  # 查房医生
    round_type = Column(Integer, default=2)  # 0=主任医师 1=副主任医师 2=主治医师
    content = Column(Text)
    round_time = Column(DateTime)
    create_time = Column(DateTime)

    patient = relationship("Patient")
    doctor = relationship("Doctor")
    admission = relationship("Admission")


class MedicalRecordQuality(Base):
    __tablename__ = "hoimsystem_medical_record_quality"

    quality_id = Column(Integer, primary_key=True, autoincrement=True)
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"))
    record_id = Column(String(36), ForeignKey("hoimsystem_structured_medical_record.record_id"))
    check_item = Column(String(50))  # 检查项：时限/完整性/规范
    check_result = Column(Integer, default=0)  # 0=通过 1=警告 2=错误
    issue = Column(String(200), nullable=True)  # 问题描述
    score = Column(Integer, default=100)  # 得分
    checker_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    check_time = Column(DateTime)

    checker = relationship("User")


# ===== 手术麻醉管理模块 =====


class SurgeryApplication(Base):
    __tablename__ = "hoimsystem_surgery_application"

    application_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    surgery_name = Column(String(100))  # 手术名称
    surgery_code = Column(String(20), nullable=True)  # 手术编码
    surgery_level = Column(Integer, default=1)  # 1=一级 2=二级 3=三级 4=四级
    anesthesia_type = Column(String(20), default="局部麻醉")  # 全麻/椎管内/局部/神经阻滞
    scheduled_date = Column(Date, nullable=True)  # 计划手术日期
    preop_diagnosis = Column(String(200), nullable=True)  # 术前诊断
    surgery_indication = Column(String(500), nullable=True)  # 手术指征
    contraindication = Column(String(300), nullable=True)  # 禁忌症
    status = Column(Integer, default=0)  # 0=待审批 1=已批准 2=已排台 3=已完成 4=已取消
    approver_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)
    approve_time = Column(DateTime, nullable=True)
    create_time = Column(DateTime)

    patient = relationship("Patient")
    doctor = relationship("Doctor")
    approver = relationship("User")


class SurgerySchedule(Base):
    __tablename__ = "hoimsystem_surgery_schedule"

    schedule_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    application_id = Column(String(36), ForeignKey("hoimsystem_surgery_application.application_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    operating_room = Column(String(20))  # 手术室号
    surgery_date = Column(Date)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    surgeon_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))  # 主刀医生
    assistant_ids = Column(String(100), nullable=True)  # 助手医生ID，逗号分隔
    anesthesiologist_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"), nullable=True)  # 麻醉医生
    scrub_nurse_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)  # 器械护士
    circulating_nurse_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"), nullable=True)  # 巡回护士
    status = Column(Integer, default=0)  # 0=待手术 1=手术中 2=已完成 3=已取消
    create_time = Column(DateTime)

    application = relationship("SurgeryApplication")
    patient = relationship("Patient")
    surgeon = relationship("Doctor", foreign_keys=[surgeon_id])
    anesthesiologist = relationship("Doctor", foreign_keys=[anesthesiologist_id])


class AnesthesiaRecord(Base):
    __tablename__ = "hoimsystem_anesthesia_record"

    record_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    schedule_id = Column(String(36), ForeignKey("hoimsystem_surgery_schedule.schedule_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    anesthesiologist_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))

    # 入室情况
    enter_time = Column(DateTime, nullable=True)
    consciousness = Column(String(10), nullable=True)
    preop_bp = Column(String(20), nullable=True)  # 术前血压
    preop_hr = Column(Integer, nullable=True)  # 术前心率
    preop_spo2 = Column(Float, nullable=True)

    # 麻醉过程
    anesthesia_method = Column(String(50), nullable=True)
    induction_drugs = Column(String(200), nullable=True)  # 诱导用药
    maintenance_drugs = Column(String(200), nullable=True)  # 维持用药

    # 术中监测
    intraop_bp = Column(String(100), nullable=True)  # 术中血压变化
    intraop_hr = Column(String(100), nullable=True)
    blood_loss = Column(Float, default=0)  # 出血量(ml)
    urine_output = Column(Float, default=0)  # 尿量(ml)
    fluid_input = Column(Float, default=0)  # 输液量(ml)

    # 出室情况
    extubation_time = Column(DateTime, nullable=True)
    leave_time = Column(DateTime, nullable=True)
    postop_consciousness = Column(String(10), nullable=True)
    complications = Column(String(200), nullable=True)  # 并发症

    create_time = Column(DateTime)

    schedule = relationship("SurgerySchedule")
    patient = relationship("Patient")
    anesthesiologist = relationship("Doctor")


# ===== 住院管理模块 =====


class Ward(Base):
    __tablename__ = "hoimsystem_ward"

    ward_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50))  # 病区名称：内科一病区、外科二病区
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"))
    bed_count = Column(Integer, default=0)
    nurse_station_phone = Column(String(11), nullable=True)
    location = Column(String(50), nullable=True)
    status = Column(Integer, default=0)  # 0=启用 1=停用

    department = relationship("Department")
    beds = relationship("Bed", back_populates="ward", cascade="all, delete-orphan")


class Bed(Base):
    __tablename__ = "hoimsystem_bed"

    bed_id = Column(Integer, primary_key=True, autoincrement=True)
    ward_id = Column(Integer, ForeignKey("hoimsystem_ward.ward_id"))
    bed_no = Column(String(10))  # 床位号：01、02
    room_no = Column(String(10))  # 房间号：101、102
    bed_type = Column(String(10), default="普通")  # 普通/监护/抢救/单人/双人
    price_per_day = Column(Float, default=0)  # 每日床位费
    status = Column(Integer, default=0)  # 0=空闲 1=占用 2=禁用 3=预订

    ward = relationship("Ward", back_populates="beds")


class Admission(Base):
    __tablename__ = "hoimsystem_admission"

    admission_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    admission_no = Column(String(20), unique=True)  # 住院号：ZY20260511001
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    department_id = Column(Integer, ForeignKey("hoimsystem_department.department_id"))
    ward_id = Column(Integer, ForeignKey("hoimsystem_ward.ward_id"))
    bed_id = Column(Integer, ForeignKey("hoimsystem_bed.bed_id"))
    admission_type = Column(Integer, default=0)  # 0=门诊入院 1=急诊入院 2=转诊入院 3=预约入院
    admission_time = Column(DateTime)
    admission_diagnosis = Column(String(200), nullable=True)  # 入院诊断
    chief_complaint = Column(String(200), nullable=True)  # 主诉
    present_illness = Column(String(500), nullable=True)  # 现病史
    past_history = Column(String(300), nullable=True)  # 既往史
    deposit_amount = Column(Float, default=0)  # 入院押金
    discharge_time = Column(DateTime, nullable=True)
    discharge_diagnosis = Column(String(200), nullable=True)
    status = Column(Integer, default=0)  # 0=待入院 1=在院 2=已出院 3=已退院
    create_time = Column(DateTime)

    patient = relationship("Patient")
    doctor = relationship("Doctor")
    department = relationship("Department")
    ward = relationship("Ward")
    bed = relationship("Bed")
    orders = relationship("InpatientOrder", back_populates="admission", cascade="all, delete-orphan")
    nursing_records = relationship("NursingRecord", back_populates="admission", cascade="all, delete-orphan")
    temperature_records = relationship("TemperatureRecord", back_populates="admission", cascade="all, delete-orphan")
    charges = relationship("InpatientCharge", back_populates="admission", cascade="all, delete-orphan")
    discharge_summary = relationship("DischargeSummary", back_populates="admission", uselist=False)


class InpatientOrder(Base):
    __tablename__ = "hoimsystem_inpatient_order"

    order_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    order_type = Column(Integer, default=0)  # 0=长期医嘱 1=临时医嘱
    category = Column(String(10))  # drug=药品 treatment=治疗 exam=检查 diet=饮食 nursing=护理 other=其他
    start_time = Column(DateTime)
    stop_time = Column(DateTime, nullable=True)
    status = Column(Integer, default=0)  # 0=新开 1=已审核 2=执行中 3=已停止 4=已撤销
    priority = Column(Integer, default=0)  # 0=常规 1=紧急 2=抢救
    note = Column(String(200), nullable=True)
    create_time = Column(DateTime)

    admission = relationship("Admission", back_populates="orders")
    patient = relationship("Patient")
    doctor = relationship("Doctor")
    items = relationship("InpatientOrderItem", back_populates="order", cascade="all, delete-orphan")
    executions = relationship("OrderExecution", back_populates="order", cascade="all, delete-orphan")


class InpatientOrderItem(Base):
    __tablename__ = "hoimsystem_inpatient_order_item"

    item_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    order_id = Column(String(36), ForeignKey("hoimsystem_inpatient_order.order_id"))
    item_name = Column(String(50))  # 药品名或项目名称
    item_type = Column(String(10))  # drug=药品 consumable=耗材 service=服务项目
    item_id_ref = Column(Integer, nullable=True)  # 关联药品ID或耗材ID
    dose = Column(String(20), nullable=True)  # 剂量：如 "10mg"
    unit = Column(String(10), nullable=True)  # 单位
    frequency = Column(String(20), nullable=True)  # 频次：如 "qd"(每日一次)、"bid"(每日两次)
    route = Column(String(20), nullable=True)  # 给药途径：口服、静脉滴注、皮下注射
    days = Column(Integer, default=1)  # 用药天数
    quantity = Column(Integer, default=1)  # 数量
    unit_price = Column(Float, default=0)  # 单价
    total_price = Column(Float, default=0)  # 总价
    note = Column(String(100), nullable=True)

    order = relationship("InpatientOrder", back_populates="items")


class OrderExecution(Base):
    __tablename__ = "hoimsystem_order_execution"

    execution_id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(36), ForeignKey("hoimsystem_inpatient_order.order_id"))
    nurse_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    planned_time = Column(DateTime)  # 计划执行时间
    execution_time = Column(DateTime, nullable=True)  # 实际执行时间
    status = Column(Integer, default=0)  # 0=待执行 1=已执行 2=已跳过 3=已停止
    note = Column(String(200), nullable=True)

    order = relationship("InpatientOrder", back_populates="executions")
    nurse = relationship("User")


class NursingRecord(Base):
    __tablename__ = "hoimsystem_nursing_record"

    record_id = Column(Integer, primary_key=True, autoincrement=True)
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    nurse_id = Column(Integer, ForeignKey("hoimsystem_users.user_id"))
    record_time = Column(DateTime)
    consciousness = Column(String(10), nullable=True)  # 意识：清醒、嗜睡、昏迷
    temperature = Column(Float, nullable=True)
    pulse = Column(Integer, nullable=True)
    respiration = Column(Integer, nullable=True)
    blood_pressure = Column(String(20), nullable=True)
    spo2 = Column(Float, nullable=True)  # 血氧饱和度
    intake = Column(String(50), nullable=True)  # 入量
    output = Column(String(50), nullable=True)  # 出量
    skin_condition = Column(String(50), nullable=True)  # 皮肤情况
    drainage = Column(String(50), nullable=True)  # 引流情况
    note = Column(String(500), nullable=True)
    create_time = Column(DateTime)

    admission = relationship("Admission", back_populates="nursing_records")
    patient = relationship("Patient")
    nurse = relationship("User")


class TemperatureRecord(Base):
    __tablename__ = "hoimsystem_temperature_record"

    temp_id = Column(Integer, primary_key=True, autoincrement=True)
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    record_date = Column(Date)
    time_point = Column(String(5), default="06:00")  # 时间点：02:00 06:00 10:00 14:00 18:00 22:00
    temperature = Column(Float, nullable=True)
    pulse = Column(Integer, nullable=True)
    respiration = Column(Integer, nullable=True)
    blood_pressure = Column(String(20), nullable=True)
    stool_count = Column(Integer, nullable=True)  # 大便次数
    weight = Column(Float, nullable=True)
    intake = Column(Float, nullable=True)  # 入量(ml)
    output = Column(Float, nullable=True)  # 出量(ml)
    note = Column(String(100), nullable=True)

    admission = relationship("Admission", back_populates="temperature_records")
    patient = relationship("Patient")


class InpatientCharge(Base):
    __tablename__ = "hoimsystem_inpatient_charge"

    charge_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    item_name = Column(String(50))  # 项目名称
    item_type = Column(String(10))  # drug=药品 consumable=耗材 bed=床位 service=服务 exam=检查
    quantity = Column(Float, default=1)
    unit_price = Column(Float, default=0)
    total_amount = Column(Float, default=0)
    charge_date = Column(Date)  # 费用所属日期
    related_order_id = Column(String(36), nullable=True)  # 关联医嘱ID
    status = Column(Integer, default=0)  # 0=未结算 1=已结算 2=已退费
    create_time = Column(DateTime)

    admission = relationship("Admission", back_populates="charges")
    patient = relationship("Patient")


class DischargeSummary(Base):
    __tablename__ = "hoimsystem_discharge_summary"

    summary_id = Column(Integer, primary_key=True, autoincrement=True)
    admission_id = Column(String(36), ForeignKey("hoimsystem_admission.admission_id"), unique=True)
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"))
    discharge_time = Column(DateTime)
    hospital_days = Column(Integer, default=0)  # 住院天数
    admission_diagnosis = Column(String(200), nullable=True)
    discharge_diagnosis = Column(String(200), nullable=True)
    treatment_summary = Column(String(1000), nullable=True)  # 诊疗经过
    discharge_status = Column(Integer, default=0)  # 0=治愈 1=好转 2=未愈 3=死亡 4=转院
    discharge_instruction = Column(String(500), nullable=True)  # 出院医嘱
    follow_up_plan = Column(String(200), nullable=True)  # 随访计划
    note = Column(String(300), nullable=True)
    create_time = Column(DateTime)

    admission = relationship("Admission", back_populates="discharge_summary")
    patient = relationship("Patient")


# ===== 体检系统模块 =====


class ExamPackage(Base):
    __tablename__ = "hoimsystem_exam_package"

    package_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50))
    category = Column(String(20))  # general=常规入职=入职 premarital=婚检 elderly=老年
    price = Column(Float, default=0)
    items = Column(String(500))  # 包含项目ID，逗号分隔
    description = Column(String(200), nullable=True)
    status = Column(Integer, default=0)  # 0=启用 1=停用
    create_time = Column(DateTime)


class ExamItem(Base):
    __tablename__ = "hoimsystem_exam_item"

    item_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50))  # 项目名称
    category = Column(String(20))  # blood=血常规 urine=尿常规 ecg=心电图 ultrasound=超声 xray=放射
    unit = Column(String(10), nullable=True)  # 单位
    reference_range = Column(String(50), nullable=True)  # 参考范围
    price = Column(Float, default=0)
    status = Column(Integer, default=0)
    create_time = Column(DateTime)


class ExamAppointment(Base):
    __tablename__ = "hoimsystem_exam_appointment"

    appointment_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    package_id = Column(Integer, ForeignKey("hoimsystem_exam_package.package_id"))
    exam_date = Column(Date)
    status = Column(Integer, default=0)  # 0=待体检 1=已报到 2=进行中 3=已完成 4=已取消
    note = Column(String(200), nullable=True)
    create_time = Column(DateTime)

    patient = relationship("Patient")
    package = relationship("ExamPackage")


class ExamRecord(Base):
    __tablename__ = "hoimsystem_exam_record"

    record_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    appointment_id = Column(String(36), ForeignKey("hoimsystem_exam_appointment.appointment_id"))
    patient_id = Column(Integer, ForeignKey("hoimsystem_patient.patient_id"))
    package_id = Column(Integer, ForeignKey("hoimsystem_exam_package.package_id"))
    doctor_id = Column(Integer, ForeignKey("hoimsystem_doctor.doctor_id"), nullable=True)
    overall_result = Column(String(20), nullable=True)  # 正常/异常/复查
    overall_advice = Column(String(500), nullable=True)  # 总检建议
    exam_time = Column(DateTime, nullable=True)
    report_time = Column(DateTime, nullable=True)
    status = Column(Integer, default=0)  # 0=待录入 1=录入中 2=待总检 3=已完成
    create_time = Column(DateTime)

    patient = relationship("Patient")
    package = relationship("ExamPackage")
    doctor = relationship("Doctor")


class ExamResult(Base):
    __tablename__ = "hoimsystem_exam_result"

    result_id = Column(Integer, primary_key=True, autoincrement=True)
    record_id = Column(String(36), ForeignKey("hoimsystem_exam_record.record_id"))
    item_id = Column(Integer, ForeignKey("hoimsystem_exam_item.item_id"))
    item_name = Column(String(50))
    result_value = Column(String(100), nullable=True)  # 检查结果值
    unit = Column(String(10), nullable=True)
    reference_range = Column(String(50), nullable=True)
    abnormal_flag = Column(Integer, default=0)  # 0=正常 1=偏高 2=偏低 3=异常
    note = Column(String(200), nullable=True)
    create_time = Column(DateTime)

    record = relationship("ExamRecord")
    item = relationship("ExamItem")
