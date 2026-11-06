# Claim字符估算与接入配置

T31第12节已用 `neutral_estimate_v1` 取代旧tokenizer/profile执行路径。此文件保留原入口名，当前不需要下载tokenizer、不需要外部profile或校准证据。`PROFILE_PATH/PROFILE_ID`为忽略的弃用输入；项目其他领域的tokenizer依赖不删除。

默认仍 `legacy_v3`；新策略显式配置 `CLAIM_EXTRACTION_STRATEGY=neutral_estimate_v1` 和部署模型对应的 `CLAIM_EXTRACTION_CONTEXT_LIMIT`（默认1048576），原模型/endpoint/key/输出配置沿用。每批完整请求软目标4096、输出cap默认32768；原Judge输出/重试选项保持。

估算为ASCII×0.3、CJK×0.6、其他Unicode×1，完整请求（含实际schema包装）加每消息8和请求128后统一乘1.15向上取整。只对当前真正准备的mode计一次schema；下一次repair/empty/compact/fallback单独估算，不预扣所有分支。可配置系数、余量和工程预算，但它们不是精确tokenizer或已校准容量。

从仓库根运行 `python backend/scripts/claim_counting_profile.py`；输出估算版本、模型/thinking、窗口和参数，`live_executed=false`，不读资产、不调用模型、不修改配置。exit0只表示离线配置预检。未配置旧profile路径/ID时应成功；无效估算参数受配置校验拒绝。

实际网关 `attempt_observer` 在每次transport前CAS预留本次输入估算与实际输出cap，返回后在parse前以可靠usage核销；回调失败不触发供应商重试。usage高于预估时保存实际费用量和超支标记、保留有效结果，阻止下一次请求；未知usage保留预留，有效结果可保留但禁止同logical自动补调/后续抽取。Judge只做当前实际请求窗口检查，不扣抽取账本、不改变原重试规则。

新策略每次抽取超时默认180秒，实际值受网关超时、剩余累计时间、工作流deadline和执行租约进一步限制；整run抽取累计时间默认480秒。旧快照保持原冻结超时。

2.0策略/账本与独立dispatch明确版本化，旧1.0数据继续只读，旧queued/running不使用估算冒充旧策略；按失败/新run重试处理，不建设同run恢复。p037迁移及回退条件见[部署说明](../deployment.md#claim-中立抽取候选)。

专项：`python scripts/run_tests.py --suite claim-extraction-focused --suite claim-extraction-eval --output output/test-runs/claim-estimate-check`。输出目录必须为空。离线替身只证明接入、预算/失败和N+1编排，不证明真实效果。

本轮用户选择只做代码和离线验证；真实DeepSeek冒烟未执行，不能写“真实可用已验证”。后续主动真实验证按[评测规则](../evaluations/README.md)另行冻结授权预算及原始证据；最小冒烟包括短文一次抽取+一次Judge、长文分批+一次Judge和非代码实操。人工标注A/B/C质量、成本和时延对照另列，不再是接通API的前置条件。
