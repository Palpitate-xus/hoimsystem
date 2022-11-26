# 医院门诊信息管理系统
[中文](README.md) [English](README.en.md)
## 如何运行
- 运行前端
``` bash
    cd vue-ui
    npm i
    npm run serve
```
- 运行后端（以Windows系统为例）
``` bash
    cd django_be
    pip install -r requirement.txt
    python manage.py makemigration
    python manage.py migrate
    python manage.py runserver
```

## 架构
- 前端
    - Vue2.x
    - Element-ui
- 后端
    - Django

## 开发环境
- Windows 11 22H2
- Python 3.7.3
- Node.js v16.18.1
- MySQL 8.0.31