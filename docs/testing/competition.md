# 比赛评测方案：RAG 工程技能培训

本方案依据仓库根比赛 PDF 的第5页提交要求和第8页实用价值评分要求。附件是评测需求来源，未将其中待办自动扩大为产品开发任务。工程回归的组织与命令见 [项目测试方案](README.md)。

## 一、要求、数据和判定口径

| 要求 ID | 比赛要求 | 当前可核查数据 / 验证 | 证据边界 |
|---|---|---|---|
| C-KB | 至少1个垂直专业领域知识库，贴合岗位与规范 | RAG 工程库 v2.3.0，6个模块、13个能力节点；快照冻结10文件/51章节 | 本地专业模块附论文/官方文档链接，不能声称已取得真实企业培训数据或独立专家认证 |
| C-PROFILE | 实用价值至少3组不同背景 | 应届计算机学生、转岗后端工程师、数据工程师；三水平×两目标，共18画像 | 虚构画像，角色/学历/专业/经验/先验AI经验；非真实受试者效果 |
| C-CASE | 不足50组属于方案不完整 | 18画像×讲义/实操指南/分阶测试题，54唯一 case_id | 用例数据数量与实际生成完成数分别统计 |
| C-CHAIN | 至少2组输入/多 Agent 中间数据/最终资源示例 | 54组固定案例通过实际 graph/证据门/Claim/发布控制回放，输出完整 `competition-replay.json` | 部分 Agent/模型为 Scripted 替身，明确标为确定性工作流回放 |
| C-HAL | 专业知识谬误率 <5% | 最终发布叶子资源中 `(contradicted + not_in_evidence) / factual_claim_total` | 不使用 Reviewer 自评分替代事实 Claim；不完整判定、无事实样本不能获正式 PASS |
| C-DIFF | 画像-资源难度适配准确率 ≥85% | 期望难度与实际难度标签相同的用例 / 全部选中用例 | 失败/未生成保留为 NOT_GENERATED，不从分母消失；标签不能证明正文的教学难度 |
| C-COVER | 核心知识覆盖率 ≥90% | supported 事实 Claim 绑定的目标能力节点 / 固定目标节点13个 | 资源自称包含知识点不算覆盖，目标集合不得随结果删减 |
| C-TRANSFER | 泛化与可迁移能力 | 合成第二领域 test_evaluation_pipeline_transfers_to_new_domain_without_code_changes | 证明评测协议/工具可迁移，不能冒充第二真实领域的模型成绩 |
| C-UNIT | 核心协同/准确性单元测试 | competition_suite/evidence/Claim 单元、workflow 集成、54例回放 | 工程正确性与模型统计分别提供 |

本项目将评分条款中的“≥50组”落实为至少50个唯一、带画像和任务目标的评测 case，采用三背景的较严格要求。金标资源固定的负例也保留；不靠删掉错误样本、降低阈值或把pytest参数化数量混入样本数获得达标。

## 二、数据包结构与冻结

```text
backend/tests/fixtures/competition/
  suite.json                          # ID/version、指标阈值、文件入口、模式说明
  sources.json                        # 知识库文件/章节hash、行号、原始来源链接
  profiles/rag_engineering_learners.json
  cases/rag_engineering_cases.json
  claims/rag_engineering_claims.json
knowledge_base/rag_engineering_training/
  metadata.json                       # 领域、6模块、13能力节点与先修关系
  modules/*.md                        # 实际学习知识与工程实操资料
  questionnaire.json
  diagnostic_questions.json
  assessment_questions.json
```

`suite.json` 是测试数据入口。默认比赛套件必须保留来源快照；加载时校验 ID/version、子文件 fixture_version、KB 引用、真实使用的背景/资源类型、画像/目标节点、唯一 case/claim、Claim type/verdict、证据约束及门槛。相对路径不得越出 fixture/KB 根。至少50用例、幻觉上界≤0.05、适配下界≥0.85、覆盖下界≥0.90不可下调。

`sources.json` 按 UTF-8/LF 规范化计算 SHA-256，因此 Windows/Linux Git 换行不影响快照。它冻结 metadata、三份问卷/题库、六份正文；每个 `ev-modNN-secN` 映射到实际文档、章节、行号与section hash，附 metadata 中的原始来源链接。任何正文/题库/metadata或证据映射漂移均加载失败。

修改专业知识或标注后，先检查事实与岗位要求，修订金标并说明版本原因，再显式重新冻结：

```powershell
python backend/scripts/competition_snapshot.py
python backend/scripts/competition_eval.py --output output/test-runs/data-review/competition.json
```

快照工具只冻结当前本地文件，不在线验证链接，不证明标注已获专家复核。当前金标来源为已有人工整理 fixture，没有独立双人复核记录；`sources.json` 与报告均保留该限制。新真实领域须提供其专业文件、画像、用例与同样的来源协议；现有合成第二领域兼容测试可无快照运行，但不能成为正式证据。

## 三、成套场景

| 场景组 | 输入变化 | 可观察结果与判定 |
|---|---|---|
| 正常生成与个性化 | 三背景×三水平×两节点×三资源形态 | 决策链完整、来源可追溯、资源类型和难度一致；数据工程师 tier1 的六个难度差异保留以定位策略缺口 |
| 专业知识正/负例 | 71 supported、2 contradicted、1 not_in_evidence、4非事实 | 事实分母74、错误分子3；非事实不混入分母 |
| 来源硬门 | 无命中、低分、跨KB、引用不存在、快照漂移 | 生成阻断或数据拒绝，不能凭“available”标签绕过证据门 |
| 审核与定向纠偏 | 审核要求修订、Claim不支持、版本重试 | 保留旧版本/审计，仅最终发布叶子计量，未通过不能发布 |
| 学习反馈与动态决策 | 低正确率、正常练习、掌握度进展 | 补救/强化/推进规则与新路径版本，重试幂等；见工程覆盖矩阵 |
| 运行失败与统计边界 | 模型/生成/查询异常、未发布、1–49个样本 | 逐例失败阶段和异常类型，保留分母；缺证据为 NOT_MEASURABLE |
| 协议和阈值负例 | 49用例、未使用背景、未知节点、版本漂移、降低阈值 | 加载失败；幻觉恰好上界不通过，适配/覆盖恰好下界通过 |
| 迁移与恢复 | 合成新领域、进程重启、SQLite迁移 | 工具数据协议复用、运行可恢复；不外推真实领域准确性 |

54个比赛用例作为个性化矩阵；安全/重试/反馈等工程负例独立运行，不混作54个真实生成样本。

## 四、运行与结果分层

### 1. 离线金标与策略回归

```powershell
python scripts/run_tests.py --suite competition
python scripts/run_tests.py --suite backend-workflow
```

competition 读取78条固定 Claim，构造金标聚合资源以验证计算；难度来自系统 `difficulty_for_tier`，期望来自画像标注。回归基线是幻觉3/74≈4.05%、难度48/54≈88.89%、覆盖13/13=100%。这些是预设数据与策略的数值；`gates` PASS 表示回归通过，`completed_generation_count=0`，`official_gates` 全为 `NOT_MEASURABLE`。

`case_results` 有54条画像/背景/请求、input hash、期望、策略决定和gold证据编号；`status=REFERENCE_ONLY`、运行事件为空、生成output为空，避免制造模型生成记录。

### 2. 实际工作流的冻结回放

backend-workflow/backend-full 执行 `test_competition_replay.py`，用冻结知识章节、固定画像、Scripted Agent 输出经过实际工作流控制、Claim结构化校验和最终发布规则。结果 `competition-replay.json` 含54组完整的输入、来源、结构化diagnosis/learning_plan/review_result、各节点摘要与协同trace、Claim/judgement、发布资源与output hash，可选任意两组以上作为固定演示示例。

其 `evidence_scope=deterministic_workflow_replay_with_scripted_agents`、`live_generation_count=0`。它验证协同和证据协议，不能证明模型真实推理、检索排名质量或岗位培训效果。

### 3. 真实模型生成与生产自审

仅在用户明确授权、有效配置和隔离评测环境具备后执行。本次改造不运行此层。先确认测试数据库、索引和产物目录与实际用户环境隔离，并明确模型、成本/次数/时延预算。原live CLI 会使用配置的容器及持久化环境；不能把它指向实际用户库作为默认验收。

```powershell
$env:RUN_LIVE_LLM = "1"
python backend/scripts/competition_eval.py --mode live --max-cases 3 --output output/test-runs/live-smoke/competition.json
python backend/scripts/competition_eval.py --mode live --max-cases 54 --output output/test-runs/live-full/competition.json
```

小批量前3例仅验证调用通路，未覆盖三背景，不产生正式达标结论。缺开关/凭据在任何模型调用前 SKIP，退出2。真实结果文件自动加 `-live` 后缀。每例保留静态画像输入、run_id、排序事件与payload hash、Evidence快照/版本/hash、Claim/judgement、最终资源与output hash；异常只记阶段与类型，不导出任意异常正文。失败继续记入选中集合，难度分母不缩小。

三项运行gate需至少50完成用例、完整选中集合、三背景/三资源类型、来源快照和完整事实判定；缺少任何一项为 NOT_MEASURABLE。失败用例使CLI退出1，纯小样本/缺证据为2。这里的 Claim 判定来自系统自己的生产审核，仍须独立质量复核；`official_gates` 保持 NOT_MEASURABLE。

### 4. 独立质量与岗位适配复核

从冻结的真实生成报告导出 `case_id→input_hash→run_id→resource/version/output_hash→Claim→source_snapshot_hash`，由未参与生成的评测人员或校准后的独立评判器盲审。保留事实 supported/contradicted/无证据标注、期望难度理由、核心知识节点覆盖与分歧裁决，复核对象须为最终发布版本。实际资源难度还应包含术语、先修、实操步骤/问题复杂度，不能只认可资源自带标签。

至少三背景各有完成样本，说明每个分母、失败率、分组表现及样本选择；核心13节点的未覆盖项逐项保留。专家/真实受试者训练效果与第二真实领域迁移结果须独立记录，不用合成画像或工程回放替代。当前仓库不自动导入独立判分，缺少该报告时不要提交正式质量PASS；独立审核属于赛事实验，不新增产品人工审核工作台。

## 五、报告与退出码

| 字段 / 文件 | 用途 |
|---|---|
| suite_id/version、suite_data_hash | 固定本次画像/用例/金标配置身份 |
| source_snapshot_hash | 固定KB/章节/来源身份 |
| evidence_scope、independent_quality_review | 区分离线、冻结回放、实际生成与独立质量证据 |
| selected_case_count、completed_generation_count、failed_case_count | 样本数量、真实完成、失败，不能相互替代 |
| metrics 与 gates | 明示事实数74等实际分母、目标节点、准确率、混淆矩阵和运行回归门 |
| official_gates | 缺真实生成/独立复核时明确 NOT_MEASURABLE |
| case_results / competition-replay.json | 完整逐例引用、决策链、输出和失败定位 |

普通离线回归通过退出0，数值gate失败/执行失败退出1，live未就绪/样本不足或 `--require-official` 缺正式证据退出2。例如在离线输出上使用 `--require-official` 会生成报告并退出2，这是预期的证据检查，不是回归失败。

## 六、当前完成范围与待补证据

已具备版本化专业数据、54案例/三背景、输入-协同-输出固定示例、工程负例、统一入口、可追溯报告与自动回归。正式三指标达标仍需真实生成样本和独立复核；岗位培训效果、第二真实领域、线上Worker及部署分别需要实际实验。具体执行结果以每次生成的本地验收报告为准，不把未运行项写为PASS；更新计划属于本地资料，不随仓库分发。
