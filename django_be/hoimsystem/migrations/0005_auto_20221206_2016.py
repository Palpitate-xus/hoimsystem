# Generated by Django 3.2.16 on 2022-12-06 12:16

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('hoimsystem', '0004_auto_20221206_1347'),
    ]

    operations = [
        migrations.CreateModel(
            name='medical_record',
            fields=[
                ('medical_record_id', models.UUIDField(primary_key=True, serialize=False)),
            ],
        ),
        migrations.CreateModel(
            name='notice',
            fields=[
                ('notice_id', models.UUIDField(primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=12)),
                ('content', models.TextField()),
            ],
        ),
        migrations.CreateModel(
            name='prescription',
            fields=[
                ('prescription_id', models.UUIDField(primary_key=True, serialize=False)),
            ],
        ),
        migrations.AlterField(
            model_name='department',
            name='director',
            field=models.IntegerField(),
        ),
    ]
