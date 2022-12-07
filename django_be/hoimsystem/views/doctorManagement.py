from django.shortcuts import render
from django.shortcuts import HttpResponse
from django.utils import timezone
import json
import traceback
from hoimsystem.models.roleUser import *
from hoimsystem.models.adminOp import *
from hoimsystem.models.doctorOp import *
# Create your views here.

# 测试api
def test(request):
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 医生注册
def add_doctor(request):
    received_data = json.loads(request.body.decode())
    username = received_data.get('username')
    if users.objects.filter(username=username).exists():
         response = {"code": 500, "msg": '已存在相同用户'}
         return HttpResponse(json.dumps(response))
    password = received_data.get('password')
    name = received_data.get('name')
    title = received_data.get('title')
    if received_data.get('sex') == '女':
        sex = 0
    else:
        sex = 1
    phone = received_data.get('phone')
    department_in = department.objects.get(department_id=received_data.get('department'))
    permission = received_data.get('permission')
    education = received_data.get('education')
    try:
        # 判断是否为科室主任
        if permission == 'director':
            users.objects.create(username=username, password=password, user_role="director")
        else:
            users.objects.create(username=username, password=password, user_role="doctor")
        user_id = users.objects.get(username=username)
        # 在医生表中插入记录
        doctor.objects.create(name=name, sex=sex, title=title, education=education, phone=phone, permission=permission, department_id=department_in, user_id=user_id)
        response = {"code": 200, "msg": 'success'}
    except:
        traceback.print_exc()
        response = {"code": 500, "msg": '医生注册失败'}
    return HttpResponse(json.dumps(response))

# 医生排班
def doctor_schedule_register(request):
    received_data = json.loads(request.body.decode())
    schedule_list = received_data.get('schedule')
    specialist = received_data.get('specialist')
    number = received_data.get('number')
    doctor_obj = doctor.objects.get(doctor_id=received_data.get('doctor'))
    for i in schedule_list:
        week = i[0:3]
        time = i[3:5]
        doctor_schedule.objects.create(week=week, time=time, number=number, specialist=specialist, doctor_id=doctor_obj)
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 医生排班信息查看
def doctor_schedule_getlist(request):
    token = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).user_role
    data = []
    if token == 'admin':
        schedule_list = doctor_schedule.objects.all()
        doctor_list = doctor.objects.all()
        for i in doctor_list:
            schedule_list = doctor_schedule.objects.filter(doctor_id=i.doctor_id)
            schedule = []
            for j in schedule_list:
                schedule.append(j.week + j.time)
            data.append({
                'id': i.doctor_id,
                'name': i.name,
                'schedule': schedule
            })
    else:
        token = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).user_role
        doctor_obj = doctor.objects.get(user_id=users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')))
        schedule_list = doctor_schedule.objects.filter(doctor_id=doctor_obj.doctor_id)
        schedule = []
        for i in schedule_list:
            schedule.append(i.week + i.time)
        data.append({
                'id': doctor_obj.doctor_id,
                'name': doctor_obj.name,
                'schedule': schedule
            })
    response = {"code": 200, "msg": 'success', 'data': data}
    return HttpResponse(json.dumps(response))

# 药品注册
def pharmaceutical_register(request):
    received_data = json.loads(request.body.decode())
    name = received_data.get('name')
    stock = received_data.get('stock')
    price = float(received_data.get('price'))
    expireddate = received_data.get('expireddate')
    purchasing_time = timezone.now()
    supplier = received_data.get('supplier')
    remark = received_data.get('remark')
    pharmaceutical.objects.create(name=name, stock=stock, price=price, expireddate=expireddate, purchasing_time=purchasing_time, supplier=supplier, remark=remark)
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 药品信息
def get_pharmaceutical_list(request):
    pharmaceutical_list = pharmaceutical.objects.all()
    data = []
    for item in pharmaceutical_list:
        data.append({
            'id': item.pharmaceutical_id,
            'name': item.name,
            'stock': item.stock,
            'price': item.price,
            'expireddate': str(item.expireddate),
            'purchasing_time': str(item.purchasing_time),
            'supplier': item.supplier,
            'remark': item.remark
        })
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))