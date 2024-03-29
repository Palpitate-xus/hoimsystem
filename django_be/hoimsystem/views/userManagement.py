from django.shortcuts import render
from django.shortcuts import HttpResponse
import json
from hoimsystem.models.roleUser import *
# Create your views here.

# 测试api
def test(request):
    received_data = json.loads(request.body.decode())
    temp = received_data.get('data')
    response = {"code": 200, "msg": 'success', "data": temp}
    return HttpResponse(json.dumps(response))

# publicKey
def get_public_key(request):
    response = {"code": 200, "msg": 'success', "data": {
        "publicKey": 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDBT2vr+dhZElF73FJ6xiP181txKWUSNLPQQlid6DUJhGAOZblluafIdLmnUyKE8mMHhT3R+Ib3ssZcJku6Hn72yHYj/qPkCGFv0eFo7G+GJfDIUeDyalBN0QsuiE/XzPHJBuJDfRArOiWvH0BXOv5kpeXSXM8yTt5Na1jAYSiQ/wIDAQAB',
        "mockServer": 'False',
        }}
    return HttpResponse(json.dumps(response))

# 登录
def login(request):
    received_data = json.loads(request.body.decode())
    username = received_data.get('username')
    password = received_data.get('password')
    if users.objects.filter(username=username, password=password).exists():
        response = {"code": 200, "msg": 'success', "data": {"accessToken": username}}
    else:
        response = {"code": 500, "msg": '账户或密码不正确'}

    return HttpResponse(json.dumps(response))

# 注册
def register(request):
    received_data = json.loads(request.body.decode())
    username = received_data.get('username')
    password = received_data.get('password')
    identity = received_data.get('identity')
    address = received_data.get('address')
    sex = received_data.get('sex')
    phone = received_data.get('phone')
    birthday = received_data.get('birthday')
    try:
        patient.objects.create(name=username, identity=identity, address=address, sex=sex, phone=phone, birthday=birthday, permission="allow")
        users.objects.create(username=identity, password=password, user_role="patient")
        response = {"code": 200, "msg": 'success'}
    except:
        response = {"code": 500, "msg": '用户注册失败'}
    return HttpResponse(json.dumps(response))

# 获取用户信息
def get_user_info(request):
    received_data = json.loads(request.body.decode())
    access_token = received_data.get('accessToken')
    userinfo = users.objects.get(username=access_token)
    if userinfo.user_role == 'admin':
        permissions = ['admin']
    elif userinfo.user_role == 'doctor':
        permissions = ['doctor']
    elif userinfo.user_role == 'director':
        permissions = ['director', 'doctor']
    elif userinfo.user_role == 'patient':
        permissions = ['patient']
    username = userinfo.username
    avatar_url = 'https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fc-ssl.duitang.com%2Fuploads%2Fitem%2F202006%2F07%2F20200607000651_vopye.jpg&refer=http%3A%2F%2Fc-ssl.duitang.com&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1672814873&t=b4388830c9cf3005e51d64f282b07abc'
    data = {'permissions': permissions, 'username': username, 'avatar': avatar_url}
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# 退出登录
def logout(request):
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))
    