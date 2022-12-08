from django.db import models
import uuid
from django.db import models
# Create your models here.

# 处方
class prescription(models.Model):
  prescription_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 处方号
  patient_id = models.ForeignKey('patient', on_delete=models.PROTECT)  # 病人id
  doctor_id = models.ForeignKey('doctor', on_delete=models.PROTECT)  # 医生id

# 处方和药品对应
class pre_pha(models.Model):
  pre_pha_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 对应表id
  prescription_id = models.CharField(max_length=50)  # 对应的处方id
  pharmaceutical_id = models.ForeignKey('pharmaceutical', on_delete=models.PROTECT)  # 药品id
  number = models.IntegerField()  # 药品数量

# 病历
class medical_record(models.Model):
  medical_record_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)  # 病历号
  consultation_time = models.DateTimeField()  # 就诊时间
  doctor_id = models.ForeignKey('doctor', on_delete=models.PROTECT)  # 医生id
  patient_id = models.ForeignKey('patient', on_delete=models.PROTECT)  # 病人id
  symptom = models.CharField(max_length=100)  # 病人症状
  result = models.CharField(max_length=100)  # 诊断结果
  prescription_id = models.ForeignKey('prescription', on_delete=models.PROTECT)  # 处方id

# 药品
class pharmaceutical(models.Model):
  pharmaceutical_id = models.AutoField(primary_key=True)
  name = models.CharField(max_length=24)  # 药品名称
  stock = models.IntegerField()  # 库存数量
  price = models.FloatField()  # 单价
  expireddate = models.DateField()  # 过期时间
  purchasing_time = models.DateTimeField()  # 采购时间
  supplier = models.CharField(max_length=24)  # 供应商
  remark = models.CharField(max_length=100)  # 备注