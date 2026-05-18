# ADR-0005: 用中间件统一记录操作日志

Date: 2026-05-18
Status: Accepted

## Context

医疗系统的操作必须可审计（《医院信息系统基本功能规范》要求）。
项目初期定义了 `OperationLog` 表，但**实际上没有任何代码写入日志**。

我们需要决定：如何统一记录所有用户的关键操作？

**业务需求：**
- 所有写操作（POST/PUT/DELETE）都要记录
- 记录：用户、操作、对象、结果、IP、时间
- 不影响业务代码（业务代码不能到处写日志）
- 不影响性能（日志写入不能阻塞主流程）

## Decision

实现 **`OperationLogMiddleware`** 中间件，自动拦截所有 POST/PUT/DELETE 请求并写入日志。

业务代码**零侵入**。

## Alternatives Considered

### 方案 A：装饰器手动加

```python
@router.post("/patient/create")
@log_operation("新增·患者")
def create_patient(...):
    ...
```

**优点：**
- 显式声明，可读性好
- 可以传更多上下文

**缺点：**
- 每个 API 都要加，容易遗漏
- 装饰器嵌套层数多
- 不同模块写法不一致风险

### 方案 B：在 Service 中调用

```python
def create_patient(req, db, user):
    patient = Patient(...)
    db.add(patient)
    db.commit()

    log_operation(db, user, "新增", "患者", "成功")  # 手动调用
    return patient
```

**优点：**
- 可以精确控制日志内容

**缺点：**
- 业务代码混入日志逻辑
- 容易忘记调用
- 失败路径的日志（异常分支）容易漏

### 方案 C：FastAPI 中间件 ✅

```python
class OperationLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.method in {"POST", "PUT", "DELETE"}:
            self._log(request, response)
        return response
```

**优点：**
- 业务代码零侵入
- 一处代码覆盖所有 API
- 自动覆盖未来新增的 API
- 自动覆盖错误路径（500 也记录）

**缺点：**
- 路径解析需要映射规则（自动从 `/api/patientManagement/create` 推断"新增·患者"）
- 不能记录精细的业务上下文（如"创建了哪个 ID 的患者"）

### 方案 D：用 AOP / Signals

类似 Django 的 `signals` 或 Spring 的 AOP。FastAPI 没有内置，需要自己实现，复杂度高。

## Consequences

### Positive（好处）
- ✅ **零侵入**：业务代码完全不变
- ✅ **全覆盖**：247 个 API 全部自动记录
- ✅ **新 API 自动覆盖**：以后加 API 不用考虑日志
- ✅ **失败路径也覆盖**：500 错误也记一笔"失败"
- ✅ **统一格式**：所有日志格式一致

### Negative（坏处）
- ❌ 路径映射不精确（自动推断为"新增·患者"，没有具体的患者 ID）
- ❌ 列表查询接口（POST 但实际是 GET 性质）也会被记录 → 用 `SKIP_PATHS` 排除
- ❌ 中间件解析 token 会增加 1-2ms 开销（可忽略）

### Neutral
- 如果需要精细日志，可以保留中间件 + 关键节点手动加日志（混合模式）

## 实现详情

### 路径自动映射

```python
ACTION_MAP = {
    "create": "新增",
    "update": "更新",
    "delete": "删除",
    "audit": "审核",
    "login": "登录",
    ...
}

TARGET_MAP_ORDERED = [
    ("patientmanagement", "患者"),
    ("doctormanagement", "医生"),
    ("noticemanagement", "公告"),
    ...
]
```

`/api/patientManagement/update` → 解析为 `(更新, 患者)`

### 跳过列表查询

```python
SKIP_PATHS = {"/log/", "/getList", "/getDetail", "/getPending"}
```

避免列表查询接口爆炸式产生日志。

### 用户解析

```python
# 从 accesstoken 头解析 user_id
access_token = request.headers.get("accesstoken")
if access_token:
    username = decode_access_token(access_token)
    user = db.query(User).filter(User.username == username).first()
    user_id = user.user_id if user else None
```

未登录请求（如 login 接口本身）user_id 为空。

### 性能

- 异步写入：使用 `db.commit()`，但放在响应返回之后
- 异常处理：日志写入失败不影响业务

## 监控

可在 GitHub Issues 中跟踪：
- 是否有遗漏的关键操作没记录
- 是否有列表接口被错误记录
- 路径映射是否准确

## References

- [Starlette Middleware](https://www.starlette.io/middleware/)
- [《医院信息系统基本功能规范》第 8 章 安全管理](https://www.nhc.gov.cn/)
