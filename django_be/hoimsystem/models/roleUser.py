from django.db import models
import uuid
from django.db import models
# Create your models here.

class users(models.Model):
  user_id = models.AutoField(primary_key=True)
  username = models.CharField(max_length=20)
  password = models.CharField(max_length=20)
  user_role = models.CharField(max_length=10)

class patient(models.Model):
  patient_id = models.AutoField(primary_key=True)  # 自动递增的病人id
  name = models.CharField(max_length=24)  # 病人姓名
  sex = models.IntegerField()  # 病人性别，0女1男
  identity = models.CharField(max_length=20)  # 病人身份证号
  birthday = models.DateField()  # 病人出生日期
  phone = models.CharField(max_length=11)  # 病人联系方式
  address = models.CharField(max_length=100)  # 病人住址
  permission = models.CharField(max_length=10)  # 病人权限

class doctor(models.Model):
  doctor_id = models.AutoField(primary_key=True)  # 自动递增的医生id
  name = models.CharField(max_length=24)  # 医生姓名
  sex = models.IntegerField()  # 医生性别，0女1男
  department_id = models.ForeignKey('department', on_delete=models.PROTECT)  # 科室id
  title = models.CharField(max_length=10)  # 医生职称
  education = models.CharField(max_length=10)  # 医生学历
  phone = models.CharField(max_length=11)  # 医生联系方式
  permission = models.CharField(max_length=10)  # 医生权限
