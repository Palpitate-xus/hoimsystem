from django.shortcuts import render
from django.shortcuts import HttpResponse
import json
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

# 挂号记录查看
def get_registration_list(request):
    received_data = json.loads(request.body.decode())
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 病人预约
def patient_appointment(request):
    received_data = json.loads(request.body.decode())
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 预约记录查看
def get_appointment_list(request):
    received_data = json.loads(request.body.decode())
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
    received_data = json.loads(request.body.decode())
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))


