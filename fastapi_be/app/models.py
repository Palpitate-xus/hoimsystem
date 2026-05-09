import uuid
from sqlalchemy import Column, Integer, String, Float, DateTime, Date, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base


class User(Base):
    __tablename__ = "hoimsystem_users"

    user_id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(20))
    password = Column(String(128))
    user_role = Column(String(10))

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

    patient = relationship("Patient", back_populates="prescriptions")
    doctor = relationship("Doctor", back_populates="prescriptions")
    charges = relationship("Charge", back_populates="prescription")
    pre_phas = relationship("PrePha", back_populates="prescription",
                            primaryjoin="PrePha.prescription_id == Prescription.prescription_id",
                            foreign_keys="PrePha.prescription_id")


class PrePha(Base):
    __tablename__ = "hoimsystem_pre_pha"

    pre_pha_id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    prescription_id = Column(String(50))
    pharmaceutical_id = Column(Integer, ForeignKey("hoimsystem_pharmaceutical.pharmaceutical_id"))
    number = Column(Integer)

    pharmaceutical = relationship("Pharmaceutical")
    prescription = relationship("Prescription", back_populates="pre_phas",
                                primaryjoin="PrePha.prescription_id == Prescription.prescription_id",
                                foreign_keys="PrePha.prescription_id")


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
