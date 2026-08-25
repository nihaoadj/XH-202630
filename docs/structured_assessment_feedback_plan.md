# 结构化测试题与反馈判分

分阶测试题从 Markdown 直出改为节点级 `AssessmentPackageV2`。批次有 N 个目标能力节点时，Agent 调用 N 次；每次只处理一个节点并固定生成 2 道单选、1 道多选和 2 道问答。完整 JSON 是唯一题目事实，Markdown 仅为不含答案的确定性阅读投影。

每题保存知识点标签、冻结 evidence、题型、难度阶段和服务端分配的分值：两道单选固定为“基础”，一道多选固定为“进阶”，两道问答固定为“挑战”。单选为满分或零分；多选全对满分、只选正确答案的非空子集半分、包含错误选项零分；问答通过 LLMGateway 根据题目、用户答案、参考答案与 rubric 评分。反馈报告输出 100 分制总分及逐题对错、分数、节点和知识点。

模型只生成一次包含答案、参考答案、rubric 和 evidence ID 的内部 canonical JSON。资源审核读取该内部题卷，检查答案、rubric、证据 allow-list、题型配额和难度阶段；审核通过后，服务端从同一 JSON 确定性派生无答案 Markdown 与脱敏题目投影供前端使用。公开投影不得包含答案、参考答案、rubric、evidence ID 或审核信息。结构化测评不进入通用 Markdown Claim 抽取；Claim 审核记录为 `structured_assessment_internal`，避免对脱敏展示文本进行错误审计。

测评资源的专有语义审核位于 `agents/resource_workflows/learning_documents/specialized_reviews/assessment_scope.py`，由 `reviewer_agent.py` 在通用内容审核前编排。它按题检查题干、选项、答案、参考答案和 rubric 是否仅覆盖冻结能力节点、允许知识点和该题 evidence；任一题越界或证据不足会产生“分阶测试题”的定向返工指令，审核器不可用或返回结构不合法则失败关闭为人工复核。

反馈会话优先读取已发布且 payload hash 校验通过的结构化测试题；没有此类资源时才从正式测评题库按能力节点回退选题。结构化 payload 损坏时失败关闭，不能混入题库题。

真实 Provider 评测必须显式设置 `RUN_LIVE_LLM=1`，固定运行至少 20 批，分别记录节点调用成功率、完整批次成功率、审核通过率、最终发布率、token、延迟、重试与失败原因。最终发布率需达到至少 90%，且发布资源不得存在结构违规或答案泄漏。
