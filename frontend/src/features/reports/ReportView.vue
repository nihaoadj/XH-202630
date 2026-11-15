<template>
  <div class="report-page">
    <div class="report-overview report-snap-section">
      <section class="report-hero workspace-filter-surface" aria-label="学习报告概览与筛选">
        <div class="task-selector">
          <div class="selector-field report-profile-field">
            <label>学习画像 <span>PROFILE</span></label>
            <el-select v-model="selectedLearnerId" placeholder="选择学习画像" class="task-select" aria-label="学习画像" popper-class="report-control-dropdown" filterable @change="handleProfileChange">
              <el-option v-for="item in profileOptions" :key="item.learner_id" :label="item.label" :value="item.learner_id" />
            </el-select>
          </div>
          <div class="selector-field report-window-field">
            <label>时间范围 <span>PERIOD</span></label>
            <el-select v-model="windowDays" class="task-select" aria-label="报告时间窗口" popper-class="report-control-dropdown" @change="restartStream">
              <el-option :value="7" label="近 7 天" />
              <el-option :value="30" label="近 30 天" />
              <el-option :value="90" label="近 90 天" />
            </el-select>
          </div>
          <el-button class="report-refresh-button" :icon="Refresh" :loading="reportLoading" @click="() => loadReport(true)" :disabled="!selectedLearnerId">更新报告</el-button>
        </div>

        <el-alert
          v-if="report.report_availability?.status === 'calibration_pending'"
          type="warning"
          :closable="false"
          :title="report.report_availability.message || '初始诊断尚未完成，暂不生成正式学习结论'"
        />

        <div v-if="reportError" class="report-state report-state-error" role="alert">
          <span>{{ reportError }}</span><el-button @click="retryReport">重新加载</el-button>
        </div>
        <p v-else-if="reportLoading" class="report-state" role="status">正在读取当前画像的报告，请稍候。</p>

        <div class="job-summary report-summary-metrics" aria-label="学习数据摘要" v-module-motion="{ key: selectedLearnerId + ':' + windowDays, ready: !reportLoading }">
          <div class="summary-item"><span>学习资源</span><strong class="summary-count">{{ metricSummary.resource_count || 0 }}</strong><small>已生成资源批次</small></div>
          <div class="summary-item"><span>练习反馈</span><strong class="summary-count">{{ metricSummary.feedback_count || 0 }}</strong><small>已记录练习结果</small></div>
          <div class="summary-item"><span>客观正确率</span><strong class="summary-count">{{ averageCorrectRate }}</strong><small>{{ streamStatusLabel }}</small></div>
          <div class="summary-item"><span>待巩固知识点</span><strong class="summary-count">{{ metricSummary.weak_point_count || 0 }}</strong><small>优先进入下一轮学习</small></div>
        </div>
      </section>


      <section class="report-chart-section report-mastery-section" aria-label="学习节点掌握概览">
        <LearningNodeMasteryChart :key="`mastery-${report.report_revision || 'initial'}`" :data="report.learning_node_mastery_map" />
      </section>

    </div>

    <section class="report-visual-grid" aria-label="学情与资源匹配可视化">
      <div class="report-chart-slot report-radar-slot report-snap-section"><ReportChart :data="report" /></div>
      <div class="report-chart-slot report-fit-slot"><ResourceDifficultyCurve :data="report.resource_difficulty_curve" /></div>
      <div class="report-chart-slot report-path-slot report-snap-section"><LearningPathGraph :data="report.learning_path_graph" /></div>
    </section>

    <div class="report-ending report-snap-section">
      <section v-if="qualitySummary || recentQualityItems.length" class="report-quality-section" aria-label="生成资源质量摘要">
        <header class="report-quality-head">
          <div>
            <span class="report-kicker">RESOURCE QUALITY</span>
            <h3>生成资源质量摘要</h3>
          </div>
          <div v-if="qualityBatches.length" class="report-quality-filter">
            <label for="report-quality-batch">资源批次 <span>BATCH</span></label>
            <el-select id="report-quality-batch" v-model="qualityBatchKey" aria-label="资源批次"
              popper-class="report-control-dropdown" filterable>
              <el-option label="全部批次" :value="allQualityBatches" />
              <el-option v-for="batch in qualityBatches" :key="batch.key"
                :label="qualityBatchLabel(batch)" :value="batch.key" />
            </el-select>
          </div>
        </header>
        <p v-if="!activeQualityBatch && recentQualityItems.length" class="report-quality-scope">
          汇总最近 {{ recentQualityItems.length }} 份已发布资源，最多 10 份。可选择单个批次查看完整明细。
        </p>
        <div v-if="qualitySummary" class="report-quality-grid">
          <article class="report-quality-metric">
            <span>知识覆盖</span>
            <strong :class="`is-${qualityTone(qualitySummary.coverage)}`">{{ qualityValueText(qualitySummary.coverage) }}</strong>
            <small>{{ qualityMetricText(qualitySummary.coverage) }}</small>
          </article>
          <article class="report-quality-metric">
            <span>普通审核参考幻觉率</span>
            <strong :class="qualitySummary.resource_total > 0 ? 'is-attention' : 'is-muted'">{{ qualitySummary.resource_total > 0 ? '<5%' : '—' }}</strong>
            <small v-if="qualitySummary.resource_total > 0">平台参考线，实测值见 Claim 核验统计。</small>
            <small v-else>当前范围没有已发布资源。</small>
          </article>
          <article class="report-quality-metric">
            <span>幻觉率（已核验事实子集）</span>
            <strong :class="`is-${qualityTone(qualitySummary.claim_unverified_subset_rate || null)}`">{{ claimAggregateText }}</strong>
            <small>
              <span class="claim-calculation-formula">（矛盾数＋未获支持数）÷ 已核验事实数 × 100%</span>
              <span class="claim-calculation-detail">{{ claimAggregateNote }}</span>
            </small>
          </article>
        </div>
        <ul v-if="recentQualityItems.length" class="report-quality-list">
          <li v-for="item in recentQualityItems" :key="`${item.resource_id}-${item.resource_version}`">
            <strong>{{ qualityResourceLabel(item) }}</strong>
            <span>覆盖 {{ qualityValueText(item.coverage) }}（{{ sourceLabel(item.coverage) }} · {{ statusLabel(item.coverage) }}）</span>
            <span v-if="isReferenceMetric(item.hallucination)">普通审核参考线 {{ formatReferenceLimit(item.hallucination.value) }}</span>
            <span v-else>幻觉 {{ hallucinationMetricText(item.hallucination) }}</span>
          </li>
        </ul>
      </section>


      <section class="next-round-panel">
        <div><span class="report-kicker">NEXT LEARNING CYCLE</span><h3>下一轮学习重点</h3><p>建议优先围绕以下知识点进行练习与资源生成，持续缩小当前学习盲区。</p></div>
        <div class="suggestion-list"><span v-for="item in nextSuggestions" :key="item">{{ item }}</span><em v-if="!nextSuggestions.length">完成一次能力诊断后，将在这里展示个性化学习重点。</em></div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { currentProfileRating } from '../../utils/profileRating.js'
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'
import { knowledgeApi } from '../knowledge/api.js'
import { profileApi } from '../learners/api.js'
import { useAppStore } from '../../stores/app'
import ReportChart from './ReportChart.vue'
import LearningNodeMasteryChart from './LearningNodeMasteryChart.vue'
import ResourceDifficultyCurve from './ResourceDifficultyCurve.vue'
import LearningPathGraph from './LearningPathGraph.vue'
import { learningReportApi, fetchReportSnapshot } from './api'
import { ReportStreamClient } from './reportStreamClient'
import {
  hallucinationMetricText, isReferenceMetric, qualityMetricText, qualityTone, qualityValueText,
  sourceLabel, statusLabel,
} from '../../utils/qualityMetricsPresentation.js'

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
const allQualityBatches = 'all'
const qualityBatchKey = ref(allQualityBatches)
const qualityBatches = computed(() => report.resource_quality_batches || [])
const activeQualityBatch = computed(() => qualityBatches.value.find(batch => batch.key === qualityBatchKey.value))
const qualitySummary = computed(() => activeQualityBatch.value?.summary || report.resource_quality_summary || null)
const recentQualityItems = computed(() => activeQualityBatch.value?.items || (report.recent_resource_quality || []).slice(0, 10))
const qualityResourceKey = item => JSON.stringify([item.resource_id, item.resource_version])
const qualityTopicByResource = computed(() => new Map(qualityBatches.value.flatMap(batch =>
  (batch.items || []).map(item => [qualityResourceKey(item), batch.topic]),
)))
function qualityResourceLabel(item) {
  const resourceName = item.resource_type || '资源'
  if (activeQualityBatch.value) return resourceName
  const nodeName = item.learning_node_name || qualityTopicByResource.value.get(qualityResourceKey(item)) || item.topic || item.learning_node_id
  if (!nodeName) return resourceName
  return `${nodeName}—${resourceName}`
}
watch(selectedLearnerId, () => { qualityBatchKey.value = allQualityBatches }, { flush: 'sync' })
watch(qualityBatches, batches => {
  if (batches.length && !batches.some(batch => batch.key === qualityBatchKey.value)) {
    qualityBatchKey.value = allQualityBatches
  }
})
const batchDate = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'short', timeStyle: 'short' })
function qualityBatchLabel(batch) {
  const date = batch.created_at ? batchDate.format(new Date(batch.created_at)) : ''
  return [batch.topic, date, `${batch.summary.resource_total} 份资源`].filter(Boolean).join(' · ')
}
const claimAggregateText = computed(() => {
  const rate = qualitySummary.value?.claim_unverified_subset_rate
  return rate ? qualityValueText(rate) : '—'
})
const claimAggregateNote = computed(() => {
  const summary = qualitySummary.value
  if (!summary || !summary.claim_unverified_subset_rate) {
    return '当前范围暂无可用的完整 Claim 核验结果。'
  }
  const risk = summary.claim_risk_fact_total ?? 0
  const factual = summary.claim_factual_total ?? 0
  return `当前范围共核验 ${factual} 条事实，其中 ${risk} 条与证据矛盾或未获支持。`
})
const nextSuggestions = computed(() => report.next_suggestions || report.weak_points || [])
const activeProfile = computed(() => profiles.value.find((item) => item.learner_id === selectedLearnerId.value) || null)
const averageCorrectRate = computed(() => formatPercent(report.learning_activity?.verified_accuracy ?? metricSummary.value.average_correct_rate))
const streamStatusLabel = computed(() => ({ connecting: '正在连接自动更新', live: '自动更新已开启', reconnecting: '正在重连自动更新', polling: '已降级为定时刷新', offline: '当前离线', closed: '自动更新已停止' })[streamStatus.value] || '自动更新')
const profileOptions = computed(() => profiles.value.map((profile) => ({ ...profile, label: `${profileDisplayName(profile)} / ${resolveTrackName(profile.knowledge_base_id)} / ${currentProfileRating(profile) || '未分级'}` })))

function resolveTrackName(trackId) {
  return tracks.value.find((item) => item.track_id === trackId || item.knowledge_base_id === trackId)?.name || trackId || '未选择学习方向'
}
function profileDisplayName(profile) {
  const snapshot = profile?.learning_preferences?.metadata?.user_profile_snapshot
  return snapshot?.display_name || snapshot?.name || profile?.learner_type || '未命名画像'
}
function formatPercent(value, fallback = '--') { return typeof value === 'number' ? `${Math.round(value * 100)}%` : fallback }
function formatReferenceLimit(value) {
  return typeof value === 'number' ? `<${formatPercent(value)}` : '—'
}

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
  fetchReport: fetchReportSnapshot,
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
  gap: 0;
  padding: 0;
  overflow: hidden;
  border: 0 !important;
  border-radius: 18px !important;
  box-shadow: inset 0 -1px 1px rgb(111 142 167 / 15%),0 3px 5px -4px rgb(33 64 86 / 24%),0 12px 24px -17px rgb(33 64 86 / 30%) !important;
}
.report-page .report-kicker { display: block; color: var(--report-muted) !important; font: 10px/1.5 Consolas, "SFMono-Regular", monospace; letter-spacing: .025em; }
.report-hero h2 { margin: 7px 0 0; color: var(--report-ink); font-size: 26px; font-weight: 650; line-height: 1.3; }
.report-hero > .el-alert { min-width: 0; min-height: 38px; margin: 0 20px 10px; padding: 9px 12px; border: 0; border-left: 3px solid #6a9b79; border-radius: 0; background: #f0f7f1; }
.report-hero > .el-alert :deep(.el-alert__title) { color: #39644a; font-size: 12px; font-weight: 500; line-height: 1.75; overflow-wrap: anywhere; }
.report-hero > .el-alert--warning { border-left-color: #ba8a35; background: #fff8eb; }
.report-hero > .el-alert--warning :deep(.el-alert__title) { color: #7c5a21; }
/* 复用生成页 control-panel 的任务选择与摘要样式（高级感 / 玻璃质感）。 */
.report-hero .task-selector { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)) auto; gap: 20px; align-items: end; padding: 14px 20px 12px; }
.report-hero .selector-field { min-width: 0; }
.report-hero .selector-field label { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; gap: 8px; color: #59697b; font-size: 12px; }
.report-hero .selector-field label span { font: 9px Consolas, monospace; }
.report-hero .task-select { width: 100%; min-width: 0; }
.report-page .report-refresh-button {
  justify-self: end;
  min-width: 116px;
  min-height: 44px;
  height: auto;
  margin: 0;
  padding: 10px 16px;
  border: 1px solid #a9c6d7;
  border-radius: 10px;
  background: #edf7fa linear-gradient(155deg, #ffffffed, #d8edf3b3);
  color: #165765;
  font-size: 12px;
  font-weight: 600;
  box-shadow: inset 0 1px #fff, 0 3px 8px #254a6426;
}
.report-page .report-refresh-button:not(.is-disabled, .is-loading):hover {
  border-color: #76aab9;
  background-color: #d7eef3;
  color: #104653;
}
.report-page .report-refresh-button:not(.is-disabled, .is-loading):active {
  box-shadow: inset 0 1px 3px #254a6426;
}
.report-page .report-refresh-button :deep(.el-icon) { width: 14px; height: 14px; font-size: 14px; color: inherit; }
.report-page .report-refresh-button.is-disabled { border-color: #d2dee5; background: #e8eef2; color: #536b7d; box-shadow: none; }
.report-page .report-refresh-button.is-disabled :deep(.el-icon) { color: #8ca1ae; }
.report-page .report-refresh-button:focus-visible { outline: 2px solid #167587; outline-offset: 3px; }
.report-hero > .report-state { margin: 0 20px 10px; }
.report-hero .job-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; margin: 0 20px 14px; padding-top: 12px; border-top: 1px solid #dce4eb; }
.report-hero .summary-item { min-width: 0; padding: 0 12px; border-left: 1px solid #dce4eb; }
.report-hero .summary-item:first-child { border: 0; padding-left: 0; }
.report-hero .summary-item:last-child { padding-right: 0; }
.report-hero .summary-item > span { display: block; color: #59697b; font-size: 11px; }
.report-hero .summary-item strong { display: block; margin-top: 6px; min-height: 22px; color: #172c45; font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.report-hero .summary-item .summary-count { color: #176b70; font-size: 20px; font-weight: 600; line-height: 1.1; font-variant-numeric: tabular-nums; }
.report-hero .summary-item small { display: block; margin-top: 4px; color: #59697b; font-size: 10px; line-height: 1.5; overflow-wrap: anywhere; }

/* Panel styles are independent of the four charts' drawing surfaces and options. */
.report-mastery-section, .report-radar-slot, .report-fit-slot {
  min-width: 0;
  border: 1px solid var(--report-glass-card-border);
  border-radius: 20px;
  background: linear-gradient(150deg, #fff 15%, #f0f7fb);
  box-shadow: var(--report-glass-card-shadow);
}
.report-page .report-visual-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; border: 0 !important; border-radius: 0 !important; background: transparent; box-shadow: none !important; }
.report-overview,.report-ending { display:grid; gap:24px; min-width:0; }
.report-path-slot {
  min-width: 0;
  grid-column: 1 / -1;
  border:1px solid #bed4e7 !important;
  border-radius:20px !important;
  background:linear-gradient(145deg,#fff,#f0f7fd);
  box-shadow:0 6px 18px #254d7414, inset 0 1px #fff !important;
}
.report-page .report-path-slot :deep(.visual-card) { border-radius:inherit; background:transparent; }
.report-path-slot :deep(.visual-heading) { border-bottom-color:#dbe8f4; }
.report-chart-section :deep(.visual-card), .report-chart-slot :deep(.visual-card), .report-chart-slot :deep(.analysis-panel) { height: 100%; min-width: 0; padding: 20px; border: 0; border-radius: inherit; background: transparent; box-shadow: none; }
.report-chart-slot :deep(.visual-card::before) { display: none; }
.report-chart-section :deep(.visual-heading), .report-chart-slot :deep(.visual-heading), .report-chart-slot :deep(.analysis-heading) { gap: 12px; padding-bottom: 15px; border-bottom: 1px solid var(--report-line); }
.report-chart-section :deep(.visual-heading span), .report-chart-slot :deep(.visual-heading span), .report-chart-slot :deep(.analysis-kicker) { color: var(--report-muted); font: 10px/1.5 Consolas, "SFMono-Regular", monospace; letter-spacing: .025em; }
.report-chart-section :deep(.visual-heading h3), .report-chart-slot :deep(.visual-heading h3), .report-chart-slot :deep(.analysis-heading h3) { margin: 7px 0 0; font-size: 20px; font-weight: 650; line-height: 1.4; }
.report-chart-section :deep(.visual-heading small), .report-chart-slot :deep(.visual-heading small), .report-chart-slot :deep(.analysis-note) { max-width: 250px; margin-top: 4px; padding: 0; border: 0; border-radius: 0; background: transparent; color: var(--report-muted); font-size: 11px; font-weight: 400; line-height: 1.65; white-space: normal; overflow: visible; overflow-wrap: anywhere; }
.report-radar-slot :deep(.analysis-heading) { margin-bottom: 16px; }
.report-radar-slot :deep(.chart-card) { min-height: 0; padding: 0; border: 0; border-radius: 0; background: transparent; }

.report-page .report-ending .next-round-panel {
  display: grid;
  grid-template-columns: minmax(240px, .65fr) minmax(0, 1.35fr);
  align-items: center;
  gap: 28px;
  padding: 22px;
  border: 1px solid #cbdfe8 !important;
  border-radius: 22px !important;
  background: var(--report-glass-panel) !important;
  box-shadow: var(--report-glass-panel-shadow) !important;
}
.next-round-panel h3 { margin: 7px 0 0; color: var(--report-ink); font-size: 20px; font-weight: 650; line-height: 1.4; }
.next-round-panel p { max-width: 340px; margin: 10px 0 0; color: var(--report-muted); font-size: 12px; line-height: 1.85; }
.suggestion-list { display: grid; min-width: 0; grid-template-columns: repeat(auto-fit, minmax(min(100%, 160px), 1fr)); gap: 12px; }
.suggestion-list > span {
  display: grid;
  min-width: 0;
  min-height: 54px;
  place-items: center;
  padding: 10px 14px;
  border: 1px solid var(--report-glass-card-border);
  border-radius: 14px;
  background: var(--report-glass-card);
  box-shadow: var(--report-glass-card-shadow);
  color: var(--report-ink);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.5;
  text-align: center;
  overflow-wrap: anywhere;
}
.suggestion-list em { grid-column: 1 / -1; color: var(--report-muted); font-size: 12px; font-style: normal; line-height: 1.85; }

/* Matches the neighboring pages without changing the shared application shell. */
:global(.app-shell:has(.report-page)) { background: #f5f7fa; }
:global(.app-shell:has(.report-page) .content-area) { padding: 22px 28px 28px; overflow-y: auto; }

@media (min-width: 821px) and (min-height: 680px) {
  :global(.app-shell:has(.report-page) .content-area) {
    scroll-snap-type:y mandatory;
    scroll-padding-block:22px 28px;
  }
  .report-snap-section { scroll-snap-align:start; scroll-snap-stop:always; }
  .report-ending { scroll-snap-align:end; }
}
@media (max-width: 1080px) and (min-width: 821px) and (min-height: 680px) {
  .report-fit-slot { scroll-snap-align:start; scroll-snap-stop:always; }
}
@media (max-width: 1300px) {
  .report-page, .report-page .report-visual-grid { gap: 20px !important; }
}
@media (max-width: 1080px) {
  .report-page .report-visual-grid { grid-template-columns: minmax(0, 1fr); }
  .report-path-slot { grid-column: auto; }
}
@media (max-width: 760px) {
  :global(.app-shell:has(.report-page) .content-area) { padding: 18px 18px 24px; }
  .report-hero .task-selector { grid-template-columns: 1fr; gap: 14px; padding: 16px 18px 12px; }
  .report-hero .report-refresh-button { justify-self: stretch; }
  .report-hero .job-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 0; margin-inline: 18px; }
  .report-hero .summary-item:nth-child(odd) { border: 0; padding-left: 0; }
  .report-hero .summary-item:nth-child(even) { padding-left: 14px; }
  .report-page .report-ending .next-round-panel { grid-template-columns: minmax(0, 1fr); gap: 18px; }
}
@media (max-width: 560px) {
  .report-page .report-refresh-button { min-width: 112px; padding: 10px 14px; }
  .report-chart-section :deep(.visual-card), .report-chart-slot :deep(.visual-card), .report-chart-slot :deep(.analysis-panel) { padding: 16px; }
  .report-chart-section :deep(.visual-heading), .report-chart-slot :deep(.visual-heading), .report-chart-slot :deep(.analysis-heading) { flex-direction: column; gap: 5px; }
  .report-chart-section :deep(.visual-heading h3), .report-chart-slot :deep(.visual-heading h3), .report-chart-slot :deep(.analysis-heading h3) { font-size: 18px; }
  .report-page .report-ending .next-round-panel { padding: 18px 16px; }
  .suggestion-list { grid-template-columns: minmax(0, 1fr); }
}
@media (prefers-reduced-motion: reduce) {
  .report-page .report-refresh-button { transition: none; }
}
.report-page {
  --report-glass-panel: linear-gradient(150deg, #f4f9fc 0%, #e1eff3 62%, #edf5f9 100%);
  --report-glass-panel-shadow: 0 8px 20px #254a6414, inset 0 1px #fff;
  --report-glass-card: linear-gradient(155deg, #ffffffec, #f4f9fbe0 58%, #e9f2f8c9);
  --report-glass-card-border: #a9c6d7;
  --report-glass-card-shadow: 0 2px 3px #244b641a, 0 6px 12px #2c59762b, inset 0 1px #fff;
}
.report-quality-section {
  padding:20px;
  border:1px solid #cbdfe8;
  border-radius:22px;
  background:var(--report-glass-panel);
  box-shadow:var(--report-glass-panel-shadow);
}
.report-quality-head { display:flex; flex-wrap:wrap; gap:14px 24px; align-items:center; justify-content:space-between; margin-bottom:16px; }
.report-quality-head h3 { margin:4px 0 0; font-size:18px; color:#172c45; }
.report-quality-filter { flex:0 1 410px; min-width:0; }
.report-quality-filter label { display:flex; justify-content:space-between; gap:8px; margin-bottom:6px; color:#39596d; font-size:12px; }
.report-quality-filter label span { font:10px Consolas,monospace; }
.report-quality-filter :deep(.el-select) { width:100%; }
.report-quality-filter :deep(.el-select__wrapper) { min-height:44px; }
.report-quality-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.report-quality-metric {
  display:flex;
  min-width:0;
  flex-direction:column;
  gap:8px;
  padding:15px;
  border:1px solid var(--report-glass-card-border);
  border-radius:14px;
  background:var(--report-glass-card);
  box-shadow:var(--report-glass-card-shadow);
}
.report-quality-metric span { color:#415a70; font-size:12px; }
.report-quality-metric strong { color:#172c45; font-size:24px; font-weight:600; font-variant-numeric:tabular-nums; }
.report-quality-metric strong.is-success { color:#176b70; }
.report-quality-metric strong.is-attention { color:#935719; }
.report-quality-metric strong.is-muted { color:#59697b; }
.report-quality-metric small { color:#4f6476; font-size:12px; line-height:1.6; overflow-wrap:anywhere; }
.report-quality-metric .claim-calculation-formula,
.report-quality-metric .claim-calculation-detail { color:inherit; }
.report-quality-metric .claim-calculation-detail { display:block; margin-top:3px; }
.report-quality-list { display:grid; gap:6px; margin:14px 0 0; padding:0; list-style:none; }
.report-quality-list li { display:flex; flex-wrap:wrap; align-items:baseline; gap:4px 12px; padding:8px 10px; border-radius:8px; background:#ffffffb8; color:#4f6476; font-size:12px; }
.report-quality-list li strong { color:#172c45; overflow-wrap:anywhere; }
.report-quality-scope { margin:0 0 12px; color:#4f6476; font-size:12px; line-height:1.6; }
@media(max-width:740px) {
  .report-quality-section { padding:16px; }
  .report-quality-filter { flex-basis:100%; }
  .report-quality-grid { grid-template-columns:1fr; }
}
</style>
