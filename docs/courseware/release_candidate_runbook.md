# 互动课件批次 C 发布候选运行手册

本手册只生成本地候选与证据索引，不会连接或变更外部生产环境。

## C0：手动真实模型验收

受控 CI 的手动 `live-model` job 需要非敏感 GitHub Variables：provider、base URL、model、structured mode、timeout、retry、输入/输出价格、币种、价格版本和生效日。密钥只放 `LLM_API_KEY` Secret。缺任何字段时报告为 `CONFIG_MISSING` 且 job 失败；没有凭据时为 `EXTERNAL_PENDING`。

```powershell
python backend/scripts/courseware_live_model_eval.py --fake --output backend/.pytest-tmp/live-fake.json
python backend/scripts/courseware_live_workflow_smoke.py `
  --config backend/config/courseware_live_model.deepseek-v4-flash.json `
  --enable `
  --artifact-root backend/.pytest-tmp/live-workflow-artifacts `
  --output backend/.pytest-tmp/live-workflow-report.json
```

该命令只运行四个固定的脱敏 ResourceBundleSnapshot 组合，每个组合创建一次正常课件任务并由 Worker executor 消费；配置最多两次模型尝试，禁止无限重试。旧的 `courseware_live_model_eval.py` 仅保留为 schema probe，不能作为完整发布验收证据。

## C1/C2：本地单 Worker 与发布候选

Web 和 Worker 必须使用同一文件型 `DATABASE_URL` 和 artifact 根目录。另开终端仅启动一个 Worker：

```powershell
python backend/scripts/courseware_worker.py
Invoke-WebRequest http://127.0.0.1:8081/health/live -UseBasicParsing
Invoke-WebRequest http://127.0.0.1:8081/health/ready -UseBasicParsing
```

可用独立进程 smoke 证明 Web 与 Worker 使用同一 SQLite 文件、Worker readiness、并发上限和 graceful shutdown：

```powershell
python backend/scripts/courseware_process_smoke.py `
  --root backend/.pytest-tmp/courseware-process-smoke `
  --output backend/.pytest-tmp/courseware-process-smoke.json
```

C1 故障矩阵必须使用真实进程 JUnit，并覆盖 kill/restart、租约接管、心跳丢失、重复投递、意外并发 claim、SQLite busy/临时断连、checkpoint/candidate/release/outbox 重放和安全备份：

```powershell
python -m pytest backend/tests/e2e/courseware/test_c1_process_fault_matrix.py -q `
  --junitxml=backend/.pytest-tmp/courseware-faults.xml
python backend/scripts/courseware_fault_matrix.py `
  --junit backend/.pytest-tmp/courseware-faults.xml `
  --output backend/.pytest-tmp/courseware-fault-matrix.json
```

停止 Web/Worker 写入后再备份 SQLite；从副本重启二者，并比对 checkpoint、outbox、release pointer、artifact hash 和可读性。禁止复制正在写入的数据库文件。

```powershell
python backend/scripts/courseware_sqlite_backup.py `
  --source <stopped-courseware.db> --output <backup.db> --writes-stopped
```

```powershell
python backend/scripts/courseware_release_candidate.py `
  --evaluator backend/.pytest-tmp/courseware-c-round-eval.json `
  --artifacts backend/.pytest-tmp/courseware-ci-artifacts/artifact-summary.json `
  --fault-matrix backend/.pytest-tmp/courseware-fault-matrix.json `
  --browser frontend/tests/test-results/courseware-browser/summary.json `
  --live-model backend/.pytest-tmp/live-real-or-config.json `
  --output backend/.pytest-tmp/courseware-release-candidate.json
```

`LOCAL_READY` 不表示 CI、目标部署或完整发布周期完成；未运行真实模型时也继续保持 `EXTERNAL_PENDING`。SCORM/xAPI 是基础导出包。

## C3：完整发布周期

从运行数据库导出脱敏事件（仅 sequence、stage、status、code、release ID）后运行：

```powershell
python backend/scripts/courseware_release_cycle.py `
  --events <sanitized-event-export.json> `
  --output backend/.pytest-tmp/courseware-release-cycle.json
```

该脚本会识别 hard-gate 绕过、重复 release 与来源错配，但不伪造观察期；其 `observation_status` 保持 `EXTERNAL_PENDING`。仅在完整真实周期有留档时才能把 C3 标为 `DONE`。任何需要事件契约、数据库、公开 API、组件 schema 或 workflow 节点的变化必须另建任务。
