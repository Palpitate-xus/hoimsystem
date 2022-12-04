from django.db import models
import uuid
from django.db import models
# Create your models here.

class department(models.Model):
  department_id = models.AutoField(primary_key=True)
  name = models.CharField(max_length=24)
  phone = models.CharField(max_length=11)
  location = models.CharField(max_length=24)
  director = models.ForeignKey('doctor', on_delete=models.PROTECT)

class reg_category(models.Model):
  reg_category_id = models.AutoField(primary_key=True)
  name = models.CharField(max_length=10)