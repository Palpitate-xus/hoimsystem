# ADR-0002: 开发环境使用 SQLite

Date: 2026-04-29
Status: Accepted

## Context

医院信息系统通常用 SQL Server、Oracle、PostgreSQL 等"重型"数据库。但本项目是一个开源/教学/演示项目，需要降低参与门槛。

**项目需求：**
- 新开发者能 5 分钟内启动整个项目
- 不需要安装额外的数据库服务
- 单元测试不依赖外部服务
- 生产环境仍能切换到 PostgreSQL

## Decision

- **开发环境**：使用 **SQLite**（单文件、零配置）
- **生产环境**：推荐 **PostgreSQL**
- **切换方式**：仅修改 `.env` 中的 `DATABASE_URL`，代码不变

## Alternatives Considered

### 方案 A：开发也用 PostgreSQL

**优点：**
- 开发和生产环境一致，避免"我电脑上能跑"问题
- 可以用 PostgreSQL 特性（JSONB、CTE、窗口函数）

**缺点：**
- 新人需要安装 PostgreSQL + 创建数据库 + 配置环境变量
- 不同开发者的本地数据可能冲突
- 测试用例需要清理数据库，增加复杂度

### 方案 B：开发也用 MySQL

类似 PostgreSQL，但功能稍弱，且需要额外安装。同样的缺点。

### 方案 C：SQLite + 生产 PostgreSQL ✅

**优点：**
- 零安装：Python 标准库内置 SQLite
- 单文件存储，易备份、易重置（`rm test.db` 重来）
- 测试用内存 SQLite，每个测试函数完全隔离
- SQLAlchemy 抽象层屏蔽差异

**缺点：**
- 必须避免使用数据库特有语法（PostgreSQL 的 JSONB、ARRAY 类型不能用）
- 并发写入性能差（开发环境无所谓）
- 部分 ORM 高级特性受限

## Consequences

### Positive（好处）
- 新开发者克隆代码后 5 分钟启动
- CI/CD 测试无需启动数据库容器
- 团队成员的本地数据互不影响

### Negative（坏处）
- 不能用 PostgreSQL 的 JSONB、Array 类型
- 不能用 SQLite 不支持的某些 DDL（如 ALTER COLUMN TYPE）
- 索引、约束行为略有差异，可能在生产环境暴露

### Neutral
- 字段需要更通用：用 `String` 存 JSON 字符串而非 `JSONB`
- 跨数据库迁移用 `pgloader` 或手动脚本

## 编码约定

为保持跨数据库兼容性：
- ❌ 不用 `JSONB`、`ARRAY` 类型 → 用 `String` 存 JSON 字符串
- ❌ 不用 `RETURNING` 子句 → 用 `db.refresh(obj)`
- ❌ 不用 `ILIKE`（PostgreSQL 大小写不敏感）→ 用 `LIKE` + `LOWER()`
- ❌ 不用窗口函数（SQLite 3.25+ 支持，但版本要求高）

## References

- [SQLAlchemy 多方言支持](https://docs.sqlalchemy.org/en/20/dialects/)
- [SQLite vs PostgreSQL 兼容性表](https://www.sqlite.org/whentouse.html)
