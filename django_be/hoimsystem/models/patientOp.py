from django.db import models
import uuid
from django.db import models
# Create your models here.

# 挂号
class registration(models.Model):
  registration_uuid = models.UUIDField()  # 挂号id
  registration_id = models.IntegerField()  # 就诊顺序
  patient_id = models.ForeignKey('patient', on_delete=models.CASCADE)  # 病人id
  doctor_id = models.ForeignKey('doctor', on_delete=models.CASCADE)  # 医生id
  category = models.ForeignKey('reg_category', on_delete=models.PROTECT)  # 挂号类别id
  department_id = models.ForeignKey('department', on_delete=models.CASCADE)  # 科室id
  status = models.IntegerField()  # 挂号状态（是否就诊）

# 预约
class appointment(models.Model):
  registration_uuid = models.UUIDField()
  patient_id = models.ForeignKey('patient', on_delete=models.CASCADE)
  doctor_id = models.ForeignKey('doctor', on_delete=models.CASCADE)
  category = models.ForeignKey('reg_category', on_delete=models.PROTECT)
  department_id = models.ForeignKey('department', on_delete=models.CASCADE)
  prefer_time = models.ForeignKey
  status = models.IntegerField()


# 预约违约记录
class breach_record(models.Model):
  breach_id = models.UUIDField()
  registration_id = models.ForeignKey('registration', on_delete=models.CASCADE)