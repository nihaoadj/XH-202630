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

    <LearningNodeMasteryChart :key="`mastery-${report.report_revision || 'initial'}`" :data="report.learning_node_mastery_map" />

    <section class="report-visual-grid" aria-label="学情与资源匹配可视化">
      <ReportChart :data="report" />
      <ResourceDifficultyCurve :data="report.resource_difficulty_curve" />
      <LearningPathGraph :data="report.learning_path_graph" />
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
.report-hero,.next-round-panel { border:1px solid var(--line); border-radius:18px; background:rgba(255,255,255,.96); box-shadow:0 12px 28px rgba(24,60,96,.06); }
.report-hero { position:relative; display:grid; grid-template-columns:minmax(0,1fr) minmax(350px,.55fr); gap:28px; align-items:center; min-height:156px; padding:24px 28px; overflow:hidden; background:radial-gradient(circle at 86% 14%,rgba(48,203,174,.19),transparent 30%),linear-gradient(115deg,#eff6ff,#fcfdff 60%,#edf4ff); }.report-hero::after { position:absolute; right:13%; bottom:-78px; width:210px; height:150px; border:1px solid rgba(66,172,148,.15); border-radius:50%; content:''; }.report-hero-copy { position:relative; z-index:1; }
.report-kicker { display:block; color:#2058a7; font-size:12px; font-weight:800; letter-spacing:.09em; line-height:1; }.report-hero h2 { margin:8px 0 0; color:var(--ink); font-size:clamp(30px,2.3vw,40px); font-weight:800; letter-spacing:-.045em; line-height:1.08; }.report-hero p { max-width:720px; margin:10px 0 0; color:#536d8d; font-size:15px; line-height:1.6; }
.profile-selector { position:relative; z-index:1; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:9px 10px; padding:16px; border:1px solid rgba(255,255,255,.86); border-radius:14px; background:rgba(255,255,255,.76); backdrop-filter:blur(8px); }.profile-selector > span { grid-column:1 / -1; color:#5f7691; font-size:12px; font-weight:700; }.report-input { width:100%; }.profile-selector :deep(.el-button) { height:34px; border-radius:8px; font-weight:700; }
.report-snapshot { display:grid; grid-template-columns:minmax(270px,.7fr) minmax(0,1.3fr); gap:16px; padding:16px; }.learning-focus { min-width:0; padding:17px 19px; border-radius:14px; background:linear-gradient(145deg,#102d50,#1d4c7c); color:#fff; }.focus-state { display:flex; align-items:center; gap:8px; color:rgba(223,239,255,.82); font-size:12px; }.focus-state i { width:8px; height:8px; border-radius:50%; background:#8fd2ff; box-shadow:0 0 0 5px rgba(73,209,175,.14); }.learning-focus > strong { display:block; margin-top:12px; overflow:hidden; font-size:22px; text-overflow:ellipsis; white-space:nowrap; }.focus-goal { display:block; min-height:21px; margin-top:6px; overflow:hidden; color:rgba(218,235,252,.78); font-size:13px; text-overflow:ellipsis; white-space:nowrap; }.focus-meta { display:flex; gap:18px; margin-top:15px; padding-top:11px; border-top:1px solid rgba(218,235,252,.2); }.focus-meta span { color:rgba(218,235,252,.72); font-size:11px; }.focus-meta b { display:block; margin-top:4px; color:#fff; font-size:14px; }
.summary-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }.summary-metric { display:flex; flex-direction:column; justify-content:center; min-width:0; padding:14px; border:1px solid #dce7f2; border-radius:13px; background:#fbfdff; }.summary-metric.mint { border-color:#cfe2ff; background:#f5f9ff; }.summary-metric.blue { border-color:#d7e5fb; background:#f4f8ff; }.summary-metric.amber { border-color:#f4e3c7; background:#fffaf1; }.summary-metric.slate { border-color:#e1e7ee; background:#f8fafc; }.summary-metric span { overflow:hidden; color:#6c8199; font-size:12px; font-weight:650; text-overflow:ellipsis; white-space:nowrap; }.summary-metric strong { margin-top:8px; color:#183654; font-size:28px; line-height:1; }.summary-metric small { margin-top:6px; overflow:hidden; color:#8190a4; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }
.report-detail-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; }.report-section { min-height:276px; padding:20px; }.section-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; margin-bottom:16px; }.section-heading h3,.next-round-panel h3 { margin:7px 0 0; color:var(--ink); font-size:22px; font-weight:800; letter-spacing:-.035em; line-height:1.1; }.section-count { padding:6px 9px; border-radius:999px; background:#eff6fc; color:#54728f; font-size:12px; font-weight:700; white-space:nowrap; }
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

/* The report header is a compact control surface: keep the context, alerts,
   filters and metrics visually related without making them compete. */
.report-hero {
  grid-template-columns: minmax(0, 1fr) minmax(310px, .48fr);
  gap: 10px 24px;
  padding: 18px 20px 20px;
  border-color: #d8e5f2;
  border-radius: 12px;
  background:
    radial-gradient(circle at 88% 0%, rgba(74, 157, 255, .14), transparent 27%),
    linear-gradient(135deg, #f7fbff 0%, #ffffff 55%, #f4f9ff 100%);
  box-shadow: 0 10px 24px rgba(25, 73, 120, .07);
}
.report-hero-copy { align-self: center; padding: 6px 0 6px 2px; }
.report-kicker { color: #2463b4; font-size: 11px; letter-spacing: .11em; }
.report-hero h2 { margin-top: 7px; color: #102b4b; font-size: clamp(30px, 2.45vw, 38px); letter-spacing: -.055em; }
.report-focus {
  min-width: 0;
  padding: 12px 15px;
  border: 1px solid #d9e8f6;
  border-radius: 11px;
  background: rgba(255, 255, 255, .78);
  box-shadow: 0 5px 14px rgba(35, 92, 148, .045);
}
.report-focus > span { color: #607b97; font-size: 11px; font-weight: 750; }
.report-focus i { width: 7px; height: 7px; background: #438ff0; box-shadow: 0 0 0 5px rgba(67, 143, 240, .12); }
.report-focus strong { margin-top: 8px; color: #183b61; font-size: 17px; }
.report-focus b { color: #4c6e8d; font-size: 11px; font-weight: 750; }
.report-focus small {
  grid-column: 1 / -1;
  margin-top: 3px;
  overflow: hidden;
  color: #7389a0;
  font-size: 11px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.report-hero > .el-alert {
  grid-column: 1 / -1;
  margin: 0;
  min-height: 40px;
  padding: 9px 13px;
  border: 1px solid #d6eac9;
  border-radius: 9px;
  background: #f2faec;
}
.report-hero > .el-alert :deep(.el-alert__title) { color: #5d9f3b; font-size: 13px; font-weight: 700; line-height: 1.45; }
.report-hero > .el-alert--warning { border-color: #f1dfb6; background: #fff9eb; }
.report-hero > .el-alert--warning :deep(.el-alert__title) { color: #9b742b; }
.report-selector-row {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) 112px max-content;
  gap: 8px 10px;
  align-items: center;
  padding: 8px 0 0;
  border-top: 1px solid #e5edf5;
}
.report-selector-row > span { color: #5d7691; font-size: 12px; font-weight: 800; }
.report-selector-row :deep(.el-select__wrapper) {
  min-height: 35px;
  border: 1px solid #d7e5f2;
  border-radius: 8px;
  box-shadow: 0 1px 2px rgba(35, 75, 114, .03);
}
.report-selector-row :deep(.el-select__wrapper.is-focused) { border-color: #5b9bea; box-shadow: 0 0 0 3px rgba(91, 155, 234, .12); }
.report-refresh-button {
  height: 35px !important;
  min-width: 100px;
  border: 0 !important;
  border-radius: 8px !important;
  background: #2463b4 !important;
  box-shadow: 0 6px 12px rgba(36, 99, 180, .2);
}
.report-refresh-button:hover, .report-refresh-button:focus-visible { background: #1b4f94 !important; }
.report-summary-metrics { grid-column: 1 / -1; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.summary-metric {
  position: relative;
  min-height: 70px;
  padding: 10px 13px 9px;
  overflow: hidden;
  border: 1px solid #dce8f3;
  border-radius: 9px;
  background: rgba(255, 255, 255, .72);
}
.summary-metric::before { position: absolute; inset: 0 auto 0 0; width: 3px; background: #4d91df; content: ''; }
.summary-metric.mint::before { background: #39b58d; }
.summary-metric.blue::before { background: #4d91df; }
.summary-metric.amber::before { background: #e2a13f; }
.summary-metric.slate::before { background: #8295aa; }
.summary-metric span { color: #6a8098; font-size: 11px; }
.summary-metric strong { margin-top: 5px; color: #183654; font-size: 24px; }
.summary-metric small { margin-top: 4px; color: #8a9bae; font-size: 10px; }

@media (max-width: 860px) {
  .report-hero { grid-template-columns: 1fr; }
  .report-focus { display: block; }
  .report-focus > span, .report-focus small { display: block; }
  .report-selector-row { grid-template-columns: auto minmax(0, 1fr) 112px max-content; }
}
@media (max-width: 560px) {
  .report-hero { padding: 16px; }
  .report-selector-row { grid-template-columns: minmax(0, 1fr) 112px max-content; }
  .report-selector-row > span { grid-column: 1 / -1; }
  .report-refresh-button { min-width: 42px; padding: 0 11px; }
  .report-summary-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .summary-metric { min-height: 66px; }
}

</style>
