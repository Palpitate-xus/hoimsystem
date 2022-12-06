from django.shortcuts import render
from django.shortcuts import HttpResponse
import json
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
      data.append({'id': item.doctor_id, 'name': item.name})
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# department注册
def department_register(request):
    received_data = json.loads(request.body.decode())
    name = received_data.get('name')
    phone = received_data.get('phone')
    director = doctor.objects.get(doctor_id=received_data.get('director'))
    location = received_data.get('location')
    try:
      department.objects.create(name=name, phone=phone, location=location, director=director)
      response = {"code": 200, "msg": 'success'}
    except:
      response = {"code": 500, "msg": '科室注册失败'}
    return HttpResponse(json.dumps(response))

# 管理员密码修改
def update_password(request):
    received_data = json.loads(request.body.decode())
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))
