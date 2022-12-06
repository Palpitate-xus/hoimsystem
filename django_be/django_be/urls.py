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
    re_path('^api/appointManagement/getList', patientManagement.get_appointment_list),
    re_path('^api/appointManagement/create', patientManagement.patient_appointment),
    re_path('^api/appointManagement/cancel', patientManagement.patient_appointment_cancel),
    re_path('^api/registrationManagement/getList', patientManagement.get_registration_list),
    re_path('^api/registrationManagement/create', patientManagement.patient_registration),
    re_path('^api/registrationManagement/cancel', patientManagement.patient_registration_cancel),

    # 管理员操作组
    re_path('^api/doctorManagement/getList', adminManagement.get_doctor_list),
    re_path('^api/departmentManagement/create', adminManagement.department_register),

]
