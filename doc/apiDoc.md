# 医院信息管理系统api文档

baseURL：/api

## Login

| url        | method | payload | response |
|:----------:|:------:|:-------:| -------- |
| /publicKey | POST   |         |          |
| /login     | POST   |         |          |
| /register  | POST   |         |          |
| /userInfo  | POST   |         |          |
| /logout    | POST   |         |          |

## Admin

| url                           | method | payload | response |
|:-----------------------------:|:------:| ------- |:--------:|
| /doctorManagement/getList     | POST   |         |          |
| /patientManagement/getList    | POST   |         |          |
| /departmentManagement/getList | POST   |         |          |
| /departmentManagement/create  | POST   |         |          |
| /notice/getList               | POST   |         |          |
| /notice/create                | POST   |         |          |
|                               |        |         |          |

## Patient

| url                                      | method | payload | response |
|:----------------------------------------:|:------:|:-------:|:--------:|
| /appointmentManagement/getList           | POST   |         |          |
| /appointmentManagement/appointmentList   | POST   |         |          |
| /appointmentManagement/create            | POST   |         |          |
| /appointmentManagement/cancel            | POST   |         |          |
| /registrationManagement/getList          | POST   |         |          |
| /registrationManagement/registrationList | POST   |         |          |
| /registrationManagement/create           | POST   |         |          |
| /registrationManagement/cancel           | POST   |         |          |
| /chargeManagement/getList                | POST   |         |          |
| /chargeManagement/charge                 | POST   |         |          |
| /inpectionManagement/getList             | POST   |         |          |
|                                          |        |         |          |

## Doctor

| url                                   | method | payload | response |
|:-------------------------------------:|:------:|:-------:|:--------:|
| /doctorManagement/register            | POST   |         |          |
| /doctorScheduleManagement/register    | POST   |         |          |
| /doctorScheduleManagement/getList     | POST   |         |          |
| /pharmaceuticalManagement/create      | POST   |         |          |
| /pharmaceuticalManagement/getList     | POST   |         |          |
| /pharmaceuticalManagement/stock_query | POST   |         |          |
| /prescriptionManagement/getList       | POST   |         |          |
| /prescriptionManagement/create        | POST   |         |          |
|                                       |        |         |          |

## 