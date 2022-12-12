from django.shortcuts import render
from django.shortcuts import HttpResponse
from django.utils import timezone
from datetime import datetime
import time
import json
from hoimsystem.models.roleUser import *
from hoimsystem.models.patientOp import *
from hoimsystem.models.doctorOp import *
from hoimsystem.models.adminOp import *
# Create your views here.

# 测试api
def test(request):
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 挂号信息
def registrationList(request):
    today_weeky = datetime.now().weekday()
    weekdays = ['星期一', '星期二', '星期三', '星期四', '星期五']
    if today_weeky > 4:
        data = '今天为休息日'
    else:
        data = []
        schedules = doctor_schedule.objects.filter(week=weekdays[today_weeky])
        for item in schedules:
            data.append({
                'id': item.schedule_id,
                'time': item.time,
                'specialist': item.specialist,
                'time': item.time,
                'doctor': item.doctor_id.name,
                'doctor_id': item.doctor_id.doctor_id,
                'department_id': item.doctor_id.department_id.department_id,
                'stock': item.number,
            })
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# 病人挂号
def patient_registration(request):
    token = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).username
    patient_id = patient.objects.get(identity=token)
    received_data = json.loads(request.body.decode())
    reg_id = received_data.get('id')
    reg_obj = doctor_schedule.objects.get(schedule_id=reg_id)
    reg_obj.number-=1
    reg_obj.save()
    registration_id = 1
    doctor_id = doctor.objects.get(doctor_id=received_data.get('doctor_id'))
    specialist = received_data.get('specialist')
    time = timezone.now()
    status = 0
    department_id = department.objects.get(department_id=received_data.get('department_id'))
    registration.objects.create(registration_id=registration_id, patient_id=patient_id, doctor_id=doctor_id, specialist=specialist, department_id=department_id, time=time, status=status)
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 病人取消挂号
def patient_registration_cancel(request):
    received_data = json.loads(request.body.decode())
    uuid = received_data.get('uuid')
    registration_obj = registration.objects.get(registration_uuid=uuid)
    registration_obj.status=3
    registration_obj.save()
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 挂号记录查看
def get_registration_list(request):
    token = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).username
    patient_id = patient.objects.get(identity=token).patient_id
    registration_list = registration.objects.filter(patient_id=patient_id)
    data = []
    status = ['未就诊', '已就诊', '','已取消']
    for item in registration_list:
        data.append({
            'uuid': str(item.registration_uuid),
            'order': item.registration_id,
            'doctor': item.doctor_id.name,
            'specialist': item.specialist,
            'department': item.department_id.name,
            'time': str(item.time)[0:10],
            'status': status[item.status],
        })
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# 预约信息
def appointmentList(request):
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 病人预约
def patient_appointment(request):
    received_data = json.loads(request.body.decode())
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 病人取消预约
def patient_appointment_cancel(request):
    received_data = json.loads(request.body.decode())
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 预约记录查看
def get_appointment_list(request):
    token = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).username
    patient_id = patient.objects.get(identity=token).patient_id
    appointment_list = appointment.objects.filter(patient_id=patient_id)
    data = []
    for item in appointment_list:
        data.append({
            'uuid': item.registration_uuid,
            'order': item.registration_id,
            'doctor': item.doctor_id.name,
            'specialist': item.specialist,
            'department': item.department_id.name,
            'time': item.time,
            'status': item.status,
        })
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# 检查记录查看
def get_inspection_list(request):
    received_data = json.loads(request.body.decode())
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 病历查看
def get_medicalrecords_list(request):
    received_data = json.loads(request.body.decode())
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 收费记录查看
def get_charges_list(request):
    role = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).user_role
    username = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).username
    data = []
    if role == 'admin':
        charge_list = charge.objects.all()
        for item in charge_list:
            data.append({
                'id': str(item.charge_id),
                'charge_time': str(item.charge_time),
                'time': str(item.time),
                'pre_id': str(item.prescription_id.prescription_id),
                'amount': round(item.amount, 2),
                'status': item.status,
            })
    elif role == 'patient':
        patient_id = patient.objects.get(identity=username).patient_id
        pres = prescription.objects.filter(patient_id=patient_id)
        for pre in pres:
            item = charge.objects.get(prescription_id=pre.prescription_id)
            data.append({
                'id': str(item.charge_id),
                'charge_time': str(item.charge_time),
                'time': str(item.time),
                'pre_id': str(item.prescription_id.prescription_id),
                'amount': round(item.amount, 2),
                'status': item.status,
            })
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# 缴费
def charge_commit(request):
    received_data = json.loads(request.body.decode())
    charge_id = received_data.get('id')
    charge_obj = charge.objects.get(charge_id=charge_id)
    charge_obj.status = 1
    charge_obj.time = timezone.now()
    charge_obj.save()
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

    


