# E2：Claim 抽取中立性升级

- 核验日期：2026-10-26。
- 状态：**单一推荐方案已确定，当前项目接入路径已复核；真实模型效果待验证；尚未实施。**
- 本次修订范围：调整编号并复核当前流程，仅保留抽取输入与职责分离；不增加遗漏复核、补抽、覆盖状态和发布门。第 4 节区分可核对的历史测试与源码兼容性依据，本轮未重跑业务测试，未修改实现、Prompt、配置、数据库或发布策略。
- 实施顺序：建议在 [E1 检索与证据分配](E1-resource-aware-retrieval.md) 后实施；本方向可以独立验证，组合时遵守同一资源证据范围。
- 适用范围：文本学习文档现有通用 Claim 审核链。结构化测评继续使用专用内部审核，不纳入通用 Markdown 抽取方案。

## 1. 结论与直观解释

**唯一推荐方案：抽取器只依据规范正文及文内上下文识别、分类陈述；冻结 Evidence 留给 Judge 判断事实是否得到支持。**

这套方案直接修改现有 `claim_extract_node` 的输入与 Prompt，保留 `claim_extract_node → claim_judge_node → claim_decide_node` 的节点顺序、模型调用阶段和现有发布规则。抽取器自身仍负责分类，但不新增抽取后的复核调用，也不新增补抽循环。

当前抽取器同时看正文和证据，并被要求优先保留可由冻结证据独立验证的核心事实。“可验证”不等于“已得到支持”，但这种筛选要求仍存在选择偏向风险：无依据的陈述可能没有被抽出来。后续判定器只检查抽出的 Claim，无法补查未进入候选集合的事实。

例如正文包含：

1. “Python 使用缩进定义代码块。”
2. “Python 程序永远不会发生运行时错误。”

证据只包含第一句。应当把两条陈述都交给事实判定器，而不是在抽取阶段因为第二句没有依据就忽略它。第二句在当前证据下可以判 `not_in_evidence`，不要求判定器借助外部常识给出 `contradicted`。

本方向针对证据影响抽取选择的风险。**移除 Evidence 不保证完整抽取，也不能独立解决漏抽和误分类；真实模型的抽取效果尚未测量。**

## 2. 当前真实路径及已有能力

文本资源先完成检索、证据门禁、规划和生成。启用 Claim 且资源符合条件时，普通审核与工作流路由将其交给以下链路：

```text
资源规范正文 + 冻结 Evidence
→ claim_extract_node：按资源抽取候选事实、分类和原文位置
→ materialize_claims：校验原文位置与 ID 范围，生成稳定记录
→ claim_judge_node：依据冻结 Evidence 独立判定每条 Claim
→ materialize_judgements / compute_claim_metric：校验判定、计算指标
→ claim_decide_node：结合普通审核结果决定修订或交给发布策略
```

Claim 是可选审核；[GenerateRequest](../../backend/app/models/learning_documents/schemas.py) 的 `include_claim_check` 默认关闭，开启时要求普通审核开启且单请求只有一个资源类型。不能假设所有已发布资源都走过本链路。

| 已有能力 | 源码位置与含义 |
|---|---|
| 独立抽取与判定 | [claim_review_agent.py](../../backend/app/agents/resource_workflows/learning_documents/claim_review_agent.py) 的 `claim_extract_node`、`claim_judge_node`；不是一次调用完成两项任务 |
| 原文片段校验 | [claims.py](../../backend/app/models/reviews/claims.py) 的 `materialize_claims`；`source_text` 必须是资源原文精确子串，偏移错误时可确定性重定位 |
| 引用及分类合同 | `materialize_claims`、`materialize_judgements` 校验白名单、每条 Claim 恰有一个判定、类型与 verdict 组合 |
| 冻结证据语义判定 | `JUDGE_PROMPT` 要求仅依赖冻结 Evidence，区分 `supported`、`contradicted`、`not_in_evidence`，已有这项能力 |
| 特殊教学内容处理 | 复习清单题干、选项及教学提示不直接当作事实断言；分类区分 `factual`、`instructional`、`non_factual` |
| 结构化测评专道 | 有 `assessment_payload` 的分阶测试题跳过通用 Markdown 抽取，使用 [assessment_scope.py](../../backend/app/agents/resource_workflows/learning_documents/specialized_reviews/assessment_scope.py) 和内部完整题卷审核；并非未审核 |

## 3. 已确认不足与尚待验证的风险

### 3.1 抽取与“能否被现有证据支持”耦合

`claim_extract_node` 向模型提供 `allowed_evidence`，其中含 Evidence ID 和 excerpt 正文；`extractor_prompt` 明确要求：

> 优先保留可由冻结 Evidence 独立验证的核心事实。

这是源码事实。推荐直接移除抽取模型输入中的外部 Evidence，用章节标题、相邻原文、否定条件和假设标记保留消歧所需的文内上下文。正文无法明确表达的内容不能由抽取器借助证据自行补全。该设计减少证据对事实筛选的干扰，真实召回与误分类表现仍需用固定基线验证。

### 3.2 固定数量上限与长文事实数量不匹配

[config.py](../../backend/app/config.py) 中 `claim_max_claims_per_resource` 默认 10，配置范围 1–20；[claims.py](../../backend/app/models/reviews/claims.py) 的候选 schema 硬上限为 20。运行时拒绝超过配置上限的输出。

对于独立可核验事实数超过上限的资源，当前单批抽取无法逐条穷尽。把多条事实合为一条会失去逐事实判定能力；单纯提高上限也不能证明没有漏抽。

这是当前已知限制，保留在现状说明中。本方向不调整数量配置、schema 上限或其处理方式，也不增加“发现长文超过容量就阻止发布”的规则。

### 3.3 当前“complete”没有表达全文覆盖完整性

`materialize_claims` 遍历模型已提交的候选，没有和全文中的完整事实清单比较。`materialize_judgements` 保证已抽 Claim 判定齐全；`compute_claim_metric` 的分母仅是已抽取且标为 `factual` 的 Claim。

因此，当前 `complete` 表示已抽出的事实都有完成判定，不能解释为全文事实均已审查。`incomplete` 可以识别已抽事实缺少判定，不能识别根本没抽出来的事实。这是覆盖状态缺失，不是现有比例公式算错。

### 3.4 事实被误标为非事实后，后续 Judge 不能直接纠回

当前 `_normalize_judgement_candidates` 会把 `instructional/non_factual` 候选的判定规范为 `non_factual`；`materialize_judgements` 也约束类型与 verdict 一致。若抽取器把事实误分类，它不会进入事实指标分母。

这是本轮不新增机制处理的已知限制。抽取 Prompt 继续区分教学问题、错误选项、假设情境和事实，但不为误分类增加第二次模型复核。

## 4. 验证证据与适用范围

### 4.1 现有确定性测试

首次建立本文时，从仓库根使用现有独立环境运行以下三组测试，结果 **25 passed，退出码 0**。本轮修订保留该历史证据，未重新运行这三组测试：

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'backend')
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:RUN_LIVE_LLM = '0'
$env:COURSEWARE_LIVE_EVAL = '0'
& 'output/test-runs/t20-clean-py311-20261023/venv/Scripts/python.exe' -m pytest backend/tests/unit/models/test_claim_contracts.py backend/tests/unit/agents/test_claim_evaluation.py backend/tests/integration/workflow/test_claim_workflow.py -q -p no:cacheprovider --junitxml=output/test-runs/extension-idea-e1-20261025/claims.xml
```

这些测试覆盖已有原文 span、白名单、数量上限、判定缺失、非事实分类、结构化测评专道和修订等合同。它们不测量真实模型的抽取召回。

### 4.2 合成边界探针

探针调用实际 `claim_extract_node → claim_judge_node → claim_decide_node`，使用仓库已有 `ScriptedLLMGateway` 固定抽取和判定输出。普通审核预设为通过，用于隔离 Claim 环节；没有调用真实模型、数据库、发布服务或完整生产工作流。

| 固定输入场景 | 抽取情况 | 当前指标状态 | 当前 Claim 指标 | Claim 决策 |
|---|---|---|---|---|
| 正文两条事实，第二条无证据且漏抽 | 只抽第一条，判 supported | complete | 0% | approve |
| 同一正文，两条均正确抽出 | 第一条 supported，第二条 not_in_evidence | complete | 50% | revise |
| 同一正文，第二条误标 non_factual | 两条均抽出，但只有第一条计入事实 | complete | 0% | approve |
| 合成正文 11 条事实，前 10 条有证据，第 11 条无证据 | 抽前 10 条，恰好触顶 | complete | 0% | approve |

50% 是该两条合成样例的固定判定比例，不是项目真实幻觉率。`approve` 只是当前 Claim 节点决策，不是已实际发布的证据。

探针证明：**当漏抽或误分类已经发生时，当前 Claim 链不会独立检测该覆盖缺口。** 它没有证明模型会以何种频率产生这些输出，也没有证明所有其他审核都会漏掉它们。

本地复现命令（沿用上一节环境变量）：

```powershell
& 'output/test-runs/t20-clean-py311-20261023/venv/Scripts/python.exe' output/test-runs/extension-idea-e1-20261025/probe.py
```

证据为 [测试日志](../../output/test-runs/extension-idea-e1-20261025/claims.log)、[JUnit](../../output/test-runs/extension-idea-e1-20261025/claims.xml)、[探针脚本](../../output/test-runs/extension-idea-e1-20261025/probe.py)、[探针结果](../../output/test-runs/extension-idea-e1-20261025/probe.json)。这些 `output/` 路径和独立 Python 环境是本地忽略产物，远端克隆不保证存在；上面的场景、函数和结果用于保留可审查说明。实施前应把必要场景正式转成仓库测试，不能依赖本地文件永久存在。

### 4.3 本轮源码可确认的兼容性

此前文档记录过两项额外固定输出探针，但未找到其独立脚本或日志，本轮不把该叙述计为可复查的测试通过证据。当前可由源码确认的是：

| 拟采用的行为 | 当前合同依据 |
|---|---|
| 抽取 `source_evidence_ids=[]`，Judge 独立引用证据 | 抽取引用允许空列表，Judge 的 `evidence_ids` 独立校验和保存，前端引用展示读取 Judge 结果 |
| `knowledge_point_id=null` 的陈述进入判定 | `materialize_claims` 允许空标签，不会仅因无法贴知识点标签拒绝该候选 |

这说明存在兼容接入依据，**不证明无 Evidence 抽取已实现或新方案已经通过测试**。实施时应把这两项加入正式回归，并验证判定结果及预算允许下的修订路由。

## 5. 确定的升级方案

```text
现有生成与普通审核
→ claim_extract_node：仅根据正文抽取并分类
→ materialize_claims：执行既有原文位置、标签和 ID 校验
→ claim_judge_node：依据原有冻结 Evidence 判定
→ claim_decide_node：执行既有决策
→ 现有修订与发布流程
```

### 5.1 抽取模型不接收额外 Evidence

从 `claim_extract_node` 的模型 payload 中删除 `allowed_evidence`，不额外发送外部 Evidence ID、excerpt 或基于证据支持程度的提示。保留资源 ID、版本、类型、`_claim_audit_content(resource)` 的规范正文，以及仅用于贴标签的知识点 ID 白名单。

当前 `_claim_audit_content(resource)` 原样返回 `resource.content_text`，这就是本方案的规范正文；正文内已有的引文、参考内容、代码和引用标记不删除、不改写。移除的是额外附送的 Evidence，不承诺正文中完全没有来源信息，也不做会改变 span 偏移的清洗。标了引用不代表事实已经被支持。

工作流中的冻结 Evidence 继续保留。本方向单独实施时 Judge 沿用当前证据范围；E1 已实施时，Judge 输入和服务端判定白名单使用该资源冻结的 `A = 公共证据 ∪ 本类专属证据`。两种实施顺序均不向抽取模型重引入额外 Evidence。

同步修改抽取 Prompt：

- 去掉“优先保留可由冻结 Evidence 独立验证的核心事实”要求，不按能否获得证据支持来选择陈述。
- 原文实际作出的可核验断言都属于候选范围，包括疑似错误、非核心和范围外断言；输出数量仍遵守当前上限。
- `knowledge_point_id` 只表示标签归属。无法对应白名单时填写 `null`，不能因为没有对应知识点而丢掉事实。
- 保留章节、主体、条件、否定和假设语境，不借助外部常识补足原文没有表达的意思。
- 继续区分事实、教学动作、题干和干扰项；分类在这一次抽取调用中完成。
- 保留连续精确原文子串、全文字符位置及服务端校验。

### 5.2 抽取阶段不绑定证据引用

新抽取版本的 `source_evidence_ids` 保留公开字段，由服务端在候选适配层确定为 `[]`，再计算 hash 和生成记录。空列表表示“抽取阶段不绑定证据”，不表示 Judge 已判 `not_in_evidence`。

真正的支持或矛盾证据继续保存在 Judge 的 `evidence_ids`。不改写历史 Claim，不清空资源生成元数据中同名的来源字段，也不修改金标 fixture 的既有来源数据。

抽取 trace 不再把冻结 Evidence 声称为“抽取器已使用的依据”；Judge 的 trace 仍记录实际使用的证据。更新抽取 Prompt 版本，沿用现有稳定 Claim ID 与历史审计机制。

### 5.3 Judge、修订与发布按现有规则运行

保留 Judge 的 verdict、指标公式和判定职责，证据范围遵守上一节的 E1 兼容规则。Judge 仍审核已提交的候选，不承担找回漏抽事实或纠正抽取分类的新增职责。

发现 `contradicted/not_in_evidence` 时，沿用现有 `target_claim_ids` 和修订指令，由工作流根据路由与剩余预算决定是否返回生成与普通审核。当前公开请求的 `claim_max_iterations` 默认 0，但 `route_after_claim_decide` 随后还会检查普通修订预算 `max_iterations`；不能只看其中一个参数就断言一定返工或一定停止。两条适用返工路径均不允许继续时，进入原有收尾与发布限制。实际发生正文修订后，再按原流程重新抽取、判定。

本方向不新增模型调用阶段、不新增补抽、不新增覆盖状态、不调整 Claim 数量上限，也不新增覆盖发布门。当前 partial 发布与用户决定发布的规则保持不变。

## 6. 验证方案与通过依据

使用同一批正文、Evidence、模型版本及预算，对比当前流程与上述方案。只验证已选方案是否改善抽取中立性，不再提供互斥备选路线。真实模型对照需另行明确授权。

| 验证项 | 通过依据 |
|---|---|
| 输入隔离 | 抽取模型不再收到额外 Evidence，原规范正文及偏移不变；Judge 使用当前策略为本资源冻结的证据范围 |
| 空引用兼容 | 抽取引用为空不影响 Judge 引用、判定证据持久化和前端来源展示 |
| 范围外陈述 | 固定输出探针中，`knowledge_point_id=null` 的事实仍可进入判定和现有修订 |
| 原文与分类 | 精确子串和位置校验继续生效；用否定、条件句、复习题干和干扰项检查真实模型是否误拆或误分类 |
| 现有数量和发布规则 | 当前上限、失败处理、partial 与用户决定行为不变；分别覆盖 Claim 和普通修订预算，两条适用路径均耗尽时不额外生成 |
| 版本与历史 | Prompt 版本更新，历史 Claim 不被新 hash 或空引用覆盖 |
| 实际质量与成本 | 对照抽取召回、精确率、分类错误、调用数、token 和时延；不凭一次成功宣称改善 |

更完整的候选抽取可能让统计中的无依据事实比例上升，因为以前漏掉的问题进入了判断。这个数值变化不等于生成质量变差，也不能据此直接证明升级成功。

原有 `complete` 仍只表示已抽 Claim 的判定完成；本方案没有建立全文覆盖证明，不能把它解释为全文所有事实都已审核。

## 7. 当前项目接入与兼容边界

| 接入位置 | 本方向的处理 |
|---|---|
| [claim_review_agent.py](../../backend/app/agents/resource_workflows/learning_documents/claim_review_agent.py) | 修改抽取 payload、Prompt、候选空引用适配和 trace；保持 Judge 与决策职责 |
| [claims.py](../../backend/app/models/reviews/claims.py) | 沿用现有空引用、空知识点标签、原文 span、ID 和判定合同，不新增覆盖合同 |
| [workflow.py](../../backend/app/agents/resource_workflows/learning_documents/workflow.py) | 节点路由、普通审核前置、正文修订和发布规则保持不变 |
| [Claim 仓储](../../backend/app/db/claim/sql_repository.py) | 已允许抽取来源列表为空；Judge 证据绑定独立保存，验证读写兼容即可 |
| [Claim 查询](../../backend/app/services/runs/queries.py)、[前端行构造](../../frontend/src/features/generation/generationAudit.js) | 当前引用展示来自 Judge 的 `evidence_ids`；不需要为了本方案增加覆盖字段或页面 |

适用范围继续遵循当前流程：只有已开启 Claim 且资源满足现有准入条件时执行；讲义、案例、实操指南和复习清单沿用现有通用链，实操审核规范正文，结构化测评继续专道。Claim 默认开关、单请求资源类型约束均不改变。

本方向无需新增数据库表、公开响应字段、检查点状态或发布审批。正式实施仍需按 [仓库约束](../../AGENTS.md)建立计划，并验证五类文档工作流、API、Claim、发布与 Markdown 兼容；不能只凭此前 25 项局部测试宣称升级已验收。

## 8. 当前结论与下一步

当前保留的方向只有：**抽取只看正文，Judge 再看冻结证据。**

它可以接入现有项目，不新增审核阶段和发布机制。下一步按第 5 节编制实施计划，修改抽取输入、Prompt 和来源字段适配，再完成相应回归与效果验证。

尚未完成：业务实现、升级后的回归、真实模型质量与成本对照。事实遗漏、误分类与长文数量限制仍是已知边界，本轮不承诺解决。

## 9. 修订记录

- 2026-10-25：此前已将抽取方案收敛为“抽取不看 Evidence”，核对下游兼容性，保留历史测试及探针证据。
- 2026-10-25：根据用户明确指向，移除新增的“遗漏与误分类复核”，一并删除由其引入的定向补抽、覆盖状态、超额发布限制和覆盖发布门。第 3 节保留现状限制，第 4 节保留历史证据；这些不构成新增任务。
- 2026-10-26：按先检索后审核的顺序调整为 E2，同步与 E1 的证据范围关系；明确规范正文、修订预算及历史测试的证据边界。历史 output 产物保持原路径，不随方向编号重命名。
