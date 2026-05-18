# 编码规范

> 本文档定义项目的代码风格、命名约定、注释规则、文件组织等约定。
> 所有提交的代码应遵循本规范，PR 评审时也会以此为依据。

---

## 一、通用原则

1. **代码可读性 > 简短性** — 别人能看懂的代码胜过短小精悍但难懂的代码
2. **一致性 > 个人喜好** — 全项目代码风格保持一致，避免风格混乱
3. **明确意图** — 变量、函数、类的名字应该清楚表达"是什么/做什么"
4. **避免过度抽象** — 三处相似代码可以重复，五处以上再抽象
5. **不写废注释** — 代码已经清晰表达的内容，不需要注释重复
6. **错误显式处理** — 不忽略异常，至少要 log 出来

---

## 二、后端 Python 规范

### 2.1 代码风格

- 遵循 **PEP 8** 默认规范
- 使用 **ruff** 作为 linter 和 formatter
- 行长度限制：**120** 字符（比 PEP 8 默认的 79 宽松）

```bash
# 自动格式化
cd fastapi_be
ruff check . --fix
ruff format .
```

### 2.2 命名约定

| 类型 | 规则 | 示例 |
|:----:|:----|:----|
| 模块/文件 | 小写下划线 | `inpatient_order.py` |
| 类 | 大驼峰 | `class OrderExecution` |
| 函数/方法 | 小写下划线 | `def get_patient_list()` |
| 变量 | 小写下划线 | `patient_id = 1` |
| 常量 | 全大写下划线 | `MAX_RETRY_COUNT = 3` |
| 私有 | 单下划线前缀 | `_internal_helper()` |
| 数据库表 | `hoimsystem_` 前缀 + 小写下划线 | `hoimsystem_operation_log` |

### 2.3 类型注解

**必须使用类型注解**，特别是函数签名：

```python
# ✅ 正确
def get_patient(patient_id: int, db: Session) -> Patient | None:
    return db.query(Patient).filter(Patient.patient_id == patient_id).first()

# ❌ 不推荐
def get_patient(patient_id, db):
    return db.query(Patient).filter(Patient.patient_id == patient_id).first()
```

Pydantic 模型使用 v2 语法：

```python
class PatientCreateRequest(BaseModel):
    name: str
    sex: int  # 0=女 1=男
    phone: str | None = None
    birthday: datetime.date | None = None
```

### 2.4 FastAPI 路由约定

```python
# ✅ 标准路由模板
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db

router = APIRouter()


@router.post("/yourModule/create")
def create_xxx(req: YourCreateRequest, db: Session = Depends(get_db)):
    # 1. 业务校验
    if not req.field_a:
        return {"code": 500, "msg": "字段A不能为空"}

    # 2. 数据库操作
    obj = YourModel(**req.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)

    # 3. 统一响应
    return {"code": 200, "msg": "success", "data": {"id": obj.id}}
```

### 2.5 SQLAlchemy 模型约定

```python
class Patient(Base):
    __tablename__ = "hoimsystem_patient"

    patient_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    sex = Column(Integer, default=0, comment="0=女 1=男")
    birthday = Column(Date, nullable=True)
    create_time = Column(DateTime, default=datetime.datetime.now)

    # 关联
    appointments = relationship("Appointment", back_populates="patient")
```

**字段约定：**
- 主键：`{表名}_id`，使用 Integer + autoincrement
- 时间字段：`create_time` / `update_time`
- 状态字段：`status`（Integer），用注释或常量映射含义
- 软删除：不推荐，需要时用 `is_deleted = Column(Integer, default=0)`

### 2.6 响应结构

**所有 API 返回统一结构：**

```python
# 成功
{"code": 200, "msg": "success", "data": {...}}

# 失败（业务异常，不抛 HTTP 错误）
{"code": 500, "msg": "用户不存在"}

# 分页
{"code": 200, "msg": "success", "data": {"list": [...], "total": 100}}
```

> ⚠️ 不要用 `raise HTTPException(404)`，统一返回 200 + 业务 code。

### 2.7 注释规范

**何时写注释：**
- 复杂业务逻辑（解释 *为什么*，不是 *做什么*）
- 非显而易见的状态码、魔数（如 `status=0` 是什么状态）
- 字段含义不明（用 `comment` 参数或文档字符串）

**何时不写注释：**
- 显而易见的变量赋值
- 已经被命名清楚表达的函数

```python
# ✅ 好的注释
# 三次违约自动暂停 30 天，参考违约处理需求 PRD-2024-A
breach_threshold = 3
suspend_days = 30

# ❌ 废话注释
# 获取患者ID
patient_id = req.patient_id
```

---

## 三、前端 Vue 规范

### 3.1 代码风格

- 使用 **Prettier** 格式化
- 缩进：**2 空格**
- 字符串：**双引号**
- 行末分号：**保留**
- 行长度：**100** 字符

### 3.2 命名约定

| 类型 | 规则 | 示例 |
|:----:|:----|:----|
| 组件文件 | 小驼峰或大驼峰 | `inpatientOrder.vue` 或 `InpatientOrder.vue` |
| 组件名称 | 大驼峰（PascalCase） | `<el-table>`、`<VabPageHeader>` |
| 变量/函数 | 小驼峰 | `const patientList = ref([])` |
| 常量 | 全大写 | `const MAX_PAGE_SIZE = 100` |
| CSS 类名 | 小写连字符 | `.page-toolbar` |
| 路由 path | 小驼峰 | `/patient/healthRecord` |
| API 函数 | 小驼峰 | `getPatientList()` |

### 3.3 Vue 3 组件模板

```vue
<template>
  <div class="app-container">
    <vab-page-header title="页面标题" description="功能简述" />
    <el-card>
      <!-- 顶部工具栏 -->
      <div class="page-toolbar">
        <el-button type="primary" @click="handleAdd">新增</el-button>
        <el-input v-model="searchQuery" placeholder="搜索患者" class="page-search-input" />
        <el-button type="primary" @click="fetchList">搜索</el-button>
      </div>

      <!-- 表格 -->
      <el-table :data="paginatedList" v-loading="loading" empty-text="暂无数据" border>
        <el-table-column prop="name" label="姓名" sortable />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" @click="handleEdit(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <el-pagination
        v-model:current-page="currentPage"
        :total="total"
        layout="total, prev, pager, next"
        class="pagination-wrapper"
      />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from "vue";
import { ElMessage } from "element-plus";
import { getPatientList } from "@/api/patient";

const list = ref([]);
const loading = ref(false);
const searchQuery = ref("");
const currentPage = ref(1);
const pageSize = ref(10);

const total = computed(() => list.value.length);
const paginatedList = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return list.value.slice(start, start + pageSize.value);
});

const fetchList = async () => {
  loading.value = true;
  try {
    const res = await getPatientList(searchQuery.value);
    list.value = res.data || [];
  } catch (e) {
    ElMessage.error(e.msg || "查询失败");
  }
  loading.value = false;
};

onMounted(fetchList);
</script>
```

### 3.4 必备 UX 元素

每个列表页**必须**包含：

- ✅ `vab-page-header`（含 description）
- ✅ `<el-table>` 含 `empty-text` 和 `v-loading`
- ✅ 分页（如果数据可能 > 10 条）
- ✅ 操作按钮（新增/编辑/删除）
- ✅ 搜索框（带具体 placeholder，不要"搜索..."）

**避免的反模式：**

- ❌ 直接显示 `prop="id"` 数字 ID 给用户
- ❌ 显示 UUID 给用户
- ❌ 表单中让用户手动输入患者ID/医生ID（应该用 `<el-select>` 下拉）
- ❌ 显示完整身份证号（必须用 `maskIdentity()` 脱敏）
- ❌ 用 `style="width: 200px"` 等内联样式（用工具类 `class="page-search-input"`）

### 3.5 全局样式工具类

```scss
.page-toolbar              // 页面顶部操作栏
.page-search-input         // 搜索输入框（220px 宽）
.pagination-wrapper        // 分页容器（右对齐）
.form-full-width           // 表单元素 100% 宽度
.dialog-form               // 对话框表单统一样式
```

定义位置：[vue3-new-ui/src/styles/vab.scss](../vue3-new-ui/src/styles/vab.scss)

### 3.6 API 调用约定

```javascript
// vue3-new-ui/src/api/patient.js
import request from "@/utils/request";

export function getPatientList(keyword = "") {
  return request({
    url: "patientManagement/getList",
    method: "get",
    params: { keyword },
  });
}

export function createPatient(data) {
  return request({
    url: "patientManagement/create",
    method: "post",
    data,
  });
}
```

请求拦截器统一处理 `accesstoken` 注入和错误响应：
[vue3-new-ui/src/utils/request.js](../vue3-new-ui/src/utils/request.js)

---

## 四、数据库规范

### 4.1 表命名

- 统一前缀：`hoimsystem_`
- 单数形式：`hoimsystem_patient`（不是 patients）
- 全小写下划线：`hoimsystem_inpatient_order`

### 4.2 字段命名

- 主键：`{表名简称}_id`（如 `patient_id`、`doctor_id`）
- 外键：与被引用表的主键同名
- 时间：`{动词}_time`（如 `create_time`、`audit_time`）
- 状态：`status`（Integer），用文档说明含义
- 状态文本：`status_text`（仅用于 API 响应，不入库）

### 4.3 状态码约定

参考主流业务系统：
- `0` — 初始/待处理
- `1` — 已审核/进行中/启用
- `2` — 已完成/结束
- `3` — 已取消/废弃
- `4+` — 业务自定义

具体含义在模型类的 `comment` 字段或 `schemas.py` 中说明。

---

## 五、Git 规范

### 5.1 Commit Message

遵循 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/v1.0.0/)：

```
<type>: <description>

[可选 body]

[可选 footer，含 Co-Authored-By 等]
```

**type 取值：**
- `feat` — 新功能
- `fix` — 修复 bug
- `docs` — 文档变更
- `style` — 格式调整（不影响逻辑）
- `refactor` — 重构（既非新功能也非修复）
- `perf` — 性能优化
- `test` — 测试相关
- `chore` — 构建/工具/依赖等杂项

**示例：**

```
feat: 新增手术麻醉管理模块

实现手术申请、排台、麻醉记录的完整流程，
包含 12 个 API 和 3 个前端页面。

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

### 5.2 分支命名

- `feature/xxx` — 新功能开发
- `fix/xxx` — bug 修复
- `docs/xxx` — 仅文档变更
- `refactor/xxx` — 重构
- `hotfix/xxx` — 紧急生产修复

详细 Git 工作流见 [git-workflow.md](git-workflow.md)。

---

## 六、自动化检查

### 6.1 后端 Lint

```bash
cd fastapi_be
ruff check .              # 检查
ruff check . --fix        # 自动修复
ruff format .             # 格式化
```

### 6.2 前端 Lint

```bash
cd vue3-new-ui
npm run lint               # 如果配置了
npm run format             # 如果配置了
```

### 6.3 Pre-commit Hook（推荐）

```bash
# 安装 pre-commit
pip install pre-commit

# 在项目根创建 .pre-commit-config.yaml（如未存在）
# 然后安装 hook
pre-commit install
```

---

## 七、Code Review Checklist

PR 评审时，评审人应至少确认：

- [ ] 代码风格符合本规范
- [ ] 提交信息符合 Conventional Commits
- [ ] 新增 API 已添加到 `apiDoc.md` 或本身自描述
- [ ] 新增表已更新 `databaseDoc.md`
- [ ] 前端页面有 `v-loading` 和 `empty-text`
- [ ] 无敏感信息硬编码（密码、token）
- [ ] 无 console.log / print 调试残留
- [ ] 测试通过（pytest）
- [ ] 不影响现有功能（手动验证关键流程）

---

## 八、关于"避免过度抽象"的提醒

本项目**有意**保持简单：

- **不强制** Service 层 — 简单 CRUD 直接在 router 中操作 ORM
- **不强制** 严格分层 — 业务复杂度低时，少分一层即少一层维护
- **不预先抽象** — 等出现 3 个相似模块再抽象，避免错误抽象
- **不重复造轮子** — 用 FastAPI/SQLAlchemy/Element Plus 提供的标准能力

但**保留**：
- 统一的响应结构 `{code, msg, data}`
- 统一的工具样式类（`.page-toolbar` 等）
- 统一的鉴权和日志中间件

---

## 九、参考资料

- [PEP 8 Python 风格指南](https://peps.python.org/pep-0008/)
- [Vue 3 风格指南](https://vuejs.org/style-guide/)
- [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)
- [FastAPI 最佳实践](https://github.com/zhanymkanov/fastapi-best-practices)
