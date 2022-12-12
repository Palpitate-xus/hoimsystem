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
  director = models.IntegerField()  # 科室主任id

# 预约就诊时间段
class timeslot(models.Model):
  timeslot_id = models.AutoField(primary_key=True)  # 时间段id
  time = models.CharField(max_length=20)  # 时间段

# 通知
class notice(models.Model):
  notice_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 通知id
  title = models.CharField(max_length=12)  # 通知标题
  content = models.TextField()  # 通知内容
  isemergency = models.IntegerField()  # 是否紧急
  towho = models.CharField(max_length=100)  # 发送对象
  sendtime = models.DateTimeField()  # 发送时间
  expiredtime = models.DateTimeField()  # 过期时间
  readnum = models.IntegerField()  # 已读数量
  writer = models.ForeignKey('users', on_delete=models.CASCADE)  # 发送人

# 医生排班表
class doctor_schedule(models.Model):
  schedule_id = models.AutoField(primary_key=True)  # 排班id
  week = models.CharField(max_length=5)  # 星期几
  time = models.CharField(max_length=2)  # 上午 or 下午
  number = models.IntegerField()  # 最大就诊人数
  specialist = models.IntegerField()  # 是否专家号
  doctor_id = models.ForeignKey('doctor', on_delete=models.PROTECT)  # 医生id