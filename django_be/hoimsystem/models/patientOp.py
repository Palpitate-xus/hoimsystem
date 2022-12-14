from django.db import models
import uuid
from django.db import models
# Create your models here.

# 挂号
class registration(models.Model):
  registration_uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 挂号id
  registration_id = models.IntegerField()  # 就诊顺序
  patient_id = models.ForeignKey('patient', on_delete=models.CASCADE)  # 病人id
  doctor_id = models.ForeignKey('doctor', on_delete=models.CASCADE)  # 医生id
  specialist = models.IntegerField()  # 挂号类别
  department_id = models.ForeignKey('department', on_delete=models.CASCADE)  # 科室id
  time = models.DateTimeField()  # 挂号时间
  status = models.IntegerField()  # 挂号状态（是否就诊）

# 预约
class appointment(models.Model):
  registration_uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 预约id
  patient_id = models.ForeignKey('patient', on_delete=models.CASCADE)  # 病人id
  doctor_id = models.ForeignKey('doctor', on_delete=models.CASCADE)  # 医生id
  specialist = models.IntegerField()  # 挂号类别
  department_id = models.ForeignKey('department', on_delete=models.CASCADE)  # 科室id
  prefer_time = models.CharField(max_length=5)  # 预约时间段
  appointment_time = models.DateTimeField()  # 预约时间
  time = models.DateField()  # 预约日期
  status = models.IntegerField()  # 预约状态

# 预约违约记录
class breach_record(models.Model):
  breach_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 违约记录id
  registration_id = models.ForeignKey('registration', on_delete=models.CASCADE)

# 收费信息
class charge(models.Model):
    charge_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 收费记录id
    charge_time = models.DateTimeField()  # 收费时间
    time = models.DateTimeField()  # 缴费时间
    prescription_id = models.ForeignKey('prescription', on_delete=models.PROTECT)  # 处方id
    amount = models.FloatField()  # 收费金额
    status = models.IntegerField()  # 状态