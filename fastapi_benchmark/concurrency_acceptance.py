"""Verify transaction invariants through a running, isolated PostgreSQL API.

Run against the disposable benchmark stack, never a hospital database. Each run
creates unique synthetic accounts and verifies their API login before exercising
business writes. The benchmark initializer resets these records between runs.
"""

import argparse
import datetime as dt
import json
import secrets
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import requests
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from benchmark_database import (
    BACKEND_DIR,
    configure_application_environment,
    require_concurrency_safe_database,
    validate_benchmark_url,
)


def validate_targets(host: str, database_url: str) -> str:
    """Keep destructive acceptance fixtures on explicit local test targets."""
    api = urlsplit(host)
    if (
        api.scheme not in {"http", "https"}
        or api.hostname not in {"127.0.0.1", "localhost", "::1"}
        or api.username or api.password or api.query or api.fragment
        or api.path not in {"", "/"}
        or api.port is None
    ):
        raise ValueError("--host must be a loopback HTTP(S) origin with an explicit port")
    url = validate_benchmark_url(database_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("concurrency acceptance requires the local dedicated PostgreSQL benchmark database")
    return host.rstrip("/")


class Acceptance:
    def __init__(self, host, engine, models, hash_password, concurrency):
        self.host, self.engine, self.m = host, engine, models
        self.concurrency = concurrency
        self.tag = uuid4().hex[:10]
        self.tokens = {}
        self.results = []
        password = secrets.token_urlsafe(24)
        owner_name = f"cv-p-{self.tag}"
        admin_name = f"cv-a-{self.tag}"
        with Session(engine) as db:
            doctor = db.query(models.Doctor).order_by(models.Doctor.doctor_id).first()
            if doctor is None:
                raise RuntimeError("initialize benchmark data before concurrency acceptance")
            self.doctor_id, self.department_id = doctor.doctor_id, doctor.department_id
            db.add_all([
                models.User(username=admin_name, password=hash_password(password), user_role="admin"),
                models.User(username=owner_name, password=hash_password(password), user_role="patient"),
            ])
            owner = models.Patient(name=f"并发验收{self.tag}", identity=owner_name, sex=1, permission="allow", allergy_history="")
            db.add(owner)
            db.flush()
            members = [models.Patient(name=f"并发验收{i}", identity=f"cv-{self.tag}-{i}", sex=i % 2, permission="family", allergy_history="") for i in range(concurrency)]
            db.add_all(members)
            db.flush()
            db.add_all([models.FamilyMember(owner_patient_id=owner.patient_id, member_patient_id=p.patient_id, relation="其他", create_time=dt.datetime.now(), update_time=dt.datetime.now()) for p in members])
            self.owner_id = owner.patient_id
            db.flush()
            self.admin_id = db.query(models.User).filter_by(username=admin_name).one().user_id
            self.patient_ids = [p.patient_id for p in members]
            db.commit()
        # Successful logins for newly generated accounts bind the HTTP server to
        # the exact fixture database before any business endpoint is called.
        for role, username in [("admin", admin_name), ("patient", owner_name)]:
            with requests.Session() as client:
                client.trust_env = False
                response = client.post(f"{host}/api/login", json={"username": username, "password": password}, timeout=30)
                body = response.json()
                if response.status_code != 200 or body.get("code") != 200:
                    raise RuntimeError("API does not authenticate the newly seeded benchmark identity")
                self.tokens[role] = body["data"]["accesstoken"]

    def post(self, path, payload, role="admin"):
        with requests.Session() as client:
            client.trust_env = False
            response = client.post(f"{self.host}{path}", headers={"accesstoken": self.tokens[role]}, json=payload, timeout=30)
            try:
                body = response.json()
            except ValueError:
                body = {}
            return {"http_status": response.status_code, "code": body.get("code"), "body": body}

    def parallel(self, path, payloads, role="admin"):
        barrier = threading.Barrier(len(payloads))

        def send(payload):
            barrier.wait(timeout=30)
            return self.post(path, payload, role)

        with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
            return list(pool.map(send, payloads))

    def record(self, name, responses, expected, observed):
        successes = sum(r["http_status"] == 200 and r["code"] == 200 for r in responses)
        observed = {"successful_requests": successes, **observed}
        statuses = dict(Counter(str(r["http_status"]) for r in responses))
        passed = expected == observed and not any(r["http_status"] >= 500 for r in responses)
        result = {"name": name, "passed": passed, "requests": len(responses), "http_statuses": statuses, "expected": expected, "observed": observed}
        self.results.append(result)
        print(json.dumps(result, ensure_ascii=False), flush=True)

    def schedule(self, stock, offset):
        day = dt.date.today() + dt.timedelta(days=60 + offset)
        with Session(self.engine) as db:
            row = self.m.DoctorSchedule(doctor_id=self.doctor_id, week="星期" + "一二三四五六日"[day.weekday()], time="01", specialist=1, number=stock)
            db.add(row)
            db.commit()
            return row.schedule_id, day.isoformat()

    def appointment(self, schedule_id, date, patient_id):
        return {"id": schedule_id, "date": date, "doctor_id": self.doctor_id, "department_id": self.department_id, "time": "01", "specialist": 1, "patient_id": patient_id}

    def booking(self):
        sid, day = self.schedule(1, 1)
        responses = self.parallel("/api/appointmentManagement/create", [self.appointment(sid, day, p) for p in self.patient_ids], "patient")
        with Session(self.engine) as db:
            count = db.query(self.m.Appointment).filter_by(schedule_id=sid, status=0).count()
            stock = db.get(self.m.DoctorSchedule, sid).number
        self.record("last_slot_not_oversold", responses, {"successful_requests": 1, "appointments": 1, "remaining_slots": 0}, {"appointments": count, "remaining_slots": stock})

        sid, day = self.schedule(self.concurrency, 2)
        payload = self.appointment(sid, day, self.owner_id)
        responses = self.parallel("/api/appointmentManagement/create", [payload] * self.concurrency, "patient")
        with Session(self.engine) as db:
            count = db.query(self.m.Appointment).filter_by(schedule_id=sid, status=0).count()
            stock = db.get(self.m.DoctorSchedule, sid).number
        self.record("duplicate_booking_once", responses, {"successful_requests": 1, "appointments": 1, "remaining_slots": self.concurrency - 1}, {"appointments": count, "remaining_slots": stock})

        sid, day = self.schedule(self.concurrency, 3)
        for patient_id in self.patient_ids:
            ack = self.post("/api/appointmentManagement/create", self.appointment(sid, day, patient_id), "patient")
            if ack["code"] != 200:
                raise RuntimeError("cannot prepare independent cancellation fixtures")
        with Session(self.engine) as db:
            ids = [row.registration_uuid for row in db.query(self.m.Appointment).filter_by(schedule_id=sid, status=0)]
        responses = self.parallel("/api/appointmentManagement/cancel", [{"uuid": key} for key in ids], "patient")
        with Session(self.engine) as db:
            stock = db.get(self.m.DoctorSchedule, sid).number
            cancelled = db.query(self.m.Appointment).filter_by(schedule_id=sid, status=2).count()
        self.record("parallel_cancellations_restore_every_slot", responses, {"successful_requests": self.concurrency, "cancelled": self.concurrency, "remaining_slots": self.concurrency}, {"cancelled": cancelled, "remaining_slots": stock})

    def registrations(self):
        cases = [("patient_registration_duplicate_once", self.owner_id, False), ("window_registration_duplicate_once", self.patient_ids[0], True)]
        for name, patient_id, window in cases:
            sid, _ = self.schedule(self.concurrency, 10)
            if window:
                with Session(self.engine) as db:
                    identity = db.get(self.m.Patient, patient_id).identity
                path, role = "/api/windowRegistration/create", "admin"
                payload = {"identity": identity, "schedule_id": sid, "doctor_id": self.doctor_id, "department_id": self.department_id, "specialist": 1}
            else:
                path, role = "/api/registrationManagement/create", "patient"
                payload = {"id": sid, "doctor_id": self.doctor_id, "department_id": self.department_id, "specialist": 1, "patient_id": patient_id}
            responses = self.parallel(path, [payload] * self.concurrency, role)
            with Session(self.engine) as db:
                count = db.query(self.m.Registration).filter_by(schedule_id=sid, status=0).count()
                stock = db.get(self.m.DoctorSchedule, sid).number
            self.record(name, responses, {"successful_requests": 1, "registrations": 1, "remaining_slots": self.concurrency - 1}, {"registrations": count, "remaining_slots": stock})

    def new_charge(self):
        with Session(self.engine) as db:
            pre = self.m.Prescription(patient_id=self.owner_id, doctor_id=self.doctor_id, status=1, create_time=dt.datetime.now())
            db.add(pre)
            db.flush()
            charge = self.m.Charge(prescription_id=pre.prescription_id, amount="10.20", status=0, charge_type="prescription", charge_time=dt.datetime.now())
            db.add(charge)
            db.commit()
            return charge.charge_id

    def payments(self):
        charge_id = self.new_charge()
        payload = {"charge_id": charge_id, "channel": "wechat", "amount": 10.2}
        responses = self.parallel("/api/payment/create", [payload] * self.concurrency, "patient")
        with Session(self.engine) as db:
            pending = db.query(self.m.Payment).filter_by(charge_id=charge_id, status=0).count()
        self.record("one_pending_payment_per_charge", responses, {"successful_requests": 1, "pending_payments": 1}, {"pending_payments": pending})

        charge_id = self.new_charge()
        responses = self.parallel("/api/chargeManagement/charge", [{"id": charge_id}] * self.concurrency)
        with Session(self.engine) as db:
            payments = db.query(self.m.Payment).filter_by(charge_id=charge_id, status=1).count()
            state = db.get(self.m.Charge, charge_id).status
        self.record("cash_charge_paid_once", responses, {"successful_requests": 1, "payments": 1, "charge_status": 1}, {"payments": payments, "charge_status": state})

        responses = self.parallel("/api/chargeManagement/refund", [{"charge_id": charge_id, "reason": "并发验收"}] * self.concurrency)
        with Session(self.engine) as db:
            refunded = db.query(self.m.Payment).filter_by(charge_id=charge_id, status=3).count()
            state = db.get(self.m.Charge, charge_id).status
        self.record("cash_charge_refunded_once", responses, {"successful_requests": 1, "refunded_payments": 1, "charge_status": 2}, {"refunded_payments": refunded, "charge_status": state})

    def admissions(self):
        with Session(self.engine) as db:
            ward = self.m.Ward(name=f"并发病区{self.tag}", department_id=self.department_id, bed_count=1, status=0)
            db.add(ward)
            db.flush()
            bed = self.m.Bed(ward_id=ward.ward_id, bed_no="CV01", bed_type="普通", price_per_day=0, status=0)
            db.add(bed)
            db.commit()
            ward_id, bed_id = ward.ward_id, bed.bed_id
        payloads = [{"patient_id": p, "doctor_id": self.doctor_id, "department_id": self.department_id, "ward_id": ward_id, "bed_id": bed_id, "admission_type": 0} for p in self.patient_ids]
        responses = self.parallel("/api/admission/create", payloads)
        with Session(self.engine) as db:
            count = db.query(self.m.Admission).filter_by(bed_id=bed_id, status=1).count()
            state = db.get(self.m.Bed, bed_id).status
        self.record("one_active_admission_per_bed", responses, {"successful_requests": 1, "active_admissions": 1, "bed_status": 1}, {"active_admissions": count, "bed_status": state})

        # Independent patients and beds must all succeed with unique daily IDs.
        with Session(self.engine) as db:
            beds = [self.m.Bed(ward_id=ward_id, bed_no=f"CV{index + 2:02d}", bed_type="普通", price_per_day=0, status=0) for index in range(self.concurrency)]
            db.add_all(beds)
            db.flush()
            bed_ids = [bed.bed_id for bed in beds]
            # First case occupied one patient; fresh independent synthetic rows
            # avoid treating the intended active-admission rejection as failure.
            patients = [self.m.Patient(name=f"独立入院{index}", identity=f"cv-ad-{self.tag}-{index}", sex=0, permission="allow", allergy_history="") for index in range(self.concurrency)]
            db.add_all(patients)
            db.commit()
            patient_ids = [patient.patient_id for patient in patients]
        responses = self.parallel("/api/admission/create", [{"patient_id": patient_id, "doctor_id": self.doctor_id, "department_id": self.department_id, "ward_id": ward_id, "bed_id": bed_id, "admission_type": 0} for patient_id, bed_id in zip(patient_ids, bed_ids, strict=True)])
        with Session(self.engine) as db:
            rows = db.query(self.m.Admission).filter(self.m.Admission.bed_id.in_(bed_ids), self.m.Admission.status == 1).all()
            unique_numbers = len({row.admission_no for row in rows})
        self.record("independent_admissions_have_unique_numbers", responses, {"successful_requests": self.concurrency, "active_admissions": self.concurrency, "unique_admission_numbers": self.concurrency}, {"active_admissions": len(rows), "unique_admission_numbers": unique_numbers})

        with Session(self.engine) as db:
            beds = [self.m.Bed(ward_id=ward_id, bed_no=f"CV-S{index}", bed_type="普通", price_per_day=0, status=0) for index in range(self.concurrency)]
            db.add_all(beds)
            patient = self.m.Patient(name="同患者入院验收", identity=f"cv-same-{self.tag}", sex=0, permission="allow", allergy_history="")
            db.add(patient)
            db.commit()
            bed_ids, patient_id = [bed.bed_id for bed in beds], patient.patient_id
        responses = self.parallel("/api/admission/create", [{"patient_id": patient_id, "doctor_id": self.doctor_id, "department_id": self.department_id, "ward_id": ward_id, "bed_id": bed_id, "admission_type": 0} for bed_id in bed_ids])
        with Session(self.engine) as db:
            count = db.query(self.m.Admission).filter_by(patient_id=patient_id, status=1).count()
            occupied = db.query(self.m.Bed).filter(self.m.Bed.bed_id.in_(bed_ids), self.m.Bed.status == 1).count()
        self.record("one_active_admission_per_patient", responses, {"successful_requests": 1, "active_admissions": 1, "occupied_beds": 1}, {"active_admissions": count, "occupied_beds": occupied})

    def medication_administration(self):
        with Session(self.engine) as db:
            now = dt.datetime.now()
            admission = self.m.Admission(patient_id=self.owner_id, doctor_id=self.doctor_id, department_id=self.department_id, status=1, admission_time=now, create_time=now)
            card = self.m.PatientCard(card_no=f"CV-W-{self.tag}", patient_id=self.owner_id, status=0, issue_time=now, issuer_id=self.admin_id)
            drug = self.m.Pharmaceutical(name=f"扫码验收{self.tag}", barcode=f"CV-M-{self.tag}", stock=10, price=1, expireddate=dt.date.today() + dt.timedelta(days=30), status=0, antibiotic_level=0)
            db.add_all([admission, card, drug])
            db.commit()
            admission_id, drug_id = admission.admission_id, drug.pharmaceutical_id
        created = self.post("/api/inpatientOrder/create", {"admission_id": admission_id, "patient_id": self.owner_id, "doctor_id": self.doctor_id, "order_type": 1, "category": "drug", "items": [{"item_name": "扫码验收药", "item_type": "drug", "item_id_ref": drug_id, "quantity": 1, "days": 1, "unit_price": 1}]})
        if created["code"] != 200:
            raise RuntimeError("cannot prepare medication order through actual API")
        order_id = created["body"]["data"]["order_id"]
        audited = self.post("/api/inpatientOrder/audit", {"order_id": order_id})
        if audited["code"] != 200:
            raise RuntimeError("cannot audit medication order through actual API")
        with Session(self.engine) as db:
            execution_id = db.query(self.m.OrderExecution).filter_by(order_id=order_id, status=0).one().execution_id
        verified = self.post("/api/emar/verify", {"execution_id": execution_id, "patient_barcode": f"CV-W-{self.tag}", "medication_barcodes": [f"CV-M-{self.tag}"]})
        if verified["code"] != 200:
            raise RuntimeError("cannot prepare verified administration through actual API")
        administration_id = verified["body"]["data"]["administration_id"]
        responses = self.parallel("/api/emar/administer", [{"administration_id": administration_id, "note": "合成并发验收"}] * self.concurrency)
        with Session(self.engine) as db:
            administrations = db.query(self.m.MedicationAdministration).filter_by(execution_id=execution_id, status=2).count()
            executions = db.query(self.m.OrderExecution).filter_by(execution_id=execution_id, status=1).count()
        self.record("medication_administered_once", responses, {"successful_requests": 1, "completed_administrations": 1, "completed_executions": 1}, {"completed_administrations": administrations, "completed_executions": executions})

    def dispensing(self):
        now = dt.datetime.now()
        with Session(self.engine) as db:
            drug = self.m.Pharmaceutical(name=f"并发药{self.tag}", stock=10, price=1, expireddate=dt.date.today() + dt.timedelta(days=30), status=0, antibiotic_level=0)
            db.add(drug)
            db.flush()
            batch = self.m.PharmaceuticalBatch(pharmaceutical_id=drug.pharmaceutical_id, batch_no=f"CV-{self.tag}", expiry_date=drug.expireddate, stock=10, create_time=now, update_time=now)
            pre = self.m.Prescription(patient_id=self.owner_id, doctor_id=self.doctor_id, status=1, create_time=now)
            db.add_all([batch, pre])
            db.flush()
            db.add(self.m.PrePha(prescription_id=pre.prescription_id, pharmaceutical_id=drug.pharmaceutical_id, number=1))
            db.add(self.m.Charge(prescription_id=pre.prescription_id, amount=1, status=1, charge_type="prescription", charge_time=now))
            db.commit()
            drug_id, batch_id, pre_id = drug.pharmaceutical_id, batch.batch_id, pre.prescription_id
        responses = self.parallel("/api/pharmacy/dispense", [{"prescription_id": pre_id}] * self.concurrency)
        with Session(self.engine) as db:
            observed = {"stock": db.get(self.m.Pharmaceutical, drug_id).stock, "batch_stock": db.get(self.m.PharmaceuticalBatch, batch_id).stock, "outbound_ledger_rows": db.query(self.m.PharmaceuticalStockLedger).filter_by(batch_id=batch_id, transaction_type="outbound").count(), "verification_rows": db.query(self.m.DispenseVerification).filter_by(prescription_id=pre_id).count()}
        self.record("prescription_dispensed_once", responses, {"successful_requests": 1, "stock": 9, "batch_stock": 9, "outbound_ledger_rows": 1, "verification_rows": 1}, observed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not 2 <= args.concurrency <= 64:
        parser.error("--concurrency must be between 2 and 64")
    if args.output.exists():
        parser.error("--output already exists; preserve the earlier evidence")
    database_url = configure_application_environment()
    require_concurrency_safe_database(database_url)
    host = validate_targets(args.host, database_url)
    sys.path.insert(0, str(BACKEND_DIR))
    import app.models as models
    from app.security import hash_password

    started = dt.datetime.now(dt.UTC)
    begin = time.monotonic()
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        probe = Acceptance(host, engine, models, hash_password, args.concurrency)
        for scenario in [probe.booking, probe.registrations, probe.payments, probe.admissions, probe.dispensing, probe.medication_administration]:
            scenario()
        report = {"schema_version": 1, "started_at": started.isoformat(), "finished_at": dt.datetime.now(dt.UTC).isoformat(), "elapsed_seconds": time.monotonic() - begin, "host": host, "database": make_url(database_url).render_as_string(hide_password=True), "concurrency": args.concurrency, "all_passed": all(r["passed"] for r in probe.results), "scenarios": probe.results}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        return 0 if report["all_passed"] else 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
