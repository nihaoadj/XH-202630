<template>
  <div class="report-page">
    <section class="report-hero" aria-labelledby="report-overview-title">
      <header class="report-overview-head">
        <div class="report-hero-copy">
          <span class="report-kicker">01 / LEARNING REPORT</span>
          <h2 id="report-overview-title">学习报告</h2>
        </div>
        <div class="report-focus">
          <span><i aria-hidden="true" />当前学习方向<small>LEARNING FOCUS</small></span>
          <strong>{{ directionName }}</strong>
          <b>画像能力等级 {{ report.skill_level || activeProfile?.skill_level || '待诊断' }}</b>
        </div>
      </header>

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
        <div class="report-field report-profile-field">
          <label>学习画像<span>PROFILE</span></label>
          <el-select v-model="selectedLearnerId" placeholder="选择学习画像" class="report-input" aria-label="学习画像" popper-class="report-control-dropdown" filterable @change="handleProfileChange">
            <el-option v-for="item in profileOptions" :key="item.learner_id" :label="item.label" :value="item.learner_id" />
          </el-select>
        </div>
        <div class="report-field report-window-field">
          <label>时间范围<span>PERIOD</span></label>
          <el-select v-model="windowDays" class="window-select" aria-label="报告时间窗口" popper-class="report-control-dropdown" @change="restartStream">
            <el-option :value="7" label="近 7 天" />
            <el-option :value="30" label="近 30 天" />
            <el-option :value="90" label="近 90 天" />
          </el-select>
        </div>
        <el-button class="report-refresh-button" type="primary" :icon="Refresh" :loading="reportLoading" @click="() => loadReport(true)" :disabled="!selectedLearnerId">更新报告</el-button>
      </div>

      <div v-if="reportError" class="report-state report-state-error" role="alert">
        <span>{{ reportError }}</span><el-button @click="retryReport">重新加载</el-button>
      </div>
      <p v-else-if="reportLoading" class="report-state" role="status">正在读取当前画像的报告，请稍候。</p>

      <div class="summary-metrics report-summary-metrics" aria-label="学习数据摘要" v-module-motion="{ key: selectedLearnerId + ':' + windowDays, ready: !reportLoading }">
        <article class="summary-metric mint"><span>学习资源</span><strong>{{ metricSummary.resource_count || 0 }}</strong><small>已生成资源批次</small></article>
        <article class="summary-metric blue"><span>练习反馈</span><strong>{{ metricSummary.feedback_count || 0 }}</strong><small>已记录练习结果</small></article>
        <article class="summary-metric amber"><span>客观正确率</span><strong>{{ averageCorrectRate }}</strong><small>{{ streamStatusLabel }}</small></article>
        <article class="summary-metric slate"><span>待巩固知识点</span><strong>{{ metricSummary.weak_point_count || 0 }}</strong><small>优先进入下一轮学习</small></article>
      </div>
    </section>

    <section class="report-chart-section report-mastery-section" aria-label="学习节点掌握概览">
      <LearningNodeMasteryChart :key="`mastery-${report.report_revision || 'initial'}`" :data="report.learning_node_mastery_map" />
    </section>

    <section class="report-visual-grid" aria-label="学情与资源匹配可视化">
      <div class="report-chart-slot report-radar-slot"><ReportChart :data="report" /></div>
      <div class="report-chart-slot report-fit-slot"><ResourceDifficultyCurve :data="report.resource_difficulty_curve" /></div>
      <div class="report-chart-slot report-path-slot"><LearningPathGraph :data="report.learning_path_graph" /></div>
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
const reportLoading = ref(false)
const reportError = ref('')
let reportRequestVersion = 0
let reportMounted = true
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
  if (!reportMounted) return
  profiles.value = profileRes.data.items || profileRes.data.profiles || []
  tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
  if (!profiles.value.length) { selectedLearnerId.value = ''; return }
  if (!profiles.value.some((item) => item.learner_id === selectedLearnerId.value)) selectedLearnerId.value = profiles.value[0].learner_id
}
function replaceReport(data) {
  Object.keys(report).forEach((key) => delete report[key])
  Object.assign(report, data)
}
function matchesReportContext(data, learnerId, days) {
  return data?.learner_id === learnerId && data?.window?.window_days === days
}
const stream = new ReportStreamClient({
  onStatus: (status) => { streamStatus.value = status },
  onReport: (data) => {
    if (!reportMounted || !matchesReportContext(data, selectedLearnerId.value, windowDays.value)) return
    replaceReport(data)
    reportError.value = ''
  },
  fetchReport: async ({ learnerId, windowDays: days, etag }) => {
    const res = await learningReportApi.get(learnerId, days, etag)
    if (res.status === 304) return null
    return { data: res.data, revision: res.data.report_revision }
  },
})

async function loadReport(force = false) {
  if (!selectedLearnerId.value || !reportMounted) return
  const learnerId = selectedLearnerId.value
  const days = windowDays.value
  const version = ++reportRequestVersion
  const isCurrent = () => reportMounted && version === reportRequestVersion && selectedLearnerId.value === learnerId && windowDays.value === days
  stream.stop()
  if (!matchesReportContext(report, learnerId, days)) replaceReport({})
  reportLoading.value = true
  reportError.value = ''
  try {
    const res = await learningReportApi.get(learnerId, days, force ? null : report.report_revision)
    if (!isCurrent()) return
    if (res.status !== 304) {
      if (!matchesReportContext(res.data, learnerId, days)) throw new Error('报告与当前画像或时间范围不一致，请重新加载')
      replaceReport(res.data)
    }
    localStorage.setItem('last_learner_id', learnerId)
    stream.start({ learnerId, windowDays: days, revision: report.report_revision })
  } catch (error) {
    if (!isCurrent()) return
    reportError.value = error?.response?.data?.message || error?.message || '报告查询失败'
    ElMessage.error(reportError.value)
  } finally {
    if (isCurrent()) reportLoading.value = false
  }
}
async function handleProfileChange() {
  replaceReport({})
  await loadReport(true)
}
async function retryReport() {
  try {
    if (!profiles.value.length) await loadProfiles()
    await loadReport(true)
  } catch (error) {
    if (reportMounted) reportError.value = error?.response?.data?.message || '报告画像加载失败，请重试'
  }
}
function restartStream() { if (selectedLearnerId.value) loadReport() }
function handleOffline() { stream.stop(); streamStatus.value = 'offline' }
function handleVisibility() {
  if (document.visibilityState === 'visible') restartStream()
  else if (streamStatus.value === 'polling') stream.stop()
}
onMounted(async () => {
  window.addEventListener('online', restartStream); window.addEventListener('offline', handleOffline)
  document.addEventListener('visibilitychange', handleVisibility)
  try {
    await loadProfiles(); if (selectedLearnerId.value) await loadReport()
  } catch (error) {
    if (reportMounted) reportError.value = error?.response?.data?.message || '报告画像加载失败，请重试'
  }
})
onBeforeUnmount(() => {
  reportMounted = false
  ++reportRequestVersion
  stream.stop(); window.removeEventListener('online', restartStream); window.removeEventListener('offline', handleOffline)
  document.removeEventListener('visibilitychange', handleVisibility)
})
</script>

<style scoped>
.report-state { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 14px 0 0; padding: 12px 16px; border-left: 2px solid #086575; background: #f0f7f7; color: #536b7d; font-size: 13px; line-height: 1.7; }
.report-state-error { border-left-color: #a33b40; background: #fdf8f7; color: #a33b40; }
.report-state :deep(.el-button) { flex-shrink: 0; }
.report-page {
  --report-ink: #132c40;
  --report-muted: #536b7d;
  --report-line: #d9e4eb;
  --report-teal: #086575;
  --rag-ink: #132c40;
  --rag-line: #d9e4eb;
  --rag-radius: 5px;
  --rag-shadow-soft: none;
  --rag-surface: #fff;
  --rag-surface-alt: #fff;
  --rag-blue-700: #11283c;
  --rag-blue-800: #1d4055;
  --el-color-primary: #086575;
  --el-color-primary-light-9: #edf8f6;
  --el-border-radius-base: 5px;
  --el-border-color: #cbdbe4;
  --el-text-color-regular: #132c40;
  display: flex;
  width: 100%;
  min-width: 0;
  max-width: 1800px;
  flex-direction: column;
  gap: 24px !important;
  margin: 0 auto;
  color: var(--report-ink);
}
.report-page .report-hero {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 16px;
  padding: 20px;
  border: 1px solid var(--report-line) !important;
  border-top: 2px solid #132c40 !important;
  border-radius: 0 !important;
  background: #fff !important;
  box-shadow: none !important;
}
.report-overview-head { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, .8fr); align-items: center; gap: 24px; }
.report-hero-copy { min-width: 0; }
.report-page .report-kicker { display: block; color: var(--report-muted) !important; font: 10px/1.5 Consolas, "SFMono-Regular", monospace; letter-spacing: .025em; }
.report-hero h2 { margin: 7px 0 0; color: var(--report-ink); font-size: 26px; font-weight: 650; line-height: 1.3; }
.report-focus { display: grid; min-width: 0; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 7px 12px; padding-left: 20px; border-left: 1px solid var(--report-line); }
.report-focus > span { display: flex; grid-column: 1 / -1; align-items: center; flex-wrap: wrap; gap: 8px; color: var(--report-muted); font-size: 12px; line-height: 1.6; }
.report-focus > span small { margin-left: auto; color: var(--report-muted); font: 10px/1.5 Consolas, monospace; }
.report-focus i { flex: 0 0 auto; width: 7px; height: 7px; margin-right: 4px; border-radius: 50%; background: #438ff0; box-shadow: 0 0 0 5px rgba(67, 143, 240, .12); }
.report-focus strong { color: var(--report-ink); font-size: 16px; font-weight: 600; line-height: 1.65; overflow-wrap: anywhere; }
.report-focus b { color: var(--report-muted); font-size: 12px; font-weight: 500; line-height: 1.65; overflow-wrap: anywhere; }
.report-hero > .el-alert { min-width: 0; min-height: 38px; padding: 9px 12px; border: 0; border-left: 3px solid #6a9b79; border-radius: 0; background: #f0f7f1; }
.report-hero > .el-alert :deep(.el-alert__title) { color: #39644a; font-size: 12px; font-weight: 500; line-height: 1.75; overflow-wrap: anywhere; }
.report-hero > .el-alert--warning { border-left-color: #ba8a35; background: #fff8eb; }
.report-hero > .el-alert--warning :deep(.el-alert__title) { color: #7c5a21; }
.report-page .report-selector-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 160px auto;
  align-items: end;
  gap: 16px !important;
  padding: 16px 0 0;
  border: 0;
  border-top: 1px solid var(--report-line);
  border-radius: 0;
  background: transparent !important;
}
.report-field { min-width: 0; }
.report-field label { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 7px; color: var(--report-muted); font-size: 12px; line-height: 1.5; }
.report-field label span { font: 10px/1.5 Consolas, monospace; }
.report-input, .window-select { width: 100%; min-width: 0; }
.report-selector-row :deep(.el-select__wrapper) { min-height: 44px; padding: 8px 12px; border-radius: 5px !important; background: #f8fafc; box-shadow: 0 0 0 1px #cbdbe4 inset; font-size: 12px; }
.report-selector-row :deep(.el-select__placeholder), .report-selector-row :deep(.el-select__placeholder.is-transparent) { color: var(--report-ink); }
.report-selector-row :deep(.el-select__wrapper.is-focused) { box-shadow: 0 0 0 2px #167587 inset; }
.report-selector-row :deep(.el-select__caret) { color: var(--report-muted); }
.report-page .report-refresh-button { min-width: 116px; min-height: 44px; height: auto; margin: 0; padding: 10px 16px; border: 1px solid #11283c !important; border-radius: 5px !important; background: #11283c !important; color: #fff !important; font-size: 12px; font-weight: 600; box-shadow: none; }
.report-page .report-refresh-button:hover { border-color: #1d4055 !important; background: #1d4055 !important; }
.report-page .report-refresh-button :deep(.el-icon) { width: 14px; height: 14px; font-size: 14px; color: #fff; }
.report-page .report-refresh-button.is-disabled, .report-page .report-refresh-button.is-disabled:hover { border-color: #d2dee5 !important; background: #e8eef2 !important; color: #536b7d !important; box-shadow: none; }
.report-page .report-refresh-button.is-disabled :deep(.el-icon) { color: #8ca1ae; }
.report-page .report-refresh-button:focus-visible { outline: 2px solid #167587; outline-offset: 3px; }
.report-summary-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); padding-top: 17px; border-top: 1px solid var(--report-line); }
.report-page .summary-metric { position: relative; display: flex; min-width: 0; flex-direction: column; align-items: flex-start; gap: 7px; padding: 0 22px; border: 0; border-right: 1px solid var(--report-line); border-radius: 0; background: transparent !important; box-shadow: none; }
.report-page .summary-metric:first-child { padding-left: 14px; }
.report-page .summary-metric:last-child { border-right: 0; }
.summary-metric::before { position: absolute; top: 2px; left: 9px; width: 3px; height: 12px; background: #4d91df; content: ""; }
.summary-metric:first-child::before { left: 0; }
.summary-metric.mint::before { background: #39b58d; }
.summary-metric.blue::before { background: #4d91df; }
.summary-metric.amber::before { background: #e2a13f; }
.summary-metric.slate::before { background: #8295aa; }
.summary-metric > span { color: var(--report-muted); font-size: 12px; line-height: 1.5; }
.summary-metric strong { color: var(--report-ink); font-size: 27px; font-weight: 600; line-height: 1.15; font-variant-numeric: tabular-nums; }
.summary-metric small { color: var(--report-muted); font-size: 11px; line-height: 1.65; overflow-wrap: anywhere; }

/* Only the surrounding panels are restyled; the four chart canvases and options remain intact. */
.report-page .report-chart-section, .report-chart-slot {
  min-width: 0;
  border: 1px solid var(--report-line) !important;
  border-top: 2px solid #132c40 !important;
  border-radius: 0 !important;
  background: #fff;
  box-shadow: none !important;
}
.report-page .report-visual-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; border: 0 !important; border-radius: 0 !important; background: transparent; box-shadow: none !important; }
.report-path-slot { grid-column: 1 / -1; }
.report-chart-section :deep(.visual-card), .report-chart-slot :deep(.visual-card), .report-chart-slot :deep(.analysis-panel) { height: 100%; min-width: 0; padding: 20px; border: 0; border-radius: 0; background: #fff; box-shadow: none; }
.report-chart-slot :deep(.visual-card::before) { display: none; }
.report-chart-section :deep(.visual-heading), .report-chart-slot :deep(.visual-heading), .report-chart-slot :deep(.analysis-heading) { gap: 12px; padding-bottom: 15px; border-bottom: 1px solid var(--report-line); }
.report-chart-section :deep(.visual-heading span), .report-chart-slot :deep(.visual-heading span), .report-chart-slot :deep(.analysis-kicker) { color: var(--report-muted); font: 10px/1.5 Consolas, "SFMono-Regular", monospace; letter-spacing: .025em; }
.report-chart-section :deep(.visual-heading h3), .report-chart-slot :deep(.visual-heading h3), .report-chart-slot :deep(.analysis-heading h3) { margin: 7px 0 0; font-size: 20px; font-weight: 650; line-height: 1.4; }
.report-chart-section :deep(.visual-heading small), .report-chart-slot :deep(.visual-heading small), .report-chart-slot :deep(.analysis-note) { max-width: 250px; margin-top: 4px; padding: 0; border: 0; border-radius: 0; background: transparent; color: var(--report-muted); font-size: 11px; font-weight: 400; line-height: 1.65; white-space: normal; overflow: visible; overflow-wrap: anywhere; }
.report-radar-slot :deep(.analysis-heading) { margin-bottom: 16px; }
.report-radar-slot :deep(.chart-card) { min-height: 0; padding: 0; border: 0; border-radius: 0; background: transparent; }
.report-radar-slot :deep(.chart-card-head strong) { font-size: 16px; font-weight: 600; }
.report-radar-slot :deep(.chart-card-head span) { font-weight: 400; }

.report-page .next-round-panel { display: grid; grid-template-columns: minmax(240px, .65fr) minmax(0, 1.35fr); align-items: start; gap: 28px; padding: 22px; border: 1px solid var(--report-line) !important; border-top: 2px solid #132c40 !important; border-radius: 0 !important; background: #fff !important; box-shadow: none !important; }
.next-round-panel h3 { margin: 7px 0 0; color: var(--report-ink); font-size: 20px; font-weight: 650; line-height: 1.4; }
.next-round-panel p { max-width: 340px; margin: 10px 0 0; color: var(--report-muted); font-size: 12px; line-height: 1.85; }
.suggestion-list { display: grid; min-width: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.suggestion-list > span { min-width: 0; padding: 12px 14px; border-left: 2px solid #167c7c; background: #edf8f6; color: var(--report-teal); font-size: 13px; font-weight: 500; line-height: 1.75; overflow-wrap: anywhere; }
.suggestion-list em { grid-column: 1 / -1; color: var(--report-muted); font-size: 12px; font-style: normal; line-height: 1.85; }

/* Matches the neighboring pages without changing the shared application shell. */
:global(.app-shell:has(.report-page)) { background: #f5f7fa; }
:global(.app-shell:has(.report-page) .topbar) { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; gap: 16px; min-height: 60px; padding: 8px 28px; background: #fff; border-bottom: 1px solid #d9e4eb; box-shadow: none; }
:global(.app-shell:has(.report-page) .topbar-copy) { display: flex; flex-direction: row-reverse; justify-content: flex-end; align-items: center; gap: 14px; min-width: 0; }
:global(.app-shell:has(.report-page) .topbar-copy h1) { margin: 0; font-size: 18px; font-weight: 650; line-height: 1.5; color: #132c40; white-space: nowrap; }
:global(.app-shell:has(.report-page) .topbar-kicker) { margin: 0; padding-left: 14px; border-left: 1px solid #d9e4eb; color: #536b7d; font: 10px/1.5 Consolas, monospace; letter-spacing: 0; }
:global(.app-shell:has(.report-page) .topbar-copy p) { display: none; }
:global(.app-shell:has(.report-page) .topbar-actions) { position: static; display: flex; width: auto; flex-wrap: nowrap; justify-content: flex-end; align-items: center; gap: 8px; margin: 0; transform: none; }
:global(.app-shell:has(.report-page) .topbar-action) { min-height: 44px; margin: 0 !important; padding: 10px 9px; border: 0 !important; border-radius: 5px !important; background: transparent !important; color: #536b7d !important; font-size: 12px; font-weight: 400; box-shadow: none !important; }
:global(.app-shell:has(.report-page) .topbar-action .el-icon) { width: 14px; height: 14px; font-size: 14px; color: #17447e; }
:global(.app-shell:has(.report-page) .topbar-action:hover) { background: #edf8f6 !important; color: #086575 !important; }
:global(.app-shell:has(.report-page) .topbar-action:focus-visible) { outline: 2px solid #167587; outline-offset: 2px; }
:global(.app-shell:has(.report-page) .topbar-meta) { display: flex; align-items: center; min-width: 0; width: auto; gap: 0; padding-left: 14px; border-left: 1px solid #d9e4eb; }
:global(.app-shell:has(.report-page) .topbar-meta > div) { min-width: 58px; padding: 0 6px; border: 0 !important; border-radius: 0 !important; background: transparent !important; box-shadow: none !important; }
:global(.app-shell:has(.report-page) .topbar-meta > div:last-child) { display: none; }
:global(.app-shell:has(.report-page) .topbar-meta span) { font-size: 10px; line-height: 1.5; color: #536b7d; }
:global(.app-shell:has(.report-page) .topbar-meta strong) { max-width: 160px; margin-top: 3px; color: #132c40; white-space: normal; overflow-wrap: anywhere; font-size: 12px; line-height: 1.5; }
:global(.app-shell:has(.report-page) .content-area) { padding: 22px 28px 28px; background: #f5f7fa; overflow-y: auto; }
:global(.report-control-dropdown .el-select-dropdown__item) { min-height: 36px; line-height: 36px; font-size: 12px; color: #132c40; }
:global(.report-control-dropdown .el-select-dropdown__item.is-selected) { background: #edf8f6; color: #086575; font-weight: 600; }

@media (max-width: 1300px) {
  :global(.app-shell:has(.report-page) .topbar-kicker) { display: none; }
  .report-overview-head { grid-template-columns: minmax(0, 1fr) minmax(280px, 1.1fr); }
  .report-page, .report-page .report-visual-grid { gap: 20px !important; }
}
@media (max-width: 1080px) {
  .report-page .report-visual-grid { grid-template-columns: minmax(0, 1fr); }
  .report-path-slot { grid-column: auto; }
  :global(.app-shell:has(.report-page) .topbar) { gap: 10px; }
}
@media (max-width: 760px) {
  :global(.app-shell:has(.report-page) .topbar) { padding: 8px 18px; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 12px; }
  :global(.app-shell:has(.report-page) .topbar-actions) { grid-row: 2; grid-column: 1 / -1; justify-content: flex-start; }
  :global(.app-shell:has(.report-page) .topbar-action) { padding: 10px 8px; }
  :global(.app-shell:has(.report-page) .topbar-meta) { grid-row: 1; grid-column: 2; }
  :global(.app-shell:has(.report-page) .content-area) { padding: 18px 18px 24px; }
  .report-overview-head { grid-template-columns: minmax(0, 1fr); gap: 16px; }
  .report-focus { padding: 14px 0 0; border-left: 0; border-top: 1px solid var(--report-line); }
  .report-page .report-selector-row { grid-template-columns: minmax(0, 1fr) auto; gap: 14px !important; }
  .report-profile-field { grid-column: 1 / -1; }
  .report-summary-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 0; }
  .report-page .summary-metric { padding-left: 16px; padding-right: 12px; }
  .report-page .summary-metric:nth-child(odd) { padding-left: 14px; }
  .summary-metric:nth-child(odd)::before { left: 0; }
  .report-page .summary-metric:nth-child(2) { border-right: 0; }
  .summary-metric:nth-child(even)::before { left: 3px; }
  .report-page .next-round-panel { grid-template-columns: minmax(0, 1fr); gap: 18px; }
}
@media (max-width: 560px) {
  .report-page .report-hero { padding: 16px; }
  .report-hero h2 { font-size: 23px; }
  .report-focus { grid-template-columns: minmax(0, 1fr); }
  .report-focus b { font-size: 12px; }
  .report-page .report-refresh-button { min-width: 112px; padding: 10px 14px; }
  .report-chart-section :deep(.visual-card), .report-chart-slot :deep(.visual-card), .report-chart-slot :deep(.analysis-panel) { padding: 16px; }
  .report-chart-section :deep(.visual-heading), .report-chart-slot :deep(.visual-heading), .report-chart-slot :deep(.analysis-heading) { flex-direction: column; gap: 5px; }
  .report-chart-section :deep(.visual-heading h3), .report-chart-slot :deep(.visual-heading h3), .report-chart-slot :deep(.analysis-heading h3) { font-size: 18px; }
  .report-page .next-round-panel { padding: 18px 16px; }
  .suggestion-list { grid-template-columns: minmax(0, 1fr); }
}
@media (prefers-reduced-motion: reduce) {
  .report-page .report-refresh-button, .report-page :deep(.el-select__wrapper) { transition: none; }
  :global(.app-shell:has(.report-page) .topbar-action) { transition: none; }
}
</style>
