# Git 协作规范

> 文档用途：约定项目组 Git 使用方式，减少多人并行开发时的冲突和误提交。  
> 当前阶段：架构搭建与并行开发准备。规则以简单、可执行为主，后续可根据团队实际调整。

## 1. 基本原则

- 不直接在 `main` 分支上开发功能。
- `main` 分支由项目负责人维护，普通开发成员不直接向 `main` 提交或合并代码。
- 普通开发成员的功能、修复和文档修改，默认先合并到 `dev`。
- 每个功能、修复或文档调整使用独立分支。
- 提交前先检查 `git status`，确认没有误提交运行时数据、缓存、密钥和依赖目录。
- 涉及 API、架构、功能范围变化时，代码和文档需要同步更新。
- 当前项目处于设计阶段，分支和提交规则用于协作清晰，不限制后续重构。

## 2. 分支约定

| 分支 | 用途 |
|------|------|
| `main` | 稳定版本，保留阶段性可展示成果；由项目负责人审批并合并 |
| `dev` | 集成开发分支，普通开发成员的代码先合并到这里 |
| `feature/<name>` | 功能开发 |
| `fix/<name>` | 问题修复 |
| `docs/<name>` | 文档调整 |
| `chore/<name>` | 配置、依赖、工程化调整 |

示例：

```bash
git checkout -b feature/agent-workflow
git checkout -b feature/knowledge-ingestion
git checkout -b feature/frontend-report
git checkout -b docs/api-contract
```

## 3. 提交信息格式

提交信息建议使用：

```text
type(scope): summary
```

常用 `type`：

| type | 用途 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(agent): add reviewer scoring` |
| `fix` | 修复问题 | `fix(api): return 404 for missing learner` |
| `docs` | 文档修改 | `docs(api): clarify feedback question source` |
| `refactor` | 重构 | `refactor(db): split learner repository` |
| `test` | 测试 | `test(service): add feedback decision cases` |
| `chore` | 配置、依赖、杂项 | `chore(git): update ignore rules` |

要求：

- `summary` 用一句话说明改了什么。
- 一个提交尽量只做一类事情。
- 不建议使用 `update`、`fix bug`、`修改一下` 这类含糊提交信息。

## 4. 推荐开发流程

第一次初始化仓库：

```bash
git init
git add .
git commit -m "chore: initialize project architecture"
```

日常开发：

```bash
git checkout dev
git pull
git checkout -b feature/<name>

# 开发完成后
git status
git add <files>
git commit -m "feat(scope): summary"
git push origin feature/<name>
```

合并建议：

1. 普通开发成员从 `dev` 拉取分支进行开发，完成后通过 Pull Request 合并到 `dev`。
2. `dev` 是日常集成分支，用于汇总各组代码、进行基础运行验证和 API 联调。
3. `dev` 合并到 `main` 由项目负责人执行，通常只在阶段成果稳定、可展示或准备提交时进行。
4. 合并前确认文档、接口和测试说明已同步。

权限建议：

- 普通开发成员：负责 `feature/*`、`fix/*`、`docs/*`、`chore/*` 分支开发，并提交 Pull Request 到 `dev`。
- 各小组负责人：负责检查本组 Pull Request 是否符合任务边界、接口约定和文档要求。
- 项目负责人：负责 `dev -> main` 的最终合并，保证 `main` 始终代表稳定版本。
- 如遇紧急修复，也应先在修复分支完成，确认后再由项目负责人决定是否合并到 `main`。

## 5. 不应提交的内容

以下内容不得提交到 Git：

| 类型 | 示例 |
|------|------|
| 密钥和本地配置 | `backend/.env`, `.env` |
| 数据库文件 | `*.db`, `*.sqlite3`, `backend/data/domain_knowledge.db` |
| 运行时生成资源 | `backend/data/generated_resources/` 下的实际资源文件 |
| 向量库索引 | `backend/chroma_db/` 下的索引文件 |
| 日志 | `backend/logs/*.log`, `*.log` |
| 依赖目录 | `node_modules/`, `venv/`, `.venv/` |
| 缓存 | `__pycache__/`, `.pytest_cache/` |

允许提交的占位文件：

- `backend/data/.gitkeep`
- `backend/data/generated_resources/.gitkeep`
- `backend/data/generated_resources/*/.gitkeep`
- `backend/chroma_db/.gitkeep`
- `backend/logs/.gitkeep`

## 6. 文档同步规则

| 修改内容 | 需要同步的文档 |
|----------|----------------|
| API 字段、路径、状态码变化 | `docs/api.md` |
| 架构分层、路径、模块边界变化 | `docs/architecture.md` |
| 功能范围、页面能力变化 | `docs/features.md` |
| 小组职责、任务、交付物变化 | `docs/task-allocation.md` |
| 启动方式、部署路径变化 | `README.md`, `docs/deployment.md` |

## 7. 冲突处理

- 先确认冲突文件是否属于自己负责范围。
- 不要直接覆盖他人的改动。
- 对 API、模型、数据库、Agent 状态字段这类跨组文件，冲突解决后需要通知相关组。
- 如果冲突涉及接口契约，以 `docs/api.md` 和总架构组最新约定为准。

## 8. 提交前检查清单

- `git status` 中没有 `.env`、数据库、日志、缓存、依赖目录。
- 修改 API 时已同步 `docs/api.md` 和 `backend/app/models/schemas.py`。
- 修改路径时已同步 `README.md`、`docs/deployment.md` 和 `.env.example`。
- 修改功能范围时已同步 `docs/features.md`。
- 修改分工或职责时已同步 `docs/task-allocation.md`。
- 能运行的测试已运行；不能运行时，在提交说明或沟通中说明原因。
