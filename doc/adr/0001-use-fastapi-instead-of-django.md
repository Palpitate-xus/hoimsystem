# ADR-0001: 选择 FastAPI 而非 Django

Date: 2026-04-29
Status: Accepted

## Context

项目初期需要选择 Python 后端框架。候选包括：Django、Flask、FastAPI。

**项目需求：**
- 前后端分离，后端只提供 REST API（不渲染页面）
- 需要自动生成 API 文档（医疗系统接口多，文档维护成本高）
- 团队偏好类型注解，希望 IDE 提供较强的代码提示
- 业务模块较多（最终 34 个），需要清晰的模块化能力
- 性能要求：单实例支持中小医院（500-2000 患者/天）

## Decision

选择 **FastAPI** 作为后端框架。

## Alternatives Considered

### 方案 A：Django + DRF

**优点：**
- 生态最成熟，社区资源最多
- 内置 admin、ORM、缓存、表单等"全家桶"
- 团队熟悉度高

**缺点：**
- 同步框架，性能上限较低
- DRF 配置繁琐，序列化器写起来重
- 不支持现代 Python 类型注解
- 自动文档（drf-yasg/spectacular）需要额外配置
- 全家桶反而限制灵活性

### 方案 B：Flask

**优点：**
- 轻量灵活
- 易上手
- 生态成熟

**缺点：**
- 缺少类型注解支持
- 大型项目缺乏结构约定，容易乱
- 自动文档（flasgger）维护成本高
- 异步支持后加（性能不如原生异步框架）

### 方案 C：FastAPI ✅

**优点：**
- 原生类型注解，IDE 提示强
- 自动生成 OpenAPI/Swagger 文档（医疗系统接口多，这点非常重要）
- 性能接近 Go（基于 Starlette + Uvicorn 异步）
- Pydantic 数据校验强大
- 文档质量高，学习曲线友好

**缺点：**
- 生态比 Django 小（但够用）
- 没有内置 admin、auth 等（需自己写或用社区库）
- 团队需要学习类型注解、async/await（学习成本可控）

## Consequences

### Positive（好处）
- 接口文档自动生成，节省至少 30% 的文档维护时间
- 类型注解提升代码质量，IDE 重构能力增强
- 性能足够支撑业务，单实例 ~3000 QPS
- 异步能力为后续 WebSocket、SSE 等留下空间

### Negative（坏处）
- 失去 Django 的全家桶便利（admin 等需要自己写或在前端实现）
- 团队需要学习 Pydantic 和 FastAPI 的 dependency injection
- ORM 选择：手动选 SQLAlchemy（见 [ADR-0002](0002-use-sqlite-for-dev.md)）

### Neutral
- 鉴权需要自己实现 JWT 方案（见 [ADR-0004](0004-jwt-in-custom-header.md)）

## References

- [FastAPI 官方文档](https://fastapi.tiangolo.com/)
- [FastAPI vs Django vs Flask 对比](https://github.com/zhanymkanov/fastapi-best-practices)
