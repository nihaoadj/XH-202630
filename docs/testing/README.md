# 测试指南

从仓库根使用项目虚拟环境执行。依赖准备见 [部署指南](../deployment.md)，套件成员以 [tests/suites.json](../../tests/suites.json) 为准。

## 选择与运行

```powershell
python scripts/run_tests.py --list
python scripts/run_tests.py --suite learning-round-api --dry-run
python scripts/run_tests.py --suite learning-round-api
```

`learning-round-api` 是轮次接口示例，实际按改动选择套件或具体 pytest 用例。多个 `--suite` 可组合。输出默认位于 `output/test-runs/`，包含命令日志和结果摘要。完整 `regression`、`acceptance` 和全部浏览器专项仅在用户明确要求全量时运行。

| 验证对象 | 入口 |
|---|---|
| API、事务、工作流、迁移 | `backend/tests/` 对应领域，按文件或用例执行 |
| 分层导入、前端契约 | `python scripts/check_architecture.py`、`python scripts/export_frontend_contracts.py --check` |
| 锁文件与安装依赖 | `python scripts/check_dependencies.py`、`python -m pip check` |
| 前端状态与交互 | [前端测试清单](../../frontend/package.json) 与 `frontend/tests/`。浏览器专项先运行 `npm --prefix frontend run build` |
| 轮次、Claim 补检、课件硬门和资源质量 | 测试清单中对应专题套件 |
| 比赛金标、冻结回放、真实生成 | [比赛评测](competition.md) |

报告读取的离线基准可用 `python backend/scripts/report_benchmark.py --output output/test-runs/report-benchmark --sizes 100 1000 10000 --repeats 3`。结果描述本次合成数据和运行环境。Claim 配置可用 `python backend/scripts/claim_counting_profile.py` 做离线预检。

后端的哈希锁文件由 `backend/requirements.txt` 和 `backend/requirements-dev.txt` 生成。更新声明后按文件头记录的命令刷新锁文件并校验依赖。

## 证据边界

确定性测试使用隔离数据库、冻结材料和模型替身。浏览器专项使用本地 fixture。记录实际执行的命令、范围、退出结果与未覆盖项。fixture、CI 和实际部署分别记录。

真实联调使用目标环境的专用测试身份和独立资料，从该环境的本地凭据取得账号信息。真实模型须由用户明确授权并提供预期凭据，按 [评测记录约定](../evaluations/README.md) 记录失败、重试、证据和用量。
