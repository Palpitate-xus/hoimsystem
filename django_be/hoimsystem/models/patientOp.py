from django.db import models
import uuid
from django.db import models
# Create your models here.

class registration(models.Model):
  registration_uuid = models.UUIDField()
  patient_id = models.ForeignKey('patient', on_delete=models.CASCADE)
  doctor_id = models.ForeignKey('doctor', on_delete=models.CASCADE)
  category = models.ForeignKey
  department_id = models.ForeignKey('department', on_delete=models.CASCADE)