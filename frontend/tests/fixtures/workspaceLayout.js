// Presentation-only fixtures: real component/style code, no account, API or model calls.
import { createApp, h, reactive, compile, nextTick } from 'vue'
import { parse } from '@vue/compiler-dom'
import ElementPlus from 'element-plus'
import { Refresh, RefreshRight, Plus, ArrowDown } from '@element-plus/icons-vue'
import 'element-plus/dist/index.css'
import '../../src/styles/theme.css'
import GenerateView from '../../src/features/generation/GenerateView.vue'
import generateSource from '../../src/features/generation/GenerateView.vue?raw'
import OnboardingView from '../../src/features/onboarding/OnboardingView.vue'
import WorkflowDetailDialog from '../../src/features/generation/WorkflowDetailDialog.vue'

// Parse the full SFC template (nested slot templates are not boundaries).
const findHeading = nodes => {
  for (const node of nodes) {
    if (node.type === 1 && node.props.some(prop => prop.type === 6 && prop.name === 'class' && prop.value?.content.split(' ').includes('resource-panel-heading'))) return node.loc.source
    const nested = node.children && findHeading(node.children)
    if (nested) return nested
  }
}
// The SFC source uses CRLF on Windows; the script marker is the reliable outer boundary.
const outerTemplate = generateSource.slice(generateSource.indexOf('<template>') + 10, generateSource.indexOf('<script')).replace(/<\/template>\s*$/, '')
const heading = findHeading(parse(outerTemplate).children)
if (!heading) throw new Error('Actual resource header not found')
const state = reactive({ view: 'controls', visible: false, node: 'diagnose', refreshes: 0, retries: 0, appends: [],
  selectedJob: { job_status: 'queued' }, resources: [], resourceId: 'r1', retrying: false, appendingResources: false,
  loadingResources: false, hasRetryableResources: false, retryableResourceTypes: [], mode: '' })
const Header = {
  __scopeId: GenerateView.__scopeId,
  setup: () => ({ ...{ Refresh, RefreshRight, Plus, ArrowDown }, state,
    selectedJob: state.selectedJob, resources: state.resources,
    retrying: false, appendingResources: false, loadingResources: false,
    hasRetryableResources: false, retryableResourceTypes: [],
    refreshStatus: () => state.refreshes++, retryGeneration: () => state.retries++,
    regeneratePendingResources: () => state.retries++, loadResourcesForSelectedJob: () => state.refreshes++,
    handleAppendCommand: command => state.appends.push(command) }),
  render: compile(`<div class="generate-page"><div class="resources-panel">${heading}</div></div>`),
}
const Onboarding = {
  __scopeId: OnboardingView.__scopeId,
  setup: () => ({ state }),
  render: compile(`<div class="fixture-scroll"><div class="onboarding-page" :class="state.mode"><section class="wizard-layout"><aside class="progress-panel"><div class="progress-heading"><div><span>LEARNING SETUP</span><strong>构建学习方向</strong></div></div><div class="progress-list"><div class="progress-card" v-for="(label,index) in ['领域','方向','问卷','诊断','资源选择']"><span class="progress-index">{{index+1}}</span><div class="progress-copy"><strong class="progress-title">{{label}}</strong><span class="progress-desc">围绕目标安排学习</span></div></div></div><div class="progress-footer"><p>以目标定义方向<br>以诊断找到起点</p></div></aside><section class="step-panel"><el-card class="work-card" shadow="never"><template #header><h2>选择学习方向</h2></template><div class="fixture-card-copy"><h3>RAG 工程链路培训</h3><p>文档解析、切分、Embedding、检索、重排、生成和评测。</p><p>长内容对齐验收</p></div></el-card></section></section></div></div>`),
}
const snapshot = {
  resource_versions: [
    { resource_id: 'r1', run_id: 'run1', resource_type: 'text', version: 1, content_text: '# 讲义 · RAG 基础\n\n## 学习目标\n\n- 理解 **检索—增强—生成**\n- 保留证据条件\n\n| 阶段 | 作用 |\n| -- | -- |\n| 离线索引 | 解析、切片与编码 |\n| 在线回答 | 召回与生成 |\n\n```python\nprint("RAG")\n```\n\n<script>window.generatedExecuted = true</script>\n\n<img src="https://invalid.test/generated.png">' },
    { resource_id: 'r2', run_id: 'run1', resource_type: 'practice', version: 2, content_text: '# 第二份资源\n\n切换只展示所选版本，不使用其他版本替代。' },
  ],
  evidence: [{ evidence_id: 'e1', run_id: 'run1', excerpt_hash: 'fixture-original-hash', excerpt: '## 回答错误时的定位顺序\n\n| 层级 | 要问的问题 | 案例 |\n| -- | -- | -- |\n| 语料 | 正确内容是否在允许的资料中 | 资料没有该日期 |\n| 解析 | 条件、表头、否定词有没有丢 | 丢了“不”或单位 |\n\n先检查 **证据条件** 与 `chunk_id`。\n\n- 保留原文限制\n- 区分无答案与故障\n\n> 检索成功不等于回答正确。\n\n```python\nprint("example")\n```\n\n<script>window.excerptExecuted = true</script>\n\n<img src="https://invalid.test/image.png" onerror="alert(1)">', locator: { title: '隔离布局教学样例', section: 'RAG 基础', line_start: 1, line_end: 5 } }],
  reviews: [{ review_id: 'review1', resource_id: 'r1', run_id: 'run1', status: 'approved', issues: [], revision_count: 0 }],
}
const summaries = {
  diagnose: "推荐难度：初级; 盲区：['RAG 基础概念（得分20%，优先补强）', 'Embedding 原理与向量化（得分40%）', '文档解析与切分策略（得分40%）', 'RAG 工程链路整体认知', '检索与生成协同流程']",
  plan: '学习路径：RAG 基础 -> 文档解析 -> Embedding', retrieve: '检索到可用证据。',
  generate: '已生成文本学习资源。', review: '普通审核未记录问题。', claim_judge: '本次没有启用事实核验。',
}
createApp({ render: () => h('div', [
  state.view === 'controls' ? h(Header) : state.view === 'onboarding' ? h(Onboarding) : null,
  h(WorkflowDetailDialog, { visible: state.visible, runId: 'run1', resourceId: state.resourceId, snapshot, claimEnabled: false,
    step: { node_name: state.node, status: 'success', step_sequence: 1, duration_ms: 9900, resource_ids: ['r1', 'r2'], evidence_refs: ['e1', 'e-missing'], output_summary: summaries[state.node], decision_reason: '建议围绕目标能力节点循序学习，先理解概念，再完成专项练习。'.repeat(4) },
    'onUpdate:visible': value => { state.visible = value }, 'onUpdate:resourceId': value => { state.resourceId = value }, onRefresh: () => state.refreshes++ }),
]) }).use(ElementPlus).mount('#app')
window.layoutFixture = { state, nextTick, snapshot }
