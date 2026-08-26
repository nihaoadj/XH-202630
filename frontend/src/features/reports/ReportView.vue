<template>
  <div class="report-page">
    <section class="report-hero">
      <div class="report-hero-copy">
        <span class="report-kicker">LEARNING REPORT</span>
        <h2>学习报告</h2>
      </div>

      <div class="report-focus">
        <span><i />当前学习方向</span>
        <strong>{{ directionName }}</strong>
        <b>画像能力等级 {{ report.skill_level || activeProfile?.skill_level || '待诊断' }}</b>
        <small v-if="tierProgress.active_tier">当前学习等级：{{ tierLabel(tierProgress.active_tier) }} · 当前节点：{{ currentNodeNames || '待选择' }} · 已解锁至第 {{ tierProgress.highest_unlocked_tier }} 阶</small>
      </div>
      <el-alert
        v-if="report.report_availability?.status === 'calibration_pending'"
        type="warning"
        :closable="false"
        :title="report.report_availability.message || '初始诊断尚未完成，暂不生成正式学习结论'"
      />
      <el-alert
        v-if="report.initial_diagnostic?.final_tier"
        type="success"
        :closable="false"
        :title="`初始校准：问卷预判第 ${report.initial_diagnostic.questionnaire_tier} 阶，最终第 ${report.initial_diagnostic.final_tier} 阶${report.initial_diagnostic.downgraded ? '（已降阶校准）' : ''}`"
      />

      <div class="profile-selector report-selector-row">
        <span>学习画像</span>
        <el-select v-model="selectedLearnerId" placeholder="选择学习画像" class="report-input" filterable @change="handleProfileChange">
          <el-option v-for="item in profileOptions" :key="item.learner_id" :label="item.label" :value="item.learner_id" />
        </el-select>
        <el-select v-model="windowDays" class="window-select" aria-label="报告时间窗口" @change="restartStream"><el-option :value="7" label="近 7 天" /><el-option :value="30" label="近 30 天" /><el-option :value="90" label="近 90 天" /></el-select>
        <el-button class="report-refresh-button" type="primary" :icon="Refresh" @click="() => loadReport(true)" :disabled="!selectedLearnerId">更新报告</el-button>
      </div>

      <div class="summary-metrics report-summary-metrics">
        <article class="summary-metric mint"><span>学习资源</span><strong>{{ metricSummary.resource_count || 0 }}</strong><small>已生成资源批次</small></article>
        <article class="summary-metric blue"><span>练习反馈</span><strong>{{ metricSummary.feedback_count || 0 }}</strong><small>已记录练习结果</small></article>
        <article class="summary-metric amber"><span>客观正确率</span><strong>{{ averageCorrectRate }}</strong><small>{{ streamStatusLabel }}</small></article>
        <article class="summary-metric slate"><span>待巩固知识点</span><strong>{{ metricSummary.weak_point_count || 0 }}</strong><small>优先进入下一轮学习</small></article>
      </div>
    </section>

    <ReportChart :data="report" />

    <section class="report-visual-grid" aria-label="学情与资源匹配可视化">
      <LearningNodeMasteryChart :key="`mastery-${report.report_revision || 'initial'}`" :data="report.learning_node_mastery_map" />
      <ResourceDifficultyCurve :data="report.resource_difficulty_curve" />
      <LearningPathGraph :data="report.learning_path_graph" />
    </section>

    <section class="mastery-panel" aria-labelledby="mastery-heading">
      <div class="section-heading">
        <div><span class="report-kicker">ABILITY MASTERY</span><h3 id="mastery-heading">能力节点掌握</h3></div>
        <span class="section-count">画像版本 {{ report.as_of_profile_version || report.profile_version || 1 }}</span>
      </div>
      <p v-if="!masterySummary.medium_or_high_confidence_count" class="mastery-warning" role="status">当前还没有客观能力证据；低置信自评仅用于安排首批学习重点，不代表已经掌握或确认薄弱。</p>
      <el-empty v-if="!abilityNodes.length" description="当前方向还没有可展示的能力节点" :image-size="62" />
      <div v-else class="mastery-grid" role="list">
        <article v-for="node in abilityNodes" :key="node.skill_node_id" class="mastery-card" :class="`status-${node.mastery.status}`" role="listitem" tabindex="0">
          <div class="mastery-card-head"><strong>{{ node.name }}</strong><span>{{ statusLabel(node.mastery.status) }}</span></div>
           <div class="mastery-score"><b>{{ masteryPercent(node.mastery) }}</b><small>置信度 {{ confidenceLabel(node.mastery.confidence) }}</small></div>
           <p v-if="assessmentConclusion(node).conclusion">结论：{{ conclusionLabel(assessmentConclusion(node).conclusion) }} · {{ trustLabel(assessmentConclusion(node).trust_status) }} · {{ assessmentConclusion(node).formal_session_count || 0 }} 次正式测评</p>
           <p v-if="diagnosticMeasurement(node).measurement_status === 'needs_evidence'">本次 {{ diagnosticMeasurement(node).correct_question_count }}/{{ diagnosticMeasurement(node).valid_question_count }} 正确，证据不足，暂不判定掌握度。</p>
          <p v-else-if="diagnosticMeasurement(node).measurement_status === 'measured'">诊断 {{ diagnosticMeasurement(node).correct_question_count }}/{{ diagnosticMeasurement(node).valid_question_count }} 正确 · 已覆盖 {{ (diagnosticMeasurement(node).covered_dimensions || []).length }} 个维度</p>
          <p v-if="relationshipLabels(node, abilityNodes).prerequisites.length">前置：{{ relationshipLabels(node, abilityNodes).prerequisites.join('、') }}</p>
          <p v-if="relationshipLabels(node, abilityNodes).children.length">后继：{{ relationshipLabels(node, abilityNodes).children.join('、') }}</p>
          <em v-if="typeof node.trend_delta === 'number'">客观趋势 {{ node.trend_delta > 0 ? '+' : '' }}{{ Math.round(node.trend_delta * 100) }}%</em>
        </article>
      </div>
      <div class="focus-explanation">
        <h4>下一批学习方式</h4>
        <p>反馈完成后可选择“强化薄弱点”或“学习新知识”。未学习节点不等同于薄弱点；已学习但待测的节点也不会被误标为未掌握。</p>
        <ol v-if="generationOptions.reinforce_weakness?.length"><li v-for="item in generationOptions.reinforce_weakness.slice(0, 3)" :key="`focus-${item.skill_node_id}`"><strong>强化：{{ item.name }}</strong><span>{{ (item.reason_codes || []).join('；') }}</span></li></ol>
        <ol v-else-if="weaknessPriorities.length"><li v-for="item in weaknessPriorities.slice(0, 3)" :key="item.skill_node_id"><strong>{{ abilityName(item.skill_node_id) }}</strong><span>{{ (item.reason_codes || []).map(focusReason).join('；') }}</span></li></ol>
      </div>
    </section>

    <section class="report-section" aria-labelledby="credibility-heading">
      <div class="section-heading"><div><span class="report-kicker">TEXT RESOURCE EVIDENCE</span><h3 id="credibility-heading">文本资源可信证据</h3></div><span class="section-count">可信 {{ resourceCredibility.trusted_count || 0 }} / {{ resourceCredibility.total_count || 0 }}</span></div>
      <p class="mastery-warning">可信等级表示平台可验证的生成质量证据，不等价于来源机构权威性或绝对事实正确。</p>
      <el-empty v-if="!recentResourceCredibility.length" description="尚无可核验的已发布文本资源" :image-size="52" />
      <div v-else class="resource-list"><article v-for="item in recentResourceCredibility" :key="item.resource_id" class="resource-item"><span class="resource-type">{{ item.grade }}</span><div><strong>{{ item.topic || item.resource_type }}</strong><p>审核 {{ item.publication_review.status }} · Claim {{ item.claim_support.status }} · 溯源 {{ item.source_traceability.status }}</p></div><span class="difficulty-tag">{{ item.resource_type }}</span></article></div>
    </section>

    <section class="next-round-panel">
      <div><span class="report-kicker">NEXT LEARNING CYCLE</span><h3>下一轮学习重点</h3><p>建议优先围绕以下知识点进行练习与资源生成，持续缩小当前学习盲区。</p></div>
      <div class="suggestion-list"><span v-for="item in nextSuggestions" :key="item">{{ item }}</span><em v-if="!nextSuggestions.length">完成一次能力诊断后，将在这里展示个性化学习重点。</em></div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { knowledgeApi, profileApi } from '../../api'
import { useAppStore } from '../../stores/app'
import ReportChart from './ReportChart.vue'
import LearningNodeMasteryChart from './LearningNodeMasteryChart.vue'
import ResourceDifficultyCurve from './ResourceDifficultyCurve.vue'
import LearningPathGraph from './LearningPathGraph.vue'
import { focusReason, masteryPercent, relationshipLabels, statusLabel } from './masteryViewModel'
import { learningReportApi } from './api'
import { ReportStreamClient } from './reportStreamClient'

const store = useAppStore()
const selectedLearnerId = ref(localStorage.getItem('last_learner_id') || store.currentLearnerId || '')
const profiles = ref([])
const tracks = ref([])
const report = reactive({})
const windowDays = ref(30)
const streamStatus = ref('closed')
const metricSummary = computed(() => report.metric_summary || {})
const nextSuggestions = computed(() => report.next_suggestions || report.weak_points || [])
const abilityNodes = computed(() => report.ability_nodes || [])
const masterySummary = computed(() => report.mastery_summary || {})
const weaknessPriorities = computed(() => report.weakness_priorities || [])
const diagnosticMeasurements = computed(() => report.diagnostic_measurements || {})
const assessmentConclusions = computed(() => report.assessment_conclusions || {})
const generationOptions = computed(() => report.generation_options || {})
const tierProgress = computed(() => report.tier_progress || generationOptions.value.tier_progress || {})
const resourceCredibility = computed(() => report.resource_credibility_summary || {})
const recentResourceCredibility = computed(() => report.recent_resource_credibility || [])
const activeProfile = computed(() => profiles.value.find((item) => item.learner_id === selectedLearnerId.value) || null)
const directionName = computed(() => resolveTrackName(activeProfile.value?.knowledge_base_id))
const averageCorrectRate = computed(() => formatPercent(report.learning_activity?.verified_accuracy ?? metricSummary.value.average_correct_rate))
const streamStatusLabel = computed(() => ({ connecting: '正在连接自动更新', live: '自动更新已开启', reconnecting: '正在重连自动更新', polling: '已降级为定时刷新', offline: '当前离线', closed: '自动更新已停止' })[streamStatus.value] || '自动更新')
const profileOptions = computed(() => profiles.value.map((profile) => ({ ...profile, label: `${profileDisplayName(profile)} / ${resolveTrackName(profile.knowledge_base_id)} / ${profile.skill_level || '未分级'}` })))

function resolveTrackName(trackId) {
  return tracks.value.find((item) => item.track_id === trackId || item.knowledge_base_id === trackId)?.name || trackId || '未选择学习方向'
}
function profileDisplayName(profile) {
  const snapshot = profile?.learning_preferences?.metadata?.user_profile_snapshot
  return snapshot?.display_name || snapshot?.name || profile?.learner_type || '未命名画像'
}
function formatPercent(value) { return typeof value === 'number' ? `${Math.round(value * 100)}%` : '--' }
function tierLabel(value) { return ({ 1: '初级', 2: '中级', 3: '高级' })[value] || `第 ${value} 阶` }
const currentNodeNames = computed(() => (report.current_learning_state?.current_node_ids || []).map(abilityName).join('、'))
function confidenceLabel(value) { return ({ none: '无', low: '低', medium: '中', high: '高' })[value] || value || '无' }
function abilityName(nodeId) { return abilityNodes.value.find((item) => item.skill_node_id === nodeId)?.name || nodeId }
function diagnosticMeasurement(node) { return diagnosticMeasurements.value[node?.skill_node_id] || {} }
function assessmentConclusion(node) { return assessmentConclusions.value[node?.skill_node_id] || {} }
function conclusionLabel(value) { return ({ confirmed_mastery: '已确认掌握', baseline_observation: '初始基线，待复测确认', awaiting_confirmation: '待第二次正式测评确认', needs_reinforcement: '需巩固并重新测评', unassessed: '尚未测评' })[value] || value || '待测评' }
function trustLabel(value) { return ({ high: '高可信', medium: '中可信', provisional: '暂定', none: '无客观证据' })[value] || value || '待确认' }

async function loadProfiles() {
  const [profileRes, domainRes] = await Promise.all([profileApi.list({ page: 1, page_size: 50 }), knowledgeApi.listDomains()])
  profiles.value = profileRes.data.items || profileRes.data.profiles || []
  tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
  if (!profiles.value.length) { selectedLearnerId.value = ''; return }
  if (!profiles.value.some((item) => item.learner_id === selectedLearnerId.value)) selectedLearnerId.value = store.currentLearnerId || profiles.value[0].learner_id
}
const stream = new ReportStreamClient({
  onStatus: (status) => { streamStatus.value = status },
  onReport: (data) => Object.assign(report, data),
  fetchReport: async ({ learnerId, windowDays: days, etag }) => {
    const res = await learningReportApi.get(learnerId, days, etag)
    if (res.status === 304) return null
    return { data: res.data, revision: res.data.report_revision }
  },
})

async function loadReport(force = false) {
  if (!selectedLearnerId.value) { ElMessage.warning('请先选择学习画像'); return }
  try {
    const res = await learningReportApi.get(selectedLearnerId.value, windowDays.value, force ? null : report.report_revision)
    if (res.status === 304) return
    Object.assign(report, res.data)
    localStorage.setItem('last_learner_id', selectedLearnerId.value)
    stream.start({ learnerId: selectedLearnerId.value, windowDays: windowDays.value, revision: report.report_revision })
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '报告查询失败')
  }
}
async function handleProfileChange() {
  stream.stop()
  Object.keys(report).forEach((key) => delete report[key])
  await loadReport(true)
}
function restartStream() { if (selectedLearnerId.value) loadReport() }
function handleOffline() { stream.stop(); streamStatus.value = 'offline' }
function handleVisibility() {
  if (document.visibilityState === 'visible') restartStream()
  else if (streamStatus.value === 'polling') stream.stop()
}
onMounted(async () => {
  await loadProfiles(); if (selectedLearnerId.value) await loadReport()
  window.addEventListener('online', restartStream); window.addEventListener('offline', handleOffline)
  document.addEventListener('visibilitychange', handleVisibility)
})
onBeforeUnmount(() => {
  stream.stop(); window.removeEventListener('online', restartStream); window.removeEventListener('offline', handleOffline)
  document.removeEventListener('visibilitychange', handleVisibility)
})
</script>

<style scoped>
.report-page { --ink:#10233f; --muted:#627692; --line:#dbe6f2; display:flex; flex-direction:column; gap:16px; }
.report-hero,.report-snapshot,.report-section,.next-round-panel { border:1px solid var(--line); border-radius:18px; background:rgba(255,255,255,.96); box-shadow:0 12px 28px rgba(24,60,96,.06); }
.report-hero { position:relative; display:grid; grid-template-columns:minmax(0,1fr) minmax(350px,.55fr); gap:28px; align-items:center; min-height:156px; padding:24px 28px; overflow:hidden; background:radial-gradient(circle at 86% 14%,rgba(48,203,174,.19),transparent 30%),linear-gradient(115deg,#eff6ff,#fcfdff 60%,#edf4ff); }.report-hero::after { position:absolute; right:13%; bottom:-78px; width:210px; height:150px; border:1px solid rgba(66,172,148,.15); border-radius:50%; content:''; }.report-hero-copy { position:relative; z-index:1; }
.report-kicker { display:block; color:#2058a7; font-size:12px; font-weight:800; letter-spacing:.09em; line-height:1; }.report-hero h2 { margin:8px 0 0; color:var(--ink); font-size:clamp(30px,2.3vw,40px); font-weight:800; letter-spacing:-.045em; line-height:1.08; }.report-hero p { max-width:720px; margin:10px 0 0; color:#536d8d; font-size:15px; line-height:1.6; }
.profile-selector { position:relative; z-index:1; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:9px 10px; padding:16px; border:1px solid rgba(255,255,255,.86); border-radius:14px; background:rgba(255,255,255,.76); backdrop-filter:blur(8px); }.profile-selector > span { grid-column:1 / -1; color:#5f7691; font-size:12px; font-weight:700; }.report-input { width:100%; }.profile-selector :deep(.el-button) { height:34px; border-radius:8px; font-weight:700; }
.report-snapshot { display:grid; grid-template-columns:minmax(270px,.7fr) minmax(0,1.3fr); gap:16px; padding:16px; }.learning-focus { min-width:0; padding:17px 19px; border-radius:14px; background:linear-gradient(145deg,#102d50,#1d4c7c); color:#fff; }.focus-state { display:flex; align-items:center; gap:8px; color:rgba(223,239,255,.82); font-size:12px; }.focus-state i { width:8px; height:8px; border-radius:50%; background:#8fd2ff; box-shadow:0 0 0 5px rgba(73,209,175,.14); }.learning-focus > strong { display:block; margin-top:12px; overflow:hidden; font-size:22px; text-overflow:ellipsis; white-space:nowrap; }.focus-goal { display:block; min-height:21px; margin-top:6px; overflow:hidden; color:rgba(218,235,252,.78); font-size:13px; text-overflow:ellipsis; white-space:nowrap; }.focus-meta { display:flex; gap:18px; margin-top:15px; padding-top:11px; border-top:1px solid rgba(218,235,252,.2); }.focus-meta span { color:rgba(218,235,252,.72); font-size:11px; }.focus-meta b { display:block; margin-top:4px; color:#fff; font-size:14px; }
.summary-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }.summary-metric { display:flex; flex-direction:column; justify-content:center; min-width:0; padding:14px; border:1px solid #dce7f2; border-radius:13px; background:#fbfdff; }.summary-metric.mint { border-color:#cfe2ff; background:#f5f9ff; }.summary-metric.blue { border-color:#d7e5fb; background:#f4f8ff; }.summary-metric.amber { border-color:#f4e3c7; background:#fffaf1; }.summary-metric.slate { border-color:#e1e7ee; background:#f8fafc; }.summary-metric span { overflow:hidden; color:#6c8199; font-size:12px; font-weight:650; text-overflow:ellipsis; white-space:nowrap; }.summary-metric strong { margin-top:8px; color:#183654; font-size:28px; line-height:1; }.summary-metric small { margin-top:6px; overflow:hidden; color:#8190a4; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }
.report-detail-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; }.report-section { min-height:276px; padding:20px; }.section-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; margin-bottom:16px; }.section-heading h3,.next-round-panel h3 { margin:7px 0 0; color:var(--ink); font-size:22px; font-weight:800; letter-spacing:-.035em; line-height:1.1; }.section-count { padding:6px 9px; border-radius:999px; background:#eff6fc; color:#54728f; font-size:12px; font-weight:700; white-space:nowrap; }
.resource-list,.feedback-list { display:grid; gap:9px; }.resource-item { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:11px; padding:12px; border:1px solid #e0e8f1; border-radius:11px; background:#fbfdff; }.resource-type { padding:5px 7px; border-radius:7px; background:#eaf3ff; color:#2e72c7; font-size:11px; font-weight:800; white-space:nowrap; }.resource-item div { min-width:0; }.resource-item strong,.resource-item p { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.resource-item strong { color:#203b5a; font-size:14px; }.resource-item p { margin:5px 0 0; color:#72849a; font-size:12px; }.difficulty-tag { padding:5px 7px; border:1px solid #cfe2ff; border-radius:999px; background:#f5f9ff; color:#228265; font-size:11px; white-space:nowrap; }.feedback-item { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px; border:1px solid #e0e8f1; border-radius:11px; background:#fbfdff; }.feedback-item div { min-width:0; }.feedback-item strong,.feedback-item span { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.feedback-item strong { color:#203b5a; font-size:14px; }.feedback-item span { margin-top:5px; color:#75889f; font-size:12px; }.feedback-item b { flex:0 0 auto; color:#2058a7; font-size:22px; }
.next-round-panel { display:grid; grid-template-columns:minmax(260px,.8fr) minmax(0,1.2fr); gap:24px; align-items:center; padding:20px 24px; overflow:hidden; background:linear-gradient(105deg,#f9fcff,#eef5ff); }.next-round-panel p { margin:9px 0 0; color:#5c738d; font-size:14px; line-height:1.55; }.suggestion-list { display:flex; flex-wrap:wrap; gap:9px; align-content:center; }.suggestion-list span { padding:9px 12px; border:1px solid #cfe2ff; border-radius:999px; background:rgba(255,255,255,.72); color:#227a64; font-size:13px; font-weight:700; }.suggestion-list em { color:#72849a; font-size:13px; font-style:normal; }
@media (max-width:1180px) { .report-snapshot { grid-template-columns:1fr; }.report-hero { grid-template-columns:1fr; }.profile-selector { max-width:560px; }.next-round-panel { grid-template-columns:1fr; gap:16px; } } @media (max-width:860px) { .report-page { gap:14px; }.report-detail-grid { grid-template-columns:1fr; }.summary-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }.report-hero { padding:22px; }.report-section { min-height:0; }.resource-item { grid-template-columns:auto minmax(0,1fr); }.difficulty-tag { grid-column:2; justify-self:start; }.next-round-panel { padding:20px; } } @media (max-width:560px) { .report-hero h2 { font-size:30px; }.profile-selector { grid-template-columns:1fr; }.profile-selector :deep(.el-button) { width:100%; }.summary-metrics { grid-template-columns:1fr; }.focus-meta { gap:12px; }.resource-item { grid-template-columns:1fr; }.resource-type { justify-self:start; }.difficulty-tag { grid-column:auto; }.report-section { padding:18px; } }

/* Report context is compact so charts and actionable details remain above the fold. */
.report-page { gap: 12px; }
.report-visual-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
.report-visual-grid > :last-child { grid-column:1 / -1; }
.report-hero {
  grid-template-columns: minmax(0, 1fr) minmax(260px, .38fr);
  gap: 11px 22px;
  min-height: 0;
  padding: 16px 20px;
  border-radius: 10px;
}
.report-hero::after { right: 10%; bottom: -108px; width: 170px; height: 126px; }
.report-hero h2 { margin-top: 5px; font-size: 28px; letter-spacing: 0; }
.report-focus {
  position: relative;
  z-index: 1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 5px 12px;
  padding: 11px 14px;
  border: 1px solid rgb(255 255 255 / 88%);
  border-radius: 10px;
  background: rgb(255 255 255 / 76%);
}
.report-focus > span { grid-column: 1 / -1; display: flex; align-items: center; gap: 8px; color: #5f7691; font-size: 11px; }
.report-focus i { width: 8px; height: 8px; border-radius: 50%; background: #4a90ff; box-shadow: 0 0 0 5px rgb(27 182 149 / 12%); }
.report-focus strong { overflow: hidden; color: #18354d; font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }
.report-focus b { color: #52708a; font-size: 11px; font-weight: 700; white-space: nowrap; }
.report-selector-row { grid-column: 1 / -1; grid-template-columns: auto minmax(0, 1fr) auto max-content; align-items: center; max-width: none; padding: 0; border: 0; background: transparent; }
.report-selector-row > span { grid-column: auto; color: #47637e; font-size: 12px; font-weight: 800; white-space: nowrap; }
.report-selector-row :deep(.el-select__wrapper) { min-height: 34px; }
.window-select { width: 112px; }
.report-refresh-button {
  min-width: 108px;
  border-color: #2058a7 !important;
  color: #fff !important;
  background: #2058a7 !important;
  box-shadow: 0 7px 14px rgb(35 110 98 / 18%);
}
.report-refresh-button:hover, .report-refresh-button:focus-visible { border-color: #17447e !important; background: #17447e !important; }
.report-refresh-button.is-disabled { border-color: #d7e3e6 !important; color: #8ca1ae !important; background: #e8f0f2 !important; box-shadow: none; }
.report-summary-metrics { grid-column: 1 / -1; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.summary-metric { min-height: 66px; padding: 9px 12px; border-radius: 8px; }
.summary-metric strong { margin-top: 4px; font-size: 21px; }
.summary-metric small { margin-top: 3px; font-size: 10px; }
.report-detail-grid { gap: 12px; }
.report-section { padding: 17px; border-radius: 10px; }

@media (max-width: 1180px) {
  .report-hero { grid-template-columns: minmax(0, 1fr) minmax(230px, .42fr); }
}
@media (max-width: 860px) {
  .report-hero { grid-template-columns: 1fr; }
  .report-focus { display: none; }
  .report-visual-grid { grid-template-columns:1fr; }
  .report-visual-grid > :last-child { grid-column:auto; }
}
@media (max-width: 560px) {
  .report-selector-row { grid-template-columns: minmax(0, 1fr) auto max-content; }
  .report-selector-row > span { grid-column: 1 / -1; }
  .report-refresh-button { width: auto !important; min-width: 42px; padding: 0 11px; }
  .report-summary-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.mastery-panel { padding:20px; border:1px solid var(--line); border-radius:10px; background:rgba(255,255,255,.96); box-shadow:0 12px 28px rgba(24,60,96,.06); }
.mastery-warning { margin:0 0 14px; padding:11px 13px; border:1px solid #efd9ad; border-radius:10px; color:#795817; background:#fff9eb; font-size:13px; line-height:1.55; }
.mastery-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.mastery-card { min-width:0; padding:14px; border:1px solid #dce7f2; border-radius:11px; background:#fbfdff; outline:none; }
.mastery-card:focus-visible { box-shadow:0 0 0 3px rgba(32,88,167,.22); border-color:#2058a7; }
.mastery-card.status-weak { border-color:#efc8be; background:#fff8f5; }
.mastery-card.status-self_reported { border-style:dashed; border-color:#e1c77f; background:#fffbef; }
.mastery-card.status-mastered { border-color:#b9dfd5; background:#f4fbf8; }
.mastery-card-head { display:flex; justify-content:space-between; gap:10px; align-items:flex-start; }
.mastery-card-head strong { color:#193754; font-size:15px; }.mastery-card-head span { flex:0 0 auto; padding:4px 7px; border-radius:999px; color:#45627d; background:#edf3f8; font-size:11px; font-weight:700; }
.mastery-score { display:flex; align-items:baseline; gap:10px; margin-top:12px; }.mastery-score b { color:#2058a7; font-size:23px; }
.mastery-score small,.mastery-card p,.mastery-card em { color:#6d8198; font-size:11px; }.mastery-card p { margin:7px 0 0; line-height:1.45; }.mastery-card em { display:block; margin-top:9px; font-style:normal; font-weight:700; }
.focus-explanation { margin-top:14px; padding:14px; border-radius:11px; background:#f4f8ff; }.focus-explanation h4 { margin:0; color:#193754; font-size:15px; }.focus-explanation p { margin:8px 0 0; color:#667c94; font-size:13px; }
.focus-explanation ol { display:grid; gap:7px; margin:10px 0 0; padding-left:21px; }.focus-explanation li { color:#365572; font-size:13px; }.focus-explanation li strong { margin-right:8px; }.focus-explanation li span { color:#6a7f95; }
@media (max-width:860px) { .mastery-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:560px) { .mastery-grid { grid-template-columns:1fr; } }
</style>
