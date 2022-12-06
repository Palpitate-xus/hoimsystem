from django.db import models
import uuid
from django.db import models
# Create your models here.

# 处方
class prescription(models.Model):
  prescription_id = models.UUIDField(primary_key=True)

# 病历
class medical_record(models.Model):
  medical_record_id = models.UUIDField(primary_key=True)