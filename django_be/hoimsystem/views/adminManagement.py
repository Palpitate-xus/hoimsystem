from django.shortcuts import render
from django.shortcuts import HttpResponse
import json
import traceback
from django.utils import timezone
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
    notices = notice.objects.all()
    token = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN')).user_role
    data = []
    for item in notices:
      if token == "director" and "科室主任" not in item.towho:
        continue
      if token == "doctor" and "医生" not in item.towho:
        continue
      if token == "patient" and "病人" not in item.towho:
        continue
      data.append({
        'uuid': str(item.notice_id),
        'title': item.title,
        'content': item.content,
        'isemergency': item.isemergency,
        'towho': item.towho,
        'sendtime': str(item.sendtime),
        'expiredtime': str(item.expiredtime),
        'readnum': item.readnum,
        'writer': item.writer.username,
      })
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# 通知发布
def notice_register(request):
  received_data = json.loads(request.body.decode())
  title = received_data.get('title')
  content = received_data.get('content')
  isemergency = received_data.get('isemergency')
  towho = str(received_data.get('towho'))
  sendtime = timezone.now()
  expiredtime = received_data.get('expiredtime')
  readnum = 0
  writer = users.objects.get(username=request.META.get('HTTP_ACCESSTOKEN'))
  notice.objects.create(title=title, content=content, isemergency=isemergency, towho=towho,sendtime=sendtime, expiredtime=expiredtime, readnum=readnum, writer=writer)
  response = {"code": 200, "msg": 'success'}
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
      try:
        director_name = doctor.objects.get(doctor_id=item.director).name
      except:
        director_name = ''
      data.append({
        'id': item.department_id,
        'name': item.name,
        'phone': item.phone,
        'location': item.location,
        'director': director_name
        })
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
