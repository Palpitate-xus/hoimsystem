from django.shortcuts import render
from django.shortcuts import HttpResponse
import json
# Create your views here.

# 测试api
def test(request):
    response = {"code": 200, "msg": 'success'}
    return HttpResponse(json.dumps(response))
