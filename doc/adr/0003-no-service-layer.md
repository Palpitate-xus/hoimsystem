# ADR-0003: 不强制分 Service 层

Date: 2026-05-01
Status: Accepted

## Context

主流 Web 项目常采用"控制器 → 服务 → 数据访问"三层架构。在 FastAPI 中可能是：

```
router/      # 路由层（控制器）
service/     # 业务逻辑层
repository/  # 数据访问层
model/       # 数据模型
```

我们考虑是否要在本项目中也强制这种分层。

## Decision

**不强制分 Service 层**。简单业务直接在 `router` 中操作 ORM。复杂业务才单独抽取 service 函数。

```
# 当前结构（扁平化）
app/
├── routers/      # 路由 + 业务逻辑
├── models.py     # SQLAlchemy 模型
├── schemas.py    # Pydantic 请求/响应模型
└── ...
```

## Alternatives Considered

### 方案 A：严格三层架构

```python
# router/patient.py
@router.post("/create")
def create_patient(req: PatientCreate, db: Session = Depends(get_db)):
    return patient_service.create(db, req)

# service/patient_service.py
def create(db: Session, req: PatientCreate) -> Patient:
    return patient_repository.create(db, req.model_dump())

# repository/patient_repository.py
def create(db: Session, data: dict) -> Patient:
    obj = Patient(**data)
    db.add(obj)
    db.commit()
    return obj
```

**优点：**
- 关注点分离清晰
- 单元测试容易（mock 各层）
- 适合大型企业项目

**缺点：**
- 简单 CRUD 要写 4 处代码
- 文件数量爆炸（router/service/repository 各一份）
- 增加新人理解成本
- 跨多模块的业务往往要在多个 service 中跳来跳去

### 方案 B：扁平化（router 直接操作 ORM）✅

```python
# router/patient.py
@router.post("/create")
def create_patient(req: PatientCreate, db: Session = Depends(get_db)):
    obj = Patient(**req.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return {"code": 200, "data": {"id": obj.patient_id}}
```

**优点：**
- 简单业务一目了然
- 文件少，导航成本低
- 团队新人易上手

**缺点：**
- 复杂业务逻辑都堆在 router 中可能膨胀
- 业务逻辑跨多个 router 复用时不方便
- 单元测试需要数据库 fixture

### 方案 C：按需抽取（折中）

简单业务扁平化，复杂业务单独抽 service 函数。

## Consequences

### Positive（好处）
- 70% 的 CRUD 业务保持简单（直接 router + ORM）
- 新人 1 天可以上手开始写 API
- 代码总行数减少约 30%（相比严格分层）

### Negative（坏处）
- 复杂业务（如出院结算、闭环医嘱）的 router 函数会变长（100+ 行）
- 跨模块业务逻辑没有统一的抽象层
- 单元测试需要数据库支持（用 SQLite in-memory）

### Neutral
- 大型业务方法可以临时抽到 `app/services/` 目录（如未来需要）
- 不阻止任何团队成员在自己模块内分层

## 何时应该抽 Service？

**抽**：
- 单个 router 函数 > 100 行
- 同一业务逻辑被 3+ 个 router 调用
- 业务包含多步事务（如出院结算涉及 5+ 张表）

**不抽**：
- 简单 CRUD（90% 情况）
- 仅在一处使用
- 逻辑 < 20 行

## 当前项目实践

截至 v1.1.0，34 个 router 模块中：
- **28 个** 是扁平化结构（直接 router + ORM）
- **6 个** 在 router 内部抽取了辅助函数（如 `_resolve_dept_names`）
- **0 个** 单独分 service 文件

事实证明扁平化结构能 cover 大部分场景。

## References

- [FastAPI 最佳实践 by zhanymkanov](https://github.com/zhanymkanov/fastapi-best-practices)
- [Avoid Premature Optimization](https://wiki.c2.com/?PrematureOptimization)
- [YAGNI 原则](https://martinfowler.com/bliki/Yagni.html)
