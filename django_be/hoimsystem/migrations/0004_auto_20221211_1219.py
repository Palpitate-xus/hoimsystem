# Generated by Django 3.2.9 on 2022-12-11 04:19

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('hoimsystem', '0003_charge'),
    ]

    operations = [
        migrations.AddField(
            model_name='appointment',
            name='appointment_time',
            field=models.DateTimeField(),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='appointment',
            name='time',
            field=models.DateField(),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='registration',
            name='time',
            field=models.DateTimeField(),
            preserve_default=False,
        ),
    ]
