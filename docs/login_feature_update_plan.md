# 简易注册与登录功能更新方案

> 项目编号：XH-202630  
> 文档版本：2.3（MVP 实施版，注册仅三项必填）  
> 文档日期：2026-08-07  
> 文档状态：已实施并完成端到端验证

## 1. 实现目标

登录不是本项目的核心比赛功能，因此只实现满足演示和基础数据隔离的最小版本：

- 支持用户名、密码登录。
- 支持用户自行注册，注册成功后自动登录。
- 支持刷新页面后保持登录。
- 支持退出登录。
- 未登录不能进入业务页面。
- 登录后默认使用当前用户，不再让普通用户切换其他用户。
- 用户只能看到自己的学习方向和学习历史。

暂不实现：

- 找回密码和修改密码。
- 手机号、验证码和第三方登录。
- 多角色权限和管理员后台。
- 登录失败锁定和复杂风控。
- Refresh Token、服务端会话表和多设备管理。

## 2. 简化后的整体方案

直接扩展现有 `users` 表，不新增 `auth_accounts` 和 `auth_sessions`：

```text
注册：用户名 + 密码 + 确认密码 -> POST /api/auth/register -> 创建 users
登录：用户名 + 密码 -> POST /api/auth/login -> 校验 users.password_hash
-> 签发短期 JWT
-> JWT 写入 HttpOnly Cookie
-> 后续请求从 Cookie 识别当前用户
```

登录状态只使用一个短期 JWT Cookie：

- JWT 默认有效期建议 8 小时，满足比赛演示。
- Cookie 使用 `HttpOnly`，前端 JavaScript 不直接读取令牌。
- 开发环境允许 HTTP；生产环境启用 `Secure` 并使用 HTTPS。
- 退出时清除 Cookie。
- 不建立会话表，因此令牌在过期前不能被服务端单独撤销；该限制对当前演示版本可以接受。

## 3. 当前数据现状

当前本地运行配置实际使用：

```text
backend/data/domain_knowledge_writable_probe.db
```

而 `backend/.env.example` 默认配置仍是：

```text
backend/data/domain_knowledge.db
```

实施前必须先确认正式使用哪个数据库文件，并只迁移该文件。

实施前活跃数据库的相关数据基线：

| 表 | 记录数 | 说明 |
|---|---:|---|
| `users` | 1 | 已有用户资料，但没有用户名和密码 |
| `learner_profiles` | 5 | 表中没有正式的 `user_id` 字段 |
| `questionnaire_submissions` | 16 | 通过 `learner_id` 关联画像 |
| `diagnostic_runs` | 6 | 通过 `learner_id` 关联画像 |
| `generation_jobs` | 9 | 通过 `learner_id` 关联画像 |
| `generated_resources` | 3 | 通过 `learner_id` 关联画像 |
| `feedback_records` | 2 | 通过 `learner_id` 关联画像 |

5 条学习画像中：

- 2 条可以从现有 JSON 元数据自动关联到用户。
- 3 条无法自动确认归属，需要人工指定、作为演示旧数据保留，或清理后重新生成。

## 4. 数据表变化

### 4.1 修改 `users` 表

在现有用户资料表中增加登录字段：

| 新字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `username` | `VARCHAR(64)` | UNIQUE, NULLABLE | 登录用户名；去除首尾空格并统一转小写，旧数据迁移阶段允许为空 |
| `password_hash` | `VARCHAR(512)` | NULLABLE | Argon2id 密码哈希，不保存明文密码 |
| `is_active` | `BOOLEAN` | NOT NULL, default `1` | 是否允许登录 |
| `last_login_at` | `DATETIME` | NULLABLE | 最近登录时间 |

说明：

- `username` 和 `password_hash` 初次迁移允许为空，避免破坏当前已有用户。
- 只有同时设置了用户名和密码哈希的用户才能登录。
- 新注册用户由后端自动生成 `user_id`，并在同一事务中保存资料和密码哈希。
- 用户资料 API 响应中绝不能返回 `password_hash`。
- 当前只有 1 条用户记录，可通过一次性初始化脚本设置用户名和密码。

SQLite 兼容迁移需要在 `backend/app/db/database.py` 增加：

```text
users.username
users.password_hash
users.is_active
users.last_login_at
```

### 4.2 修改 `learner_profiles` 表

增加一个用于数据归属的字段：

| 新字段 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `user_id` | `VARCHAR(64)` | NULLABLE, INDEX | 所属用户 ID，关联 `users.user_id` |

第一版保持 `NULLABLE`，原因是当前有 3 条画像无法自动归属。新建学习方向时必须写入当前登录用户的 `user_id`。

回填规则：

1. 优先读取 `learning_preferences.metadata.user_id`。
2. 仅当该 ID 确实存在于 `users` 时写入新字段。
3. 无法确认的旧画像保持 `NULL`，默认不向登录用户展示。
4. 不依靠 `learner_id` 字符串前缀进行安全鉴权。

### 4.3 其他业务表

以下表不增加 `user_id`：

- `questionnaire_submissions`
- `questionnaire_answers`
- `diagnostic_answers`
- `diagnostic_runs`
- `generation_jobs`
- `generated_resources`
- `feedback_records`
- `agent_runs`

它们继续通过 `learner_id -> learner_profiles.user_id` 判断数据归属，避免扩大数据库改动范围。

## 5. 后端更新范围

### 5.1 新增文件

| 文件 | 作用 |
|---|---|
| `backend/app/api/auth.py` | 注册、登录、当前用户、退出接口 |
| `backend/app/models/auth_schemas.py` | 注册、登录请求和安全响应模型 |
| `backend/app/services/auth_service.py` | 用户注册、密码校验和 JWT 生成 |
| `backend/app/core/security.py` | Argon2id 哈希、JWT 编码和解析 |
| `backend/app/api/dependencies.py` | 获取当前登录用户、校验画像归属 |

无需单独新增认证仓储层，`AuthService` 可以复用现有用户仓储，并给仓储补充 `get_by_username()`。

### 5.2 修改文件

| 文件 | 更新内容 |
|---|---|
| `backend/requirements.txt` | 增加 `pwdlib[argon2]` 和 `PyJWT` |
| `backend/.env.example` | 增加 JWT 密钥、有效期和 Cookie 配置 |
| `backend/app/config.py` | 读取登录配置 |
| `backend/app/db/models.py` | 给 `users`、`learner_profiles` 增加字段 |
| `backend/app/db/database.py` | 增加 SQLite 轻量迁移和画像归属回填 |
| `backend/app/db/user/*` | 支持按用户名查询和更新登录信息 |
| `backend/app/db/learner/*` | 读写 `LearnerProfile.user_id`，按用户筛选画像 |
| `backend/app/models/user_schemas.py` | 增加安全登录字段，但响应不包含密码哈希 |
| `backend/app/models/schemas.py` | 给 `LearnerProfile` 增加 `user_id` |
| `backend/app/containers.py` | 注入 `AuthService` |
| `backend/app/main.py` | 注册 `/api/auth` 路由 |
| `backend/app/services/onboarding_service.py` | 使用当前登录用户创建画像 |
| 业务 API | 增加登录校验和简单的画像归属校验 |

继续沿用项目现有 `Base.metadata.create_all()` 和 SQLite 轻量迁移，不为本功能单独引入 Alembic。

### 5.3 配置项

建议增加：

```env
AUTH_JWT_SECRET=replace-with-a-long-random-secret
AUTH_JWT_ALGORITHM=HS256
AUTH_TOKEN_EXPIRE_MINUTES=480
AUTH_COOKIE_NAME=training_pilot_token
AUTH_COOKIE_SECURE=false
```

生产或公开部署时：

```env
AUTH_COOKIE_SECURE=true
```

`AUTH_JWT_SECRET` 必须由部署环境提供，不能提交真实值到 Git。

## 6. API 设计

### 6.1 注册

```http
POST /api/auth/register
Content-Type: application/json
```

最小请求：

```json
{
  "username": "zhangsan",
  "password": "用户输入的密码",
  "confirm_password": "再次输入密码"
}
```

可选资料字段：

```json
{
  "identity": "在校学生",
  "education": "本科",
  "major": "软件工程",
  "job_role": "算法工程师",
  "experience_years": 1
}
```

注册规则：

- `username` 去除首尾空格并统一转为小写，长度 3 至 64 位。
- `password` 长度 8 至 128 位，不增加复杂的字符组合限制。
- `confirm_password` 只用于确认两次密码一致，不写入数据库。
- `display_name` 不在注册页填写，后端自动使用 `username` 作为兼容显示名称。
- 身份、学历和专业未填写时，后端分别使用 `其他`、`未填写`、`未填写`，之后可在用户资料页修改。
- 用户名重复返回 HTTP `409`。
- 创建用户与密码哈希必须在同一数据库事务中完成。
- 注册成功后直接设置认证 Cookie 并返回当前用户，不要求再次登录。

注册接口不能复用会返回完整资料列表的 `/api/users/`。由 `AuthService.register()` 统一生成 `user_id`、哈希密码并创建用户。

### 6.2 登录

```http
POST /api/auth/login
Content-Type: application/json
```

请求：

```json
{
  "username": "zhangsan",
  "password": "用户输入的密码"
}
```

成功后由后端设置 HttpOnly Cookie，并返回：

```json
{
  "user": {
    "user_id": "user_xxx",
    "display_name": "zhangsan",
    "username": "zhangsan"
  }
}
```

`display_name` 是旧用户资料结构中的兼容字段，不在注册页或个人资料页展示；新注册用户由后端自动令其等于 `username`。

用户名不存在和密码错误统一返回：

```text
401 用户名或密码错误
```

### 6.3 获取当前用户

```http
GET /api/auth/me
```

- Cookie 有效时返回当前用户资料。
- Cookie 缺失或过期时返回 `401`。

### 6.4 退出

```http
POST /api/auth/logout
```

- 清除认证 Cookie。
- 返回简单成功状态。

### 6.5 需要保护的接口

`POST /api/auth/register` 和 `POST /api/auth/login` 保持公开；`GET /api/auth/me` 需要有效 Cookie。`POST /api/auth/logout` 无论 Cookie 是否有效都会清理 Cookie 并返回成功，便于客户端收敛状态。

第一版至少保护这些用户数据接口：

- `/api/users/*`
- `/api/profiles/*`
- `/api/onboarding/initial-profile`
- `/api/diagnosis/*`
- `/api/generate/*`
- `/api/resources/*`
- `/api/feedback/*`
- `/api/learning-history/*`
- `/api/report/*`
- `/api/reviews/*`

知识目录和健康检查可保持公开：

- `/health`
- `/health/ready`
- `/api/knowledge/domains`
- `/api/knowledge/directions`

## 7. 前端更新范围

### 7.1 新增登录与注册页

新增 `frontend/src/views/LoginView.vue`：

- 用户名输入框。
- 密码输入框。
- 登录按钮和提交状态。
- 统一错误提示。
- 提供进入注册页的明确入口。

新增 `frontend/src/views/RegisterView.vue`：

- 用户名、密码和确认密码为必填字段。
- 身份、学历、专业、岗位背景和经验年限作为可选资料字段。
- 前端先校验两次密码一致，再提交注册。
- 注册成功后自动进入工作台。

不增加找回密码或第三方登录入口。

### 7.2 前端状态

在现有 Pinia 中增加简单认证状态，或新增 `stores/auth.js`：

- `currentUser`
- `initialized`
- `register()`
- `login()`
- `initialize()`
- `logout()`

认证令牌不保存到 `localStorage`。前端只保存当前用户展示信息，真实身份始终由 `/api/auth/me` 确认。

### 7.3 API 和路由

修改 `frontend/src/api/index.js`：

- Axios 增加 `withCredentials: true`。
- 增加 `authApi.register()`、`authApi.login()`、`authApi.me()`、`authApi.logout()`。
- 收到 `401` 时跳转登录页。

修改 `frontend/src/router/index.js`：

- 新增 `/login`。
- 新增 `/register`，与登录页同为公开路由。
- 业务页面增加 `requiresAuth`。
- 路由守卫在首次进入时调用 `/api/auth/me`。

### 7.4 现有页面调整

- `App.vue`：显示当前用户和退出按钮。
- `OnboardingView.vue`：移除用户选择下拉框，直接使用登录用户。
- `UserProfileView.vue`：只显示当前用户资料。
- `HistoryView.vue`：只请求当前用户拥有的画像。
- 退出登录时清除当前画像、诊断结果和生成任务等本地缓存。

## 8. 最小测试范围

后端至少增加以下测试：

1. 注册能够创建用户，数据库中不出现明文密码。
2. 重复用户名返回 `409`，注册失败不留下半条用户数据。
3. 注册成功后能够直接通过 Cookie 获取当前用户。
4. 正确用户名和密码可以登录。
5. 错误密码返回 `401`。
6. `/api/auth/me` 能识别有效和过期 Cookie。
7. 退出后 Cookie 失效。
8. 用户不能通过修改 `learner_id` 查看其他用户数据。
9. 旧 SQLite 数据库启动后能自动补齐新字段。

前端至少人工验证：

1. 未登录自动进入登录页。
2. 可以从登录页进入注册页并完成注册。
3. 注册成功后直接进入工作台。
4. 登录后进入工作台。
5. 刷新页面仍保持登录。
6. 退出后回到登录页。
7. 新建学习方向时不再出现用户选择器。

## 9. 推荐实施顺序

1. 备份并确认正式数据库文件。
2. 修改两张表并完成 SQLite 轻量迁移。
3. 为现有用户设置用户名和密码。
4. 实现注册、登录、当前用户和退出接口。
5. 给关键业务接口增加认证和画像归属校验。
6. 增加登录页、注册页、路由守卫和退出入口。
7. 回归问卷、诊断、资源生成、反馈和学习历史流程。

## 10. 验收标准

- 注册、登录、刷新恢复和退出流程正常。
- 重复用户名不能注册，注册过程中不会保存明文密码。
- 密码只保存 Argon2id 哈希。
- JWT 不进入 `localStorage`，只通过 HttpOnly Cookie 传递。
- 未登录无法访问个人学习数据。
- 登录用户不能查看其他用户的数据。
- 新建画像正确写入 `learner_profiles.user_id`。
- 原有学习与 Agent 工作流不受影响。

## 11. 实施与验证结果

- SQLite 启动迁移已为 `users` 增加 4 个登录字段，并为 `learner_profiles` 增加 `user_id`。
- 注册页仅要求 `username`、`password`、`confirm_password`，没有 `display_name` 输入项。
- 密码使用 Argon2id 哈希；JWT 只写入 HttpOnly Cookie，不写入前端存储。
- 已通过最小三字段注册、自动登录、退出、再次登录、读取当前用户和受保护接口访问的真实 HTTP 验证。
- 后端回归结果为 103 项通过；其余 6 项失败来自既有资源目录权限和知识库默认配置问题，与登录注册改动无关。
- 前端生产构建通过。

## 12. 安全参考

- [FastAPI OAuth2、JWT 与密码哈希示例](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
