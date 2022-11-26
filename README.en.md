# Hospital Outpatient Information Management System
[中文](README.md) | [English](README.en.md) | [需求文档](./doc/demandDoc.md) | [数据库文档](./doc/database.md) | [API文档](./doc/api.md) | [TODO](./doc/todos.md)
## How to run
- Run front-end
``` bash
    cd vue-ui
    npm i
    npm run serve
```
- Running the back end (for Windows)
``` bash
    cd django_be
    pip install -r requirement.txt
    python manage.py makemigration
    python manage.py migrate
    python manage.py runserver
```

## System Architecture
- Front End
    - Vue2.x
    - Element-ui
- Back End
    - Django

## Development Environment
- Windows 11 22H2
- Python 3.7.3
- Node.js v16.18.1
- MySQL 8.0.31