from django.shortcuts import render
from django.shortcuts import HttpResponse
import json
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
        "mockServer": 'True',
        }}
    return HttpResponse(json.dumps(response))

# 登录
def login(request):
    received_data = json.loads(request.body.decode())
    username = received_data.get('username')
    password = received_data.get('password')
    if username and password:
        response = {"code": 200, "msg": 'success', "data": "accessToken"}
    else:
        response = {"code": 500, "msg": '账户或密码不正确'}
    return HttpResponse(json.dumps(response))

# 注册
def register(request):
    received_data = json.loads(request.body.decode())
    username = received_data.get('username')
    password = received_data.get('password')
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))

# 获取用户信息
def get_user_info(request):
    received_data = json.loads(request.body.decode())
    access_token = received_data.get('accessToken')
    permissions = []
    username = ''
    avatar_url = 'https://gimg2.baidu.com/image_search/src=http%3A%2F%2Fc-ssl.duitang.com%2Fuploads%2Fitem%2F202006%2F07%2F20200607000651_vopye.jpg&refer=http%3A%2F%2Fc-ssl.duitang.com&app=2002&size=f9999,10000&q=a80&n=0&g=0n&fmt=auto?sec=1672814873&t=b4388830c9cf3005e51d64f282b07abc'
    data = {'permissions': permissions, 'username': username, 'avatar': avatar_url}
    response = {"code": 200, "msg": 'success', "data": data}
    return HttpResponse(json.dumps(response))

# 退出登录
def logout(request):
    rec = request.body().decode()
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))
    