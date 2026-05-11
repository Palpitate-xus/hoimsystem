from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    system,
    triage,
    triage_desk,
    upload,
    user,
    vitalsign,
    ward,
)

app = FastAPI(title="HOIM System FastAPI")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
