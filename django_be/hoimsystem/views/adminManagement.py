from django.shortcuts import render
from django.shortcuts import HttpResponse
import json
import traceback
from hoimsystem.models.adminOp import *
from hoimsystem.models.roleUser import *
# Create your views here.

# 测试api
def test(request):
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))
  
# 获取医生列表
def get_doctor_list(request):
    doctors = doctor.objects.all()
    data = []
    for item in doctors:
      data.append({
        'id': item.doctor_id,
        'name': item.name,
        'sex': item.sex,
        'education': item.education,
        'phone': item.phone,
        'permission': item.permission,
        'title': item.title
        })
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# 获取通知列表
def get_notice_list(request):
    data = []
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# department注册
def department_register(request):
    received_data = json.loads(request.body.decode())
    name = received_data.get('name')
    phone = received_data.get('phone')
    director = received_data.get('director')
    location = received_data.get('location')
    try:
      department.objects.create(name=name, phone=phone, location=location, director=director)
      response = {"code": 200, "msg": 'success'}
    except:
      traceback.print_exc()
      response = {"code": 500, "msg": '科室注册失败'}
    return HttpResponse(json.dumps(response))

# 获取科室列表
def get_department_list(request):
    doctors = department.objects.all()
    data = []
    for item in doctors:
      data.append({'id': item.department_id, 'name': item.name})
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# 管理员密码修改
def update_password(request):
    received_data = json.loads(request.body.decode())
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 获取病人列表
def get_patient_list(request):
    patient_data = patient.objects.all()
    data = []
    for item in patient_data:
      if item.sex == 0:
        sex = '女'
      else:
        sex = '男'
      data.append({
        'id': item.patient_id,
        'name': item.name,
        'sex': sex,
        'birthday': str(item.birthday),
        'phone': item.phone,
        'permission': item.permission,
        'address': item.address,
        'identity': item.identity
        })
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))
