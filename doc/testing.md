# 测试指南

> 本文档说明如何为项目编写和运行测试，包括后端 API 测试、单元测试和前端测试。

---

## 一、测试策略

```
                  ┌──────────────────┐
                  │   E2E 测试         │   少量 (10%)
                  │   Playwright/手工   │   核心业务流程
                  └─────────┬──────────┘
                            │
            ┌───────────────┴────────────────┐
            │   接口集成测试                    │  适量 (30%)
            │   pytest + TestClient           │  API 行为
            └───────────────┬────────────────┘
                            │
            ┌───────────────┴────────────────┐
            │   单元测试                       │  大量 (60%)
            │   pytest                       │  工具函数、纯逻辑
            └────────────────────────────────┘
```

**测试金字塔原则**：
- 单元测试多而快，覆盖业务规则
- 集成测试中等，覆盖 API 行为
- E2E 测试少而精，覆盖核心闭环

---

## 二、后端测试

### 2.1 测试框架

- **pytest** — 测试框架
- **TestClient** — FastAPI 提供，模拟 HTTP 请求
- **pytest-asyncio** — 异步测试（如需要）

### 2.2 目录结构

```
fastapi_be/
├── app/
└── tests/
    ├── __init__.py
    ├── conftest.py             # pytest fixtures
    ├── test_user.py            # 用户/登录测试
    ├── test_patient.py         # 患者管理测试
    ├── test_doctor.py          # 医生工作站测试
    └── test_*.py
```

### 2.3 conftest.py 示例

```python
# fastapi_be/tests/conftest.py
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, get_db


# 测试数据库（内存 SQLite，每次测试独立）
SQLALCHEMY_TEST_URL = "sqlite:///./test_pytest.db"
engine = create_engine(SQLALCHEMY_TEST_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(scope="function")
def db():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def admin_token(client):
    """登录获取管理员 token"""
    # 先创建管理员用户
    client.post("/api/register", json={
        "username": "test_admin",
        "password": "admin123",
        "user_role": "admin",
    })
    # 登录
    response = client.post("/api/login", json={
        "username": "test_admin",
        "password": "admin123",
    })
    return response.json()["data"]["accesstoken"]
```

### 2.4 编写测试用例

#### 单元测试示例

```python
# tests/test_utils.py
from app.utils import format_phone, mask_identity


def test_format_phone():
    assert format_phone("13800138000") == "138-0013-8000"
    assert format_phone("") == ""


def test_mask_identity():
    assert mask_identity("110101199001011234") == "110101********1234"
    assert mask_identity("") == ""
```

#### 接口测试示例

```python
# tests/test_patient.py
def test_create_patient(client, admin_token):
    response = client.post(
        "/api/patientManagement/create",
        json={"name": "张三", "sex": 1, "phone": "13800138000"},
        headers={"accesstoken": admin_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["code"] == 200
    assert data["data"]["name"] == "张三"


def test_get_patient_list(client, admin_token):
    # 先创建测试数据
    for i in range(3):
        client.post(
            "/api/patientManagement/create",
            json={"name": f"患者{i}", "sex": i % 2},
            headers={"accesstoken": admin_token},
        )

    # 查询列表
    response = client.get(
        "/api/patientManagement/getList",
        headers={"accesstoken": admin_token},
    )
    assert response.status_code == 200
    assert len(response.json()["data"]) == 3


def test_create_patient_missing_name(client, admin_token):
    """异常路径：缺少必填字段"""
    response = client.post(
        "/api/patientManagement/create",
        json={"sex": 1},
        headers={"accesstoken": admin_token},
    )
    assert response.json()["code"] == 500
```

### 2.5 API 全量测试脚本（已提供）

项目已提供基于 `requests` 的全量 API 测试脚本，无需 pytest 即可运行：

```bash
# 1. 确保后端正在运行
cd fastapi_be && uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. 运行测试
python tests/api/test_all_endpoints.py

# 3. 查看结果
cat tests/api/test_results.json    # 机器可读
less doc/api-test-report.md        # 人类可读
```

**测试覆盖**：
- 188 个测试用例，覆盖 248 个 API 端点
- 正常路径、错误参数、不存在 ID、空数据、边界值
- 认证/未授权访问测试

**最新结果**：180/188 通过（95.7%），详见 [api-test-report.md](api-test-report.md)。

#### 业务流程测试示例

```python
def test_appointment_flow(client, admin_token):
    """测试完整预约流程：挂号→报到→分配队列号"""
    # 1. 创建患者
    patient_res = client.post("/api/patientManagement/create",
        json={"name": "测试患者", "sex": 1, "identity": "110101199001011234"},
        headers={"accesstoken": admin_token})
    patient_id = patient_res.json()["data"]["id"]

    # 2. 预约挂号
    appt_res = client.post("/api/appointmentManagement/create",
        json={"id": 1, "doctor_id": 1, "department_id": 1, ...},
        headers={"accesstoken": admin_token})
    assert appt_res.json()["code"] == 200

    # 3. 报到签到
    checkin_res = client.post("/api/checkIn/checkIn",
        json={"appointment_uuid": ..., "identity": "110101199001011234"})
    assert checkin_res.json()["code"] == 200
    assert "queue_no" in checkin_res.json()["data"]
```

### 2.5 运行测试

```bash
cd fastapi_be
source venv/bin/activate

# 运行所有测试
pytest

# 运行指定文件
pytest tests/test_patient.py

# 运行指定测试
pytest tests/test_patient.py::test_create_patient

# 详细输出
pytest -v

# 显示 print 输出
pytest -s

# 失败时停止
pytest -x

# 并行运行（需要 pytest-xdist）
pytest -n auto

# 覆盖率（需要 pytest-cov）
pytest --cov=app --cov-report=html
```

### 2.6 测试覆盖率

目标覆盖率：
- 核心业务模块（patient/doctor/charge）：≥ 70%
- 工具函数：≥ 90%
- 整体：≥ 60%

```bash
pip install pytest-cov
pytest --cov=app --cov-report=term-missing --cov-report=html

# 打开 HTML 报告
open htmlcov/index.html
```

---

## 三、前端测试

### 3.1 测试框架

可选方案：

| 框架 | 用途 | 状态 |
|:----:|:----|:----:|
| Vitest | 单元测试（Vue 3 配套） | 推荐 |
| Vue Test Utils | 组件测试 | 推荐 |
| Playwright | E2E 测试 | 推荐 |
| Cypress | E2E 测试 | 备选 |

### 3.2 安装依赖

```bash
cd vue3-new-ui

# 单元测试
npm install -D vitest @vue/test-utils jsdom

# E2E 测试
npm install -D @playwright/test
npx playwright install
```

### 3.3 单元测试示例

```javascript
// tests/utils.spec.js
import { describe, it, expect } from "vitest";
import { maskIdentity, formatPhone } from "@/utils/format";

describe("maskIdentity", () => {
  it("masks middle digits", () => {
    expect(maskIdentity("110101199001011234")).toBe("110101********1234");
  });

  it("returns empty for null/empty", () => {
    expect(maskIdentity("")).toBe("");
    expect(maskIdentity(null)).toBe("");
  });

  it("returns original for short string", () => {
    expect(maskIdentity("123")).toBe("123");
  });
});
```

### 3.4 组件测试示例

```javascript
// tests/components/VabPageHeader.spec.js
import { describe, it, expect } from "vitest";
import { mount } from "@vue/test-utils";
import VabPageHeader from "@/components/VabPageHeader.vue";

describe("VabPageHeader", () => {
  it("renders title and description", () => {
    const wrapper = mount(VabPageHeader, {
      props: { title: "患者管理", description: "维护患者档案" },
    });
    expect(wrapper.text()).toContain("患者管理");
    expect(wrapper.text()).toContain("维护患者档案");
  });
});
```

### 3.5 E2E 测试示例

```javascript
// tests/e2e/login.spec.js
import { test, expect } from "@playwright/test";

test("admin can login and see dashboard", async ({ page }) => {
  await page.goto("http://localhost:8091");
  await page.fill('input[placeholder*="账号"]', "admin");
  await page.fill('input[placeholder*="密码"]', "admin123");
  await page.click('button:has-text("登录")');

  // 等待跳转到首页
  await expect(page.locator("text=今日门诊概览")).toBeVisible();
});


test("patient appointment flow", async ({ page }) => {
  // 1. 登录
  await page.goto("http://localhost:8091");
  await page.fill('input[placeholder*="账号"]', "patient1");
  await page.fill('input[placeholder*="密码"]', "patient123");
  await page.click('button:has-text("登录")');

  // 2. 进入预约挂号
  await page.click("text=预约挂号");

  // 3. 点击挂号按钮
  await page.click('button:has-text("预约挂号")');

  // 4. 选择号源
  await page.click("table tbody tr:first-child button");

  // 5. 验证成功
  await expect(page.locator("text=预约成功")).toBeVisible();
});
```

### 3.6 运行前端测试

```bash
# 单元测试
npm run test                  # 一次性
npm run test:watch            # 监听模式

# E2E 测试
npm run test:e2e              # 命令行
npm run test:e2e:ui           # UI 模式
```

需要在 `package.json` 中配置：

```json
{
  "scripts": {
    "test": "vitest run",
    "test:watch": "vitest",
    "test:e2e": "playwright test",
    "test:e2e:ui": "playwright test --ui"
  }
}
```

---

## 四、测试数据管理

### 4.1 测试数据生成

后端项目根目录有数据生成脚本：

```bash
cd fastapi_be

# 生成基础数据（科室、医生、患者、药品等）
python -m tests.gen_test_data

# 生成业务数据（预约、处方、就诊等）
python -m tests.gen_business_data
```

### 4.2 测试账号

测试用账号统一：

| 用户名 | 密码 | 角色 |
|:------|:-----|:----|
| test_admin | admin123 | admin |
| test_doctor | doctor123 | doctor |
| test_patient | patient123 | patient |

### 4.3 数据库重置

```bash
# 开发环境（SQLite）
rm fastapi_be/test.db

# 测试环境（独立 DB）
# conftest.py 中已配置每个测试函数独立的内存数据库
```

---

## 五、CI/CD 测试

### 5.1 GitHub Actions 配置

`.github/workflows/test.yml`：

```yaml
name: Tests

on:
  push:
    branches: [master, develop]
  pull_request:
    branches: [master]

jobs:
  backend-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - name: Install dependencies
        run: |
          cd fastapi_be
          pip install -r requirements.txt
          pip install pytest pytest-cov
      - name: Run tests
        run: |
          cd fastapi_be
          pytest --cov=app --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v3

  frontend-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
      - name: Install dependencies
        run: |
          cd vue3-new-ui
          npm install --legacy-peer-deps
      - name: Build
        run: |
          cd vue3-new-ui
          npm run build
```

---

## 六、测试最佳实践

### 6.1 命名

- 测试文件：`test_*.py` 或 `*.spec.js`
- 测试函数：`test_<被测对象>_<场景>_<预期>`

```python
def test_create_patient_with_valid_data_returns_200():
    ...

def test_create_patient_without_name_returns_500():
    ...
```

### 6.2 AAA 模式

每个测试遵循 Arrange-Act-Assert：

```python
def test_xxx():
    # Arrange: 准备数据
    data = {"name": "测试"}

    # Act: 执行被测代码
    response = client.post("/api/xxx", json=data)

    # Assert: 验证结果
    assert response.json()["code"] == 200
```

### 6.3 一个测试只验证一件事

❌ **不推荐：**
```python
def test_patient_crud():
    # 创建
    client.post(...)
    # 查询
    client.get(...)
    # 更新
    client.post(...)
    # 删除
    client.post(...)
```

✅ **推荐：**
```python
def test_create_patient(): ...
def test_get_patient_by_id(): ...
def test_update_patient(): ...
def test_delete_patient(): ...
```

### 6.4 使用 fixture 复用

```python
@pytest.fixture
def sample_patient(client, admin_token):
    response = client.post(...)
    return response.json()["data"]


def test_update_patient(client, admin_token, sample_patient):
    patient_id = sample_patient["id"]
    # ...
```

---

## 七、当前测试现状

> ⚠️ **本项目当前测试覆盖度较低**，建议优先补充以下测试：

- [ ] **核心业务流程 E2E**：登录、预约挂号、收费、发药 4 个流程
- [ ] **关键 API 测试**：login、create_patient、create_prescription
- [ ] **关键工具函数**：maskIdentity、parse_action_target、JWT decode
- [ ] **权限校验**：未登录访问应返回 401，越权访问应返回 403/500

详细 todo 见 [todos.md](todos.md)。

---

## 八、参考资料

- [pytest 文档](https://docs.pytest.org/)
- [FastAPI TestClient](https://fastapi.tiangolo.com/tutorial/testing/)
- [Vitest](https://vitest.dev/)
- [Vue Test Utils](https://test-utils.vuejs.org/)
- [Playwright](https://playwright.dev/)
