from django.shortcuts import render
from django.shortcuts import HttpResponse
import json
from hoimsystem.models.roleUser import *
from hoimsystem.models.adminOp import *
# Create your views here.

# 测试api
def test(request):
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 医生注册
def add_doctor(request):
    received_data = json.loads(request.body.decode())
    username = received_data.get('username')
    password = received_data.get('password')
    name = received_data.get('name')
    title = received_data.get('title')
    sex = received_data.get('sex')
    phone = received_data.get('phone')
    department_in = department.objects.get(name=received_data.get('department'))
    permission = received_data('permission')
    education = received_data.get('education')
    try:
        # 在医生表中插入记录
        doctor.objects.create(name=name, sex=sex, title=title, education=education, phone=phone, permission=permission, department_id=department_in)
        # 判断是否为科室主任
        if permission == 'director':
            users.objects.create(username=username, password=password, user_role="director")
        else:
            users.objects.create(username=username, password=password, user_role="doctor")
        response = {"code": 200, "msg": 'success'}
    except:
        response = {"code": 500, "msg": '用户注册失败'}
    return HttpResponse(json.dumps(response))
