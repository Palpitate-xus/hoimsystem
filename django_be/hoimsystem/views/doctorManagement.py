from django.shortcuts import render
from django.shortcuts import HttpResponse
from django.utils import timezone
import json
import traceback
from hoimsystem.models.roleUser import *
from hoimsystem.models.adminOp import *
from hoimsystem.models.doctorOp import *
from hoimsystem.models.roleUser import *
from hoimsystem.models.patientOp import *
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
        if doctor_schedule.objects.filter(week=week, time=time, doctor_id=doctor_obj).exists():
            doctor_schedule_obj = doctor_schedule.objects.get(week=week, time=time, doctor_id=doctor_obj)
            doctor_schedule_obj.number = number
            doctor_schedule_obj.specialist = specialist
            doctor_schedule_obj.save()
        else:
            doctor_schedule.objects.create(week=week, time=time, number=number, specialist=specialist, doctor_id=doctor_obj)
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 医生排班信息查看
def doctor_schedule_getlist(request):
    token = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).user_role
    data = []
    if token == 'admin' or token == 'patient':
        schedule_list = doctor_schedule.objects.all()
        doctor_list = doctor.objects.all()
        for i in doctor_list:
            schedule_list = doctor_schedule.objects.filter(doctor_id=i.doctor_id)
            schedule = []
            for j in schedule_list:
                schedule.append(j.week[2] + j.time[0])
            data.append({
                'id': i.doctor_id,
                'name': i.name,
                'schedule': schedule
            })
    elif token == 'doctor' or token == 'director':
        token = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).user_role
        doctor_obj = doctor.objects.get(user_id=users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')))
        schedule_list = doctor_schedule.objects.filter(doctor_id=doctor_obj.doctor_id)
        schedule = []
        for i in schedule_list:
            schedule.append(i.week[2] + i.time[0])
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

# 药品处方查询
def pharmaceutical_stock_query(request):
    received_data = json.loads(request.body.decode())
    pharmaceutical_id = received_data.get('id')
    stock_status = pharmaceutical.objects.get(pharmaceutical_id=pharmaceutical_id).stock
    data = {"stock": stock_status}
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# 处方注册
def prescription_register(request):
    received_data = json.loads(request.body.decode())
    doctor_uid = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).user_id
    doctor_obj = doctor.objects.get(user_id=doctor_uid)
    patient_id = received_data.get('patient')
    patient_obj = patient.objects.get(patient_id=patient_id)
    pre = prescription.objects.create(patient_id=patient_obj, doctor_id=doctor_obj)
    prescription_obj = prescription.objects.get(prescription_id=pre.prescription_id)
    phas = received_data.get('phas')
    amount = 0
    for item in phas:
        pharmaceutical_obj = pharmaceutical.objects.get(pharmaceutical_id=item['id'])
        pharmaceutical_obj.stock -= int(item['number'])
        pharmaceutical_obj.save()
        pre_pha.objects.create(prescription_id=pre.prescription_id, pharmaceutical_id=pharmaceutical_obj, number=item['number'])
        price = pharmaceutical.objects.get(pharmaceutical_id=item['id']).price
        amount = amount + float(price) * int(item['number'])
        print(amount)
    charge.objects.create(charge_time=timezone.now(), time="1970-1-1", prescription_id=prescription_obj, amount=amount, status=0)
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 获取处方信息
def get_prescription_list(request):
    role = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).user_role
    username = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).username
    data = []
    if role == 'admin':
        prescriptions = prescription.objects.all()
        for item in prescriptions:
            doctor_id = item.doctor_id.doctor_id
            doctor_name = item.doctor_id.name
            patient_id = item.patient_id.patient_id
            patient_name = item.patient_id.name
            phas = []
            phas_raw = pre_pha.objects.filter(prescription_id=item.prescription_id)
            for j in phas_raw:
                pha_name = j.pharmaceutical_id.name
                number = j.number
                phas.append({"name": pha_name, "number": number})
            data.append({
                "uuid": str(item.prescription_id),
                "doctor_id": doctor_id,
                "doctor_name": doctor_name,
                "patient_id": patient_id,
                "patient_name": patient_name,
                "phas": phas,
            })
    elif role == 'doctor' or role == 'director':
        id = doctor.objects.get(user_id=users.objects.get(username=username).user_id).doctor_id
        prescriptions = prescription.objects.filter(doctor_id=id)
        for item in prescriptions:
            doctor_id = item.doctor_id.doctor_id
            doctor_name = item.doctor_id.name
            patient_id = item.patient_id.patient_id
            patient_name = item.patient_id.name
            phas = []
            phas_raw = pre_pha.objects.filter(prescription_id=item.prescription_id)
            for j in phas_raw:
                pha_name = j.pharmaceutical_id.name
                number = j.number
                phas.append({"name": pha_name, "number": number})
            data.append({
                "uuid": str(item.prescription_id),
                "doctor_id": doctor_id,
                "doctor_name": doctor_name,
                "patient_id": patient_id,
                "patient_name": patient_name,
                "phas": phas,
            })
    elif role == 'patient':
        id = patient.objects.get(user_id=users.objects.get(username=username).user_id).patient_id
        prescriptions = prescription.objects.filter(patient_id=id)
        for item in prescriptions:
            doctor_id = item.doctor_id.doctor_id
            doctor_name = item.doctor_id.name
            patient_id = item.patient_id.patient_id
            patient_name = item.patient_id.name
            phas = []
            phas_raw = pre_pha.objects.filter(prescription_id=item.prescription_id)
            for j in phas_raw:
                pha_name = j.pharmaceutical_id.name
                number = j.number
                phas.append({"name": pha_name, "number": number})
            data.append({
                "doctor_id": doctor_id,
                "doctor_name": doctor_name,
                "patient_id": patient_id,
                "patient_name": patient_name,
                "phas": phas,
            })
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))
    