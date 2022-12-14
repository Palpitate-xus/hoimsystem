"""django_be URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, re_path
from hoimsystem.views import *
urlpatterns = [
    path('admin/', admin.site.urls),
    re_path('^api/test', userManagement.test),
    # 登录组
    re_path('^api/publicKey', userManagement.get_public_key),
    re_path('^api/login', userManagement.login),
    re_path('^api/register', userManagement.register),
    re_path('^api/userInfo', userManagement.get_user_info),
    re_path('^api/logout', userManagement.logout),

    # 病人操作组
    re_path('^api/appointmentManagement/getList', patientManagement.get_appointment_list),
    re_path('^api/appointmentManagement/appointmentList', patientManagement.appointmentList),
    re_path('^api/appointmentManagement/create', patientManagement.patient_appointment),
    re_path('^api/appointmentManagement/cancel', patientManagement.patient_appointment_cancel),
    re_path('^api/registrationManagement/getList', patientManagement.get_registration_list),
    re_path('^api/registrationManagement/registrationList', patientManagement.registrationList),
    re_path('^api/registrationManagement/create', patientManagement.patient_registration),
    re_path('^api/registrationManagement/cancel', patientManagement.patient_registration_cancel),
    re_path('^api/chargeManagement/getList', patientManagement.get_charges_list),
    re_path('^api/chargeManagement/charge', patientManagement.charge_commit),

    # 管理员操作组
    re_path('^api/doctorManagement/getList', adminManagement.get_doctor_list),
    re_path('^api/patientManagement/getList', adminManagement.get_patient_list),
    re_path('^api/departmentManagement/getList', adminManagement.get_department_list),
    re_path('^api/departmentManagement/create', adminManagement.department_register),
    re_path('^api/notice/getList', adminManagement.get_notice_list),
    re_path('^api/notice/create', adminManagement.notice_register),

    # 医生操作组
    re_path('^api/doctorManagement/register', doctorManagement.add_doctor),
    re_path('^api/doctorScheduleManagement/register', doctorManagement.doctor_schedule_register),
    re_path('^api/doctorScheduleManagement/getList', doctorManagement.doctor_schedule_getlist),
    re_path('^api/pharmaceuticalManagement/create', doctorManagement.pharmaceutical_register),
    re_path('^api/pharmaceuticalManagement/getList', doctorManagement.get_pharmaceutical_list),
    re_path('^api/pharmaceuticalManagement/stock_query', doctorManagement.pharmaceutical_stock_query),
    re_path('^api/prescriptionManagement/getList', doctorManagement.get_prescription_list),
    re_path('^api/prescriptionManagement/create', doctorManagement.prescription_register),

]
