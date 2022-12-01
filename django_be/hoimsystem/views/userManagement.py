from django.shortcuts import render
from django.shortcuts import HttpResponse
import json
# Create your views here.

# 测试api
def test(request):
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# publicKey
def get_public_key(request):
    response = {"code": 200, "msg": 'success', "data": {"publicKey", 'MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDBT2vr+dhZElF73FJ6xiP181txKWUSNLPQQlid6DUJhGAOZblluafIdLmnUyKE8mMHhT3R+Ib3ssZcJku6Hn72yHYj/qPkCGFv0eFo7G+GJfDIUeDyalBN0QsuiE/XzPHJBuJDfRArOiWvH0BXOv5kpeXSXM8yTt5Na1jAYSiQ/wIDAQAB'}}
    return HttpResponse(json.dumps(response))

# 登录
def login(request):
    rec = request.body().decode()
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 注册
def register(request):
    rec = request.body().decode()
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 获取用户信息
def get_user_info(request):
    rec = request.body().decode()
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 退出登录
def logout(request):
    rec = request.body().decode()
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))
    