from django.db import models
import uuid
from django.db import models
# Create your models here.

class role(models.Model):
  role_id = models.UUIDField(primary_key=True)
  accessToken = models.CharField(max_length=50)

class patient(models.Model):
  patient_id = models.AutoField(primary_key=True)  # 自动递增的病人id
  name = models.CharField(max_length=24)  # 病人姓名
  sex = models.IntegerField()  # 病人性别，0女1男
  birthday = models.DateField()  # 病人出生日期
  phone = models.CharField(max_length=11)  # 病人联系方式
  password = models.CharField(max_length=24)  # 病人密码
  address = models.CharField(max_length=100)  # 病人住址
  permission = models.CharField(max_length=10)  # 病人权限

class doctor(models.Model):
  doctor_id = models.AutoField(primary_key=True)  # 自动递增的医生id
  name = models.CharField(max_length=24)  # 医生姓名
  sex = models.IntegerField()  # 医生性别，0女1男
  title = models.CharField(max_length=10)  # 医生职称
  education = models.CharField(max_length=10)  # 医生学历
  phone = models.CharField(max_length=11)  # 医生联系方式
  password = models.CharField(max_length=24)  # 医生密码
  permission = models.CharField(max_length=10)  # 医生权限
