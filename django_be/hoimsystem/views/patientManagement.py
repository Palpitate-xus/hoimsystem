from django.shortcuts import render
from django.shortcuts import HttpResponse
from django.utils import timezone
import json
from hoimsystem.models.roleUser import *
from hoimsystem.models.patientOp import *
from hoimsystem.models.doctorOp import *
# Create your views here.

# 测试api
def test(request):
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 病人挂号
def patient_registration(request):
    received_data = json.loads(request.body.decode())
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 病人取消挂号
def patient_registration_cancel(request):
    received_data = json.loads(request.body.decode())
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 挂号记录查看
def get_registration_list(request):
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
    response = {"code": 200, "msg": 'success'}
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

    


