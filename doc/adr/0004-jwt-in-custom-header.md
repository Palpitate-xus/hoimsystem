# ADR-0004: JWT 放在自定义 accesstoken 头

Date: 2026-05-03
Status: Accepted

## Context

需要选择 JWT 的传输方式。常见做法有：
- `Authorization: Bearer <token>` 头（标准）
- Cookie（HTTPOnly 防 XSS）
- 自定义 header（如 `accesstoken: <token>`）
- URL 参数（不推荐）

## Decision

使用自定义头 **`accesstoken: <JWT>`** 传输 token。

## Alternatives Considered

### 方案 A：Authorization: Bearer

**优点：**
- 标准做法，工具支持好（Postman、Swagger 自动认）
- 符合 RFC 6750

**缺点：**
- 浏览器某些情况会自动加 `Authorization` 头（如 basic auth），可能冲突
- 部分 CDN/代理会过滤或修改 `Authorization` 头
- 与历史代码不兼容（项目早期就用了 `accesstoken`）

### 方案 B：Cookie

**优点：**
- HTTPOnly 可以防 XSS 盗 token
- 自动携带，前端不用手动加

**缺点：**
- CSRF 风险（需要额外 CSRF token）
- 跨域要配置 SameSite
- 客户端调试不方便
- 不支持移动端/桌面客户端的 SDK（如未来扩展）

### 方案 C：URL 参数

**绝对不要**。会被记录到日志、被浏览器历史保存。

### 方案 D：自定义 accesstoken 头 ✅

**优点：**
- 不与浏览器自动行为冲突
- 不被 CDN 过滤
- 与前端代码、Swagger 调试都兼容
- 历史上已经在用，迁移成本为 0

**缺点：**
- 非标准做法，新人需要文档说明
- 不能用浏览器的 basic auth 弹窗

## Consequences

### Positive（好处）
- 与现有代码兼容
- 不与浏览器自动行为冲突
- 前端拦截器统一注入，开发体验好

### Negative（坏处）
- 偏离标准（Bearer Token）
- 工具（如 Postman）需要手动配置 header

### Neutral
- 未来若要标准化，可以在中间件中同时支持 `accesstoken` 和 `Authorization` 头

## 实现细节

### 后端（FastAPI）

```python
# app/dependencies.py
def get_current_user(
    accesstoken: str = Header(None),
    db: Session = Depends(get_db)
):
    if not accesstoken:
        raise HTTPException(401, "Missing accesstoken header")

    username = decode_access_token(accesstoken)
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(401, "Invalid token")
    return user


# 路由使用
@router.get("/patient/list")
def list(current_user: User = Depends(get_current_user)):
    ...
```

### 前端（Axios）

```javascript
// src/utils/request.js
service.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers["accesstoken"] = token;
  }
  return config;
});
```

### CORS 配置

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_headers=[..., "accesstoken"],  # 必须显式允许
)
```

## 未来改进

如果需要兼容标准 `Bearer`：

```python
def get_current_user(
    accesstoken: str = Header(None),
    authorization: str = Header(None),
):
    token = accesstoken
    if not token and authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    # ...
```

## References

- [RFC 6750: The OAuth 2.0 Authorization Framework: Bearer Token Usage](https://datatracker.ietf.org/doc/html/rfc6750)
- [JWT Best Practices](https://datatracker.ietf.org/doc/html/rfc8725)
