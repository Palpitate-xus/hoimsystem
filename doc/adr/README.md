# 架构决策记录（ADR - Architecture Decision Records）

> 本目录记录项目中所有重要的架构决策。
> 每个决策一份文档，便于后续追溯"为什么这么做"。

---

## 什么是 ADR？

ADR 是一种轻量级的决策文档，记录：
- **背景** — 当时面临什么问题
- **决策** — 选择了什么方案
- **替代方案** — 还考虑过哪些方案
- **后果** — 这个决策带来什么好处和坏处

ADR 不是设计文档，而是 **决策的备忘录**。即便决策后来被推翻，原 ADR 也保留，新 ADR 会标记 `Supersedes ADR-XXX`。

---

## ADR 索引

| 编号 | 标题 | 状态 | 日期 |
|:----:|:-----|:----:|:----:|
| [0001](0001-use-fastapi-instead-of-django.md) | 选择 FastAPI 而非 Django | ✅ Accepted | 2026-04-29 |
| [0002](0002-use-sqlite-for-dev.md) | 开发环境使用 SQLite | ✅ Accepted | 2026-04-29 |
| [0003](0003-no-service-layer.md) | 不强制分 Service 层 | ✅ Accepted | 2026-05-01 |
| [0004](0004-jwt-in-custom-header.md) | JWT 放在自定义 accesstoken 头 | ✅ Accepted | 2026-05-03 |
| [0005](0005-operation-log-middleware.md) | 用中间件统一记录操作日志 | ✅ Accepted | 2026-05-18 |

---

## 状态说明

- ✅ **Accepted** — 已采纳，正在使用
- 🚧 **Proposed** — 提议中，待讨论
- ❌ **Rejected** — 被拒绝
- 🗑️ **Deprecated** — 已过时但保留参考
- 🔄 **Superseded** — 被新 ADR 取代

---

## 何时写 ADR？

- ✅ **应该写** — 影响系统结构的决策（如选型、分层、协议）
- ✅ **应该写** — 团队曾经讨论过、有争议的决策
- ✅ **应该写** — 后人可能会问"为什么这样做"的决策
- ❌ **不用写** — 日常 bug 修复
- ❌ **不用写** — 显而易见的最佳实践（如用 Git、用 SQL）

---

## ADR 模板

新建 ADR 时复制 [template.md](template.md)，命名为 `NNNN-short-title.md`（NNNN 是 4 位编号）。

```markdown
# ADR-NNNN: 决策标题

Date: YYYY-MM-DD
Status: Proposed | Accepted | Rejected | Deprecated | Superseded by ADR-XXXX

## Context
当时面临什么问题？业务背景、技术约束、相关需求...

## Decision
我们决定怎么做？

## Alternatives Considered
还考虑过哪些方案？为什么没选？

## Consequences

### Positive（好处）
- ...
- ...

### Negative（坏处）
- ...
- ...

### Neutral（中性）
- ...

## References
- 链接 1
- 链接 2
```

---

## 编号规则

- ADR 按时间顺序编号
- 编号一旦分配不可复用，即使被废弃
- 4 位数字补齐，留出扩展空间（NNNN）
- 文件名小写连字符：`0001-use-fastapi-instead-of-django.md`

---

## 维护约定

- ADR 一旦合并，**不修改决策内容**，只能新建 ADR 推翻它
- 拼写错误、链接修复、格式调整等可以直接修改
- 状态变更（如 Deprecated）可以直接修改
- 新 ADR 推翻旧 ADR 时，旧 ADR 状态改为 "Superseded by ADR-XXXX"

---

## 参考资料

- [Architecture Decision Records (Michael Nygard)](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions.html)
- [ADR Tools](https://github.com/npryce/adr-tools)
- [MADR Template](https://adr.github.io/madr/)
