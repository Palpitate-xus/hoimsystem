from django.db import models
import uuid
from django.db import models
# Create your models here.

# 科室管理
class department(models.Model):
  department_id = models.AutoField(primary_key=True)  # 科室id
  name = models.CharField(max_length=24)  # 科室名字
  phone = models.CharField(max_length=11)  # 科室联系方式
  location = models.CharField(max_length=24)  # 科室位置
  director = models.ForeignKey('doctor', on_delete=models.PROTECT)  # 科室主任id

# 挂号类别管理
class reg_category(models.Model):
  reg_category_id = models.AutoField(primary_key=True)  # 挂号类别id
  name = models.CharField(max_length=10)  # 挂号类别名称

# 预约就诊时间段
class timeslot(models.Model):
  timeslot_id = models.AutoField(primary_key=True)
  time = models.CharField(max_length=20)  
