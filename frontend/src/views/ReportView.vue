<template>
  <div class="report-page">
    <section class="report-hero">
      <div class="report-hero-copy">
        <span class="report-kicker">LEARNING REPORT</span>
        <h2>我的学习进展</h2>
        <p>围绕学习画像汇总能力掌握、资源学习与练习反馈，为下一轮学习提供清晰依据。</p>
      </div>
      <div class="profile-selector">
        <span>当前学习画像</span>
        <el-select v-model="selectedLearnerId" placeholder="选择学习画像" class="report-input" filterable @change="handleProfileChange">
          <el-option v-for="item in profileOptions" :key="item.learner_id" :label="item.label" :value="item.learner_id" />
        </el-select>
        <el-button type="primary" @click="loadReport" :disabled="!selectedLearnerId">更新报告</el-button>
      </div>
    </section>

    <section class="report-snapshot">
      <article class="learning-focus">
        <span class="focus-state"><i />正在学习</span>
        <strong>{{ directionName }}</strong>
        <span class="focus-goal">{{ report.learning_goal || activeProfile?.learning_goal || '继续完善你的学习目标' }}</span>
        <div class="focus-meta">
          <span>能力层级 <b>{{ report.skill_level || activeProfile?.skill_level || '待诊断' }}</b></span>
          <span>画像版本 <b>V{{ report.profile_version || activeProfile?.profile_version || 1 }}</b></span>
        </div>
      </article>
      <div class="summary-metrics">
        <article class="summary-metric mint"><span>学习资源</span><strong>{{ metricSummary.resource_count || 0 }}</strong><small>已生成资源批次</small></article>
        <article class="summary-metric blue"><span>练习反馈</span><strong>{{ metricSummary.feedback_count || 0 }}</strong><small>已记录练习结果</small></article>
        <article class="summary-metric amber"><span>平均正确率</span><strong>{{ averageCorrectRate }}</strong><small>基于已提交反馈</small></article>
        <article class="summary-metric slate"><span>待巩固知识点</span><strong>{{ metricSummary.weak_point_count || 0 }}</strong><small>优先进入下一轮学习</small></article>
      </div>
    </section>

    <ReportChart :data="report" />

    <section class="report-detail-grid">
      <article class="report-section">
        <div class="section-heading">
          <div><span class="report-kicker">LEARNING MATERIALS</span><h3>最近学习资源</h3></div>
          <span class="section-count">{{ recentResources.length }} 份</span>
        </div>
        <el-empty v-if="!recentResources.length" description="本学习画像还没有资源记录" :image-size="62" />
        <div v-else class="resource-list">
          <article v-for="item in recentResources" :key="item.resource_id" class="resource-item">
            <span class="resource-type">{{ item.resource_type }}</span>
            <div><strong>{{ formatResourceLabel(item, directionName) }}</strong><p>{{ (item.knowledge_points || []).slice(0, 4).join('、') || '等待补充知识点信息' }}</p></div>
            <span class="difficulty-tag">{{ item.difficulty || '适配当前阶段' }}</span>
          </article>
        </div>
      </article>

      <article class="report-section">
        <div class="section-heading">
          <div><span class="report-kicker">PRACTICE FEEDBACK</span><h3>练习反馈记录</h3></div>
          <span class="section-count">{{ recentFeedback.length }} 次</span>
        </div>
        <el-empty v-if="!recentFeedback.length" description="完成练习后，这里会沉淀你的反馈" :image-size="62" />
        <div v-else class="feedback-list">
          <article v-for="item in recentFeedback" :key="item.feedback_id || item.resource_id" class="feedback-item">
            <div><strong>{{ feedbackResourceLabel(item) }}</strong><span>{{ feedbackDecisionLabel(item) }}</span></div>
            <b>{{ formatPercent(item.correct_rate) }}</b>
          </article>
        </div>
      </article>
    </section>

    <section class="next-round-panel">
      <div><span class="report-kicker">NEXT LEARNING CYCLE</span><h3>下一轮学习重点</h3><p>建议优先围绕以下知识点进行练习与资源生成，持续缩小当前学习盲区。</p></div>
      <div class="suggestion-list"><span v-for="item in nextSuggestions" :key="item">{{ item }}</span><em v-if="!nextSuggestions.length">完成一次能力诊断后，将在这里展示个性化学习重点。</em></div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { knowledgeApi, profileApi, reportApi } from '../api'
import { useAppStore } from '../stores/app'
import ReportChart from '../components/ReportChart.vue'
import { formatResourceLabel } from '../utils/generationDisplay'

const store = useAppStore()
const selectedLearnerId = ref(localStorage.getItem('last_learner_id') || store.currentLearnerId || '')
const profiles = ref([])
const tracks = ref([])
const report = reactive({})
const recentResources = computed(() => report.recent_resources || [])
const recentFeedback = computed(() => report.recent_feedback || [])
const metricSummary = computed(() => report.metric_summary || {})
const nextSuggestions = computed(() => report.next_suggestions || report.weak_points || [])
const activeProfile = computed(() => profiles.value.find((item) => item.learner_id === selectedLearnerId.value) || null)
const directionName = computed(() => resolveTrackName(activeProfile.value?.knowledge_base_id))
const averageCorrectRate = computed(() => formatPercent(metricSummary.value.average_correct_rate))
const profileOptions = computed(() => profiles.value.map((profile) => ({ ...profile, label: `${profileDisplayName(profile)} / ${resolveTrackName(profile.knowledge_base_id)} / ${profile.skill_level || '未分级'}` })))

function resolveTrackName(trackId) {
  return tracks.value.find((item) => item.track_id === trackId || item.knowledge_base_id === trackId)?.name || trackId || '未选择学习方向'
}
function profileDisplayName(profile) {
  const snapshot = profile?.learning_preferences?.metadata?.user_profile_snapshot
  return snapshot?.display_name || snapshot?.name || profile?.learner_type || '未命名画像'
}
function formatPercent(value) { return typeof value === 'number' ? `${Math.round(value * 100)}%` : '--' }
function feedbackResourceLabel(row) {
  const resource = recentResources.value.find((item) => item.resource_id === row.resource_id)
  return resource ? formatResourceLabel(resource, directionName.value) : row.resource_id ? `资源 ${row.resource_id.slice(0, 8)}` : '未命名资源'
}
function feedbackDecisionLabel(row) { return row.decision?.action || row.decision || '已记录本次练习结果' }

async function loadProfiles() {
  const [profileRes, domainRes] = await Promise.all([profileApi.list({ page: 1, page_size: 50 }), knowledgeApi.listDomains()])
  profiles.value = profileRes.data.items || profileRes.data.profiles || []
  tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
  if (!profiles.value.length) { selectedLearnerId.value = ''; return }
  if (!profiles.value.some((item) => item.learner_id === selectedLearnerId.value)) selectedLearnerId.value = store.currentLearnerId || profiles.value[0].learner_id
}
async function loadReport() {
  if (!selectedLearnerId.value) { ElMessage.warning('请先选择学习画像'); return }
  try {
    const res = await reportApi.get(selectedLearnerId.value)
    Object.assign(report, res.data)
    localStorage.setItem('last_learner_id', selectedLearnerId.value)
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '报告查询失败')
  }
}
async function handleProfileChange() { await loadReport() }
onMounted(async () => { await loadProfiles(); if (selectedLearnerId.value) await loadReport() })
</script>

<style scoped>
.report-page { --ink:#10233f; --muted:#627692; --line:#dbe6f2; display:flex; flex-direction:column; gap:16px; }
.report-hero,.report-snapshot,.report-section,.next-round-panel { border:1px solid var(--line); border-radius:18px; background:rgba(255,255,255,.96); box-shadow:0 12px 28px rgba(24,60,96,.06); }
.report-hero { position:relative; display:grid; grid-template-columns:minmax(0,1fr) minmax(350px,.55fr); gap:28px; align-items:center; min-height:156px; padding:24px 28px; overflow:hidden; background:radial-gradient(circle at 86% 14%,rgba(48,203,174,.19),transparent 30%),linear-gradient(115deg,#eff6ff,#fcfdff 60%,#eefaf7); }.report-hero::after { position:absolute; right:13%; bottom:-78px; width:210px; height:150px; border:1px solid rgba(66,172,148,.15); border-radius:50%; content:''; }.report-hero-copy { position:relative; z-index:1; }
.report-kicker { display:block; color:#176f61; font-size:12px; font-weight:800; letter-spacing:.09em; line-height:1; }.report-hero h2 { margin:8px 0 0; color:var(--ink); font-size:clamp(30px,2.3vw,40px); font-weight:800; letter-spacing:-.045em; line-height:1.08; }.report-hero p { max-width:720px; margin:10px 0 0; color:#536d8d; font-size:15px; line-height:1.6; }
.profile-selector { position:relative; z-index:1; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:9px 10px; padding:16px; border:1px solid rgba(255,255,255,.86); border-radius:14px; background:rgba(255,255,255,.76); backdrop-filter:blur(8px); }.profile-selector > span { grid-column:1 / -1; color:#5f7691; font-size:12px; font-weight:700; }.report-input { width:100%; }.profile-selector :deep(.el-button) { height:34px; border-radius:8px; font-weight:700; }
.report-snapshot { display:grid; grid-template-columns:minmax(270px,.7fr) minmax(0,1.3fr); gap:16px; padding:16px; }.learning-focus { min-width:0; padding:17px 19px; border-radius:14px; background:linear-gradient(145deg,#102d50,#1d4c7c); color:#fff; }.focus-state { display:flex; align-items:center; gap:8px; color:rgba(223,239,255,.82); font-size:12px; }.focus-state i { width:8px; height:8px; border-radius:50%; background:#49d1af; box-shadow:0 0 0 5px rgba(73,209,175,.14); }.learning-focus > strong { display:block; margin-top:12px; overflow:hidden; font-size:22px; text-overflow:ellipsis; white-space:nowrap; }.focus-goal { display:block; min-height:21px; margin-top:6px; overflow:hidden; color:rgba(218,235,252,.78); font-size:13px; text-overflow:ellipsis; white-space:nowrap; }.focus-meta { display:flex; gap:18px; margin-top:15px; padding-top:11px; border-top:1px solid rgba(218,235,252,.2); }.focus-meta span { color:rgba(218,235,252,.72); font-size:11px; }.focus-meta b { display:block; margin-top:4px; color:#fff; font-size:14px; }
.summary-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; }.summary-metric { display:flex; flex-direction:column; justify-content:center; min-width:0; padding:14px; border:1px solid #dce7f2; border-radius:13px; background:#fbfdff; }.summary-metric.mint { border-color:#cdeadd; background:#f3fbf8; }.summary-metric.blue { border-color:#d7e5fb; background:#f4f8ff; }.summary-metric.amber { border-color:#f4e3c7; background:#fffaf1; }.summary-metric.slate { border-color:#e1e7ee; background:#f8fafc; }.summary-metric span { overflow:hidden; color:#6c8199; font-size:12px; font-weight:650; text-overflow:ellipsis; white-space:nowrap; }.summary-metric strong { margin-top:8px; color:#183654; font-size:28px; line-height:1; }.summary-metric small { margin-top:6px; overflow:hidden; color:#8190a4; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }
.report-detail-grid { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:16px; }.report-section { min-height:276px; padding:20px; }.section-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:14px; margin-bottom:16px; }.section-heading h3,.next-round-panel h3 { margin:7px 0 0; color:var(--ink); font-size:22px; font-weight:800; letter-spacing:-.035em; line-height:1.1; }.section-count { padding:6px 9px; border-radius:999px; background:#eff6fc; color:#54728f; font-size:12px; font-weight:700; white-space:nowrap; }
.resource-list,.feedback-list { display:grid; gap:9px; }.resource-item { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:11px; padding:12px; border:1px solid #e0e8f1; border-radius:11px; background:#fbfdff; }.resource-type { padding:5px 7px; border-radius:7px; background:#eaf3ff; color:#2e72c7; font-size:11px; font-weight:800; white-space:nowrap; }.resource-item div { min-width:0; }.resource-item strong,.resource-item p { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.resource-item strong { color:#203b5a; font-size:14px; }.resource-item p { margin:5px 0 0; color:#72849a; font-size:12px; }.difficulty-tag { padding:5px 7px; border:1px solid #d3e9df; border-radius:999px; background:#f2fbf7; color:#228265; font-size:11px; white-space:nowrap; }.feedback-item { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:14px; border:1px solid #e0e8f1; border-radius:11px; background:#fbfdff; }.feedback-item div { min-width:0; }.feedback-item strong,.feedback-item span { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.feedback-item strong { color:#203b5a; font-size:14px; }.feedback-item span { margin-top:5px; color:#75889f; font-size:12px; }.feedback-item b { flex:0 0 auto; color:#168369; font-size:22px; }
.next-round-panel { display:grid; grid-template-columns:minmax(260px,.8fr) minmax(0,1.2fr); gap:24px; align-items:center; padding:20px 24px; overflow:hidden; background:linear-gradient(105deg,#f9fcff,#f0faf7); }.next-round-panel p { margin:9px 0 0; color:#5c738d; font-size:14px; line-height:1.55; }.suggestion-list { display:flex; flex-wrap:wrap; gap:9px; align-content:center; }.suggestion-list span { padding:9px 12px; border:1px solid #bfe5d8; border-radius:999px; background:rgba(255,255,255,.72); color:#227a64; font-size:13px; font-weight:700; }.suggestion-list em { color:#72849a; font-size:13px; font-style:normal; }
@media (max-width:1180px) { .report-snapshot { grid-template-columns:1fr; }.report-hero { grid-template-columns:1fr; }.profile-selector { max-width:560px; }.next-round-panel { grid-template-columns:1fr; gap:16px; } } @media (max-width:860px) { .report-page { gap:14px; }.report-detail-grid { grid-template-columns:1fr; }.summary-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); }.report-hero { padding:22px; }.report-section { min-height:0; }.resource-item { grid-template-columns:auto minmax(0,1fr); }.difficulty-tag { grid-column:2; justify-self:start; }.next-round-panel { padding:20px; } } @media (max-width:560px) { .report-hero h2 { font-size:30px; }.profile-selector { grid-template-columns:1fr; }.profile-selector :deep(.el-button) { width:100%; }.summary-metrics { grid-template-columns:1fr; }.focus-meta { gap:12px; }.resource-item { grid-template-columns:1fr; }.resource-type { justify-self:start; }.difficulty-tag { grid-column:auto; }.report-section { padding:18px; } }
</style>
