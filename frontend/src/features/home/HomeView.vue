<template>
  <div ref="workbenchRoot" class="home-page" :class="{ 'is-fit-layout': fitLayout }">
    <section class="home-hero" aria-label="当前学习与推荐下一步" :aria-busy="loadingSummary">
      <DashboardHeroAtmosphere />
      <div class="hero-copy">
        <div class="hero-intro">
          <span class="hero-eyebrow"><span class="focus-mark" aria-hidden="true"></span>当前学习方向 <span class="hero-code">LEARNING FOCUS / 01</span></span>
          <h2>{{ currentDirection?.name || store.currentLearningDirectionName || '开启你的技能进阶之旅' }}</h2>
        </div>
        <div class="hero-recommendation">
          <h3 class="next-action-title">{{ nextAction.title }}</h3>
          <p>{{ nextAction.description }}</p>
        </div>
        <div class="hero-navigation">
          <div class="hero-actions">
            <el-button class="workbench-primary" type="primary" :loading="loadingSummary" :disabled="loadingSummary" @click="$router.push(nextAction.to)">
              <span>{{ nextAction.button }}</span><el-icon aria-hidden="true"><ArrowRight /></el-icon>
            </el-button>
            <el-button class="workbench-switch" :icon="Switch" :disabled="loadingProfiles" @click="profileDialogVisible = true">切换画像</el-button>
          </div>
          <div class="hero-footnote"><svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true"><path d="M8 1 10 6 15 8 10 10 8 15 6 10 1 8 6 6Z" stroke="currentColor" stroke-linejoin="round"/></svg>个性化路径<span class="footnote-divider" aria-hidden="true"></span>多智能体协作<span class="footnote-divider" aria-hidden="true"></span>证据溯源</div>
        </div>
      </div>

      <div class="hero-visual">
        <svg
          class="knowledge-network"
          viewBox="0 0 540 345"
          fill="none"
          role="img"
          aria-label="学习流程：选择方向并建立画像，完成能力诊断，生成资源，学习资源，提交测评反馈，再确认纠错或下一轮学习方案。"
        >
          <defs>
            <linearGradient id="workbench-plane" x1="170" y1="100" x2="366" y2="215" gradientUnits="userSpaceOnUse"><stop stop-color="#77e9e1" stop-opacity=".23"/><stop offset="1" stop-color="#4389ed" stop-opacity=".06"/></linearGradient>
            <linearGradient id="workbench-edge" x1="165" y1="145" x2="370" y2="250" gradientUnits="userSpaceOnUse"><stop stop-color="#99f9eb"/><stop offset="1" stop-color="#4c8bdb"/></linearGradient>
            <radialGradient id="workbench-glow"><stop stop-color="#41b5d1" stop-opacity=".19"/><stop offset="1" stop-color="#41b5d1" stop-opacity="0"/></radialGradient>
            <marker id="workbench-route-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
              <path d="m2 1 4 3-4 3" stroke="#8abbd1" stroke-linecap="round" stroke-linejoin="round"/>
            </marker>
          </defs>
          <ellipse cx="270" cy="168" rx="235" ry="142" fill="url(#workbench-glow)"/>
          <g transform="translate(0 -20)">
            <g stroke="#7493b8" stroke-opacity=".20">
              <path d="M34 210 270 73 506 210 270 347Z M67 190 303 327 M100 171 336 308 M133 152 369 289 M166 133 402 270 M199 114 435 251 M232 95 468 232 M67 232 303 95 M100 251 336 114 M133 270 369 133 M166 289 402 152 M199 308 435 171 M232 327 468 190"/>
            </g>
            <g stroke="url(#workbench-edge)" stroke-width="1.2" fill="url(#workbench-plane)">
              <path d="m270 171 104 60-104 60-104-60Z"/><path d="m270 140 104 60-104 60-104-60Z"/><path d="m270 109 104 60-104 60-104-60Z"/>
              <path d="M166 169v62M374 169v62M270 229v62" stroke-opacity=".65"/>
            </g>
            <path d="m270 140 49 29-49 29-49-29Z" fill="#8af1e1" fill-opacity=".16" stroke="#98f4e6" stroke-width="1.5"/>
            <path d="m270 128 29 17v34l-29 17-29-17v-34Z" fill="#102d45" stroke="#9af4e5" stroke-width="1.4"/>
            <path d="m241 145 29 17 29-17M270 162v34" stroke="#9af4e5" stroke-width="1.4"/>
            <path d="m270 128 29 17-29 17-29-17Z" fill="#97f2e2" fill-opacity=".24"/>
            <g fill="#9af4e5"><circle cx="166" cy="169" r="3"/><circle cx="374" cy="169" r="3"/><circle cx="270" cy="291" r="3"/><circle cx="270" cy="109" r="3"/></g>
          </g>
          <g stroke="#729db9" stroke-opacity=".75" stroke-dasharray="4 5" marker-end="url(#workbench-route-arrow)">
            <path d="M129 85Q188 52 247 49"/>
            <path d="M289 50Q355 54 410 84"/>
            <path d="M446 112Q479 164 447 215"/>
            <path d="M412 245Q358 287 293 295"/>
            <path d="M250 295Q180 288 130 246"/>
          </g>
          <g v-for="step in learningFlow" :key="step.label" :transform="`translate(${step.x} ${step.y})`">
            <path d="m0-20 17 10v20l-17 10-17-10v-20Z" fill="#112f47" stroke="#7ddbd6" stroke-width="1.2"/>
            <path :d="step.icon" stroke="#c0f7ef" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            <text class="flow-label" :y="step.labelY">{{ step.label }}</text>
          </g>
        </svg>
        <div class="visual-caption" aria-hidden="true"><span class="caption-line"></span>学习流程</div>
      </div>
    </section>

    <section class="learning-summary" aria-label="当前学习摘要" :aria-busy="loadingSummary">
      <article v-for="(item, index) in learningSummary" :key="item.label" class="summary-item" :class="['summary-' + summaryDecorations[index].kind]" :title="item.initial ? `初始诊断：${item.initial}` : undefined">
        <div class="summary-topline"><span class="summary-label">{{ item.label }}</span><span class="summary-code" aria-hidden="true">{{ summaryDecorations[index].code }}</span></div>
        <div class="summary-value"><span class="summary-icon" aria-hidden="true"><el-icon><component :is="summaryDecorations[index].icon" /></el-icon></span><strong>{{ item.value }}</strong></div>
      </article>
    </section>

    <section class="workspace-grid">
      <div class="learning-tools">
        <div class="section-heading">
          <div><span class="section-index">01 / EXPLORE</span><h3>你的学习工具</h3></div>
          <span class="section-description">连接每一步学习</span>
        </div>
        <div class="tool-grid">
          <button v-for="tool in tools" :key="tool.title" type="button" class="tool-card" :class="tool.accent" @click="$router.push(tool.to)">
            <span class="tool-icon" aria-hidden="true"><el-icon><component :is="tool.icon" /></el-icon></span>
            <span class="tool-copy"><strong>{{ tool.title }}</strong><small>{{ tool.description }}</small></span>
            <span class="tool-index" aria-hidden="true">{{ tool.index }}</span>
            <el-icon class="tool-arrow" aria-hidden="true"><ArrowRight /></el-icon>
          </button>
        </div>
      </div>
    </section>
    <footer class="workspace-footer"><span>让知识有依据，让成长有路径。</span><span>智域匠学 <span aria-hidden="true">/</span> DOMAIN SKILL WORKBENCH</span></footer>
    <el-dialog v-model="profileDialogVisible" class="profile-switch-dialog" title="切换学习画像" width="560px" append-to-body align-center>
      <p class="profile-switch-description">选择已有画像，继续对应的学习方向与进度。</p>
      <div v-if="profileListError" class="profile-switch-error" role="alert">
        <p>{{ profileListError }}</p>
        <el-button class="profile-switch-retry" :loading="loadingProfiles" @click="loadSummary">重新加载</el-button>
      </div>
      <div v-else-if="!profiles.length" class="profile-switch-empty">
        <el-icon aria-hidden="true"><User /></el-icon><strong>尚未建立学习画像</strong><p>先选择学习方向，建立你的第一份画像。</p>
      </div>
      <div v-else class="profile-options" aria-label="可选学习画像">
        <button v-for="profile in profiles" :key="profile.learner_id" type="button" class="profile-option" :class="{ 'is-current': currentProfile?.learner_id === profile.learner_id }" :data-learner-id="profile.learner_id" :aria-pressed="currentProfile?.learner_id === profile.learner_id" @click="selectProfile(profile)">
          <span class="profile-option-icon" aria-hidden="true"><el-icon><User /></el-icon></span>
          <span class="profile-option-copy"><strong class="profile-option-name">{{ profileDisplayName(profile) }}</strong><span class="profile-option-direction">{{ resolveTrackName(profile.knowledge_base_id) }}</span><small>{{ profile.learning_goal || '尚未设置学习目标' }}</small></span>
          <span class="profile-option-meta"><span class="profile-option-stage">{{ currentProfileRating(profile) || '待诊断' }}</span><span v-if="currentProfile?.learner_id === profile.learner_id" class="profile-option-current"><el-icon aria-hidden="true"><Check /></el-icon>当前画像</span></span>
        </button>
      </div>
      <template #footer>
        <el-button class="profile-switch-create" :icon="Plus" @click="profileDialogVisible = false; $router.push('/learning/new')">新建学习方向</el-button>
        <el-button class="profile-switch-cancel" @click="profileDialogVisible = false">取消</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { currentProfileRating, initialProfileRating } from '../../utils/profileRating.js'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight, ChatDotRound, Check, Clock, Collection, Compass, DataAnalysis, Document, Plus, Reading, Switch, User } from '@element-plus/icons-vue'
import DashboardHeroAtmosphere from './DashboardHeroAtmosphere.vue'
import { generateApi } from '../generation/api.js'
import { knowledgeApi } from '../knowledge/api.js'
import { profileApi } from '../learners/api.js'
import { resourceApi } from '../learning-documents/api.js'
import { useAppStore } from '../../stores/app'
import { formatDateTime } from '../../utils/generationDisplay'

const store = useAppStore()
const profiles = ref([])
const tracks = ref([])
const resources = ref([])
const jobs = ref([])
const loadingSummary = ref(false)
const loadingProfiles = ref(false)
const profileListError = ref('')
const profileDialogVisible = ref(false)
const workbenchRoot = ref(null)
const fitLayout = ref(false)
const learningFlow = [
  { label: '方向与画像', x: 110, y: 95, labelY: -30, icon: 'M5-5-2-2-5 5l7-3 3-7Z M-2-2 2 2 M0-8v1M0 7v1M-8 0h1M7 0h1' },
  { label: '能力诊断', x: 270, y: 48, labelY: -29, icon: 'M-7 6h14M-5 2v-4M0 2v-8M5 2v-6' },
  { label: '生成资源', x: 430, y: 95, labelY: -30, icon: 'M-6-8H2l4 4V8H-6Z M2-8v4h4 M0-1v6m-3-3h6' },
  { label: '学习资源', x: 430, y: 233, labelY: 35, icon: 'M0-4c-3-2-6-2-8-1V6c3-1 5-1 8 1 3-2 5-2 8-1V-5c-2-1-5-1-8 1ZM0-4V7' },
  { label: '测评反馈', x: 270, y: 297, labelY: 36, icon: 'M-7-7H7V4H1l-4 4V4h-4Z M-4-1l2 2 5-5' },
  { label: '确认下一步', x: 110, y: 233, labelY: 35, icon: 'M-8 0h16M3-5l5 5-5 5' },
]
const summaryDecorations = [
  { kind: 'direction', code: 'TRACK / 01', icon: Compass },
  { kind: 'stage', code: 'PROFILE / 02', icon: User },
  { kind: 'resource', code: 'LIBRARY / 03', icon: Collection },
  { kind: 'time', code: 'ACTIVITY / 04', icon: Clock },
]
let layoutObserver
let layoutFrame = 0
let layoutMounted = false
let catalogRequestId = 0
let summaryRequestId = 0

function scheduleLayout() {
  cancelAnimationFrame(layoutFrame)
  layoutFrame = requestAnimationFrame(async () => {
    layoutFrame = 0
    if (!layoutMounted || !workbenchRoot.value) return
    fitLayout.value = window.innerWidth >= 1100 && window.innerHeight >= 640
    await nextTick()
    if (!layoutMounted || !fitLayout.value) return
    const root = workbenchRoot.value
    const area = root.closest('.content-area')
    const bounds = area.getBoundingClientRect()
    // Enable a fixed canvas only when its actual content fits, including user text.
    const regions = [root, ...root.querySelectorAll('.workspace-heading, .home-hero, .hero-copy, .learning-summary, .summary-item, .workspace-grid, .tool-grid, .tool-card, .workspace-footer')]
    const overflow = regions.some((node) => node.scrollHeight > node.clientHeight + 1 || node.scrollWidth > node.clientWidth + 1)
    const clippedText = [...root.querySelectorAll('h2, h3, p, strong, small, button, .hero-footnote, .workspace-footer')].some((node) => {
      const rect = node.getBoundingClientRect()
      return rect.top < bounds.top - 1 || rect.bottom > bounds.bottom + 1
    })
    if (overflow || clippedText) fitLayout.value = false
    else area.scrollTop = 0
  })
}

const currentProfile = computed(() =>
  profiles.value.find((profile) => profile.learner_id === store.currentLearnerId) || store.currentProfile || profiles.value[0] || null,
)
const currentDirection = computed(() => {
  const directionId = currentProfile.value?.knowledge_base_id || store.currentLearningDirectionId
  return tracks.value.find((track) => track.track_id === directionId || track.knowledge_base_id === directionId) || null
})
const profileStage = computed(() => currentProfileRating(currentProfile.value) || (currentProfile.value ? '待诊断' : '未建立'))
const generatedResourceCount = computed(() => resources.value.length || jobs.value.reduce((total, job) => total + (job.resource_ids?.length || 0), 0))
const latestLearningTime = computed(() => {
  const values = [
    ...resources.value.map((resource) => resource.created_at),
    ...jobs.value.map((job) => job.finished_at || job.created_at),
  ].filter(Boolean)
  if (!values.length) return '暂无记录'
  return formatDateTime(values.sort((left, right) => String(right).localeCompare(String(left)))[0])
})

const learningSummary = computed(() => [
  { label: '当前方向', value: currentDirection.value?.name || store.currentLearningDirectionName || '未选择' },
  { label: '当前评级', value: profileStage.value, initial: initialProfileRating(currentProfile.value) },
  { label: '已生成资源数量', value: `${generatedResourceCount.value} 份` },
  { label: '最近一次学习时间', value: latestLearningTime.value },
])
const nextAction = computed(() => {
  if (!currentProfile.value) return {
    title: '先建立学习方向', description: '选择学习目标并完成初始诊断，系统会据此生成第一批学习资源。',
    button: '新建学习方向', to: '/learning/new',
  }
  if (!generatedResourceCount.value) return {
    title: '生成第一批学习资源', description: '当前画像已就绪，选择资源类型后即可开始生成个性化学习材料。',
    button: '去生成资源', to: '/generate',
  }
  return {
    title: '继续阅读本轮学习资源', description: '完成资源学习后提交练习反馈，即可获得强化薄弱点或学习新知识的下一步选择。',
    button: '进入学习资源', to: '/resources',
  }
})

function resolveTrackName(id) {
  return tracks.value.find((item) => item.track_id === id || item.knowledge_base_id === id)?.name || id || '未命名方向'
}

function profileDisplayName(profile) {
  const snapshot = profile?.learning_preferences?.metadata?.user_profile_snapshot
  return snapshot?.display_name || snapshot?.name || profile?.learner_type || '未命名画像'
}

async function loadProfileSummary(learnerId) {
  const requestId = ++summaryRequestId
  resources.value = []
  jobs.value = []
  loadingSummary.value = true
  try {
    const [resourceResult, jobResult] = await Promise.allSettled([
      resourceApi.listByLearner(learnerId),
      generateApi.listJobs(learnerId),
    ])
    if (!layoutMounted || requestId !== summaryRequestId) return
    if (resourceResult.status === 'fulfilled') resources.value = resourceResult.value.data.resources || []
    if (jobResult.status === 'fulfilled') jobs.value = jobResult.value.data.items || []
  } finally {
    if (layoutMounted && requestId === summaryRequestId) loadingSummary.value = false
  }
}

function selectProfile(profile) {
  profileDialogVisible.value = false
  if (profile.learner_id === currentProfile.value?.learner_id) return
  store.resumeProfile(profile, profile.knowledge_base_id, resolveTrackName(profile.knowledge_base_id))
  loadProfileSummary(profile.learner_id)
}

async function listAllProfiles(requestId) {
  const items = []
  for (let page = 1; ; page++) {
    const result = await profileApi.list({ page, page_size: 50 })
    if (!layoutMounted || requestId !== catalogRequestId) return null
    const batch = result.data.items || result.data.profiles || []
    items.push(...batch)
    if (!batch.length || (Number.isFinite(result.data.total) ? items.length >= result.data.total : batch.length < 50)) break
  }
  return [...new Map(items.map((profile) => [profile.learner_id, profile])).values()]
}

async function loadSummary() {
  const requestId = ++catalogRequestId
  ++summaryRequestId
  loadingSummary.value = true
  loadingProfiles.value = true
  profileListError.value = ''
  let summaryStarted = false
  try {
    const [profileItems, domainResult] = await Promise.all([
      listAllProfiles(requestId),
      knowledgeApi.listDomains(),
    ])
    if (!layoutMounted || requestId !== catalogRequestId || !profileItems) return
    profiles.value = profileItems
    tracks.value = (domainResult.data.domains || []).flatMap((domain) => domain.tracks || [])
    loadingProfiles.value = false
    const learnerId = currentProfile.value?.learner_id || store.currentLearnerId
    if (!learnerId) return
    const profile = profiles.value.find((item) => item.learner_id === learnerId)
    if (profile) store.resumeProfile(profile, profile.knowledge_base_id, resolveTrackName(profile.knowledge_base_id))
    summaryStarted = true
    await loadProfileSummary(learnerId)
  } catch (error) {
    if (!layoutMounted || requestId !== catalogRequestId) return
    console.error(error)
    profileListError.value = '学习画像加载失败，请重新加载。'
    ElMessage.error('当前学习摘要加载失败')
  } finally {
    if (layoutMounted && requestId === catalogRequestId) {
      loadingProfiles.value = false
      if (!summaryStarted) loadingSummary.value = false
    }
  }
}

const tools = [
  { index: '01', title: '学习资源', description: '进入资源学习与阅读', to: '/resources', icon: Reading, accent: 'tool-resources' },
  { index: '02', title: '练习反馈', description: '记录练习结果', to: '/feedback', icon: ChatDotRound, accent: 'tool-feedback' },
  { index: '03', title: '学习报告', description: '回看诊断与进步', to: '/report', icon: DataAnalysis, accent: 'tool-report' },
  { index: '04', title: '学习历史', description: '按画像查看内容', to: '/learning/history', icon: Document, accent: 'tool-history' },
]

watch([learningSummary, nextAction, loadingSummary], scheduleLayout, { flush: 'post' })
onMounted(() => {
  layoutMounted = true
  layoutObserver = new ResizeObserver(scheduleLayout)
  layoutObserver.observe(workbenchRoot.value.closest('.content-area'), { box: 'border-box' })
  scheduleLayout()
  loadSummary()
})
onBeforeUnmount(() => {
  layoutMounted = false
  ++catalogRequestId
  ++summaryRequestId
  cancelAnimationFrame(layoutFrame)
  layoutObserver?.disconnect()
})
</script>

<style scoped>
.home-page {
  --wb-ink: #172c45;
  --wb-muted: #59697b;
  --wb-line: #dce2e8;
  --wb-paper: #ffffff;
  --wb-canvas: #f5f7f9;
  --wb-night: #101f35;
  --wb-on-night: #f3f7fc;
  --wb-night-muted: #b6c8dc;
  --wb-accent: #9cf2e0;
  --wb-accent-ink: #112f37;
  --wb-focus: #2269ba;
  display: flex;
  flex-direction: column;
  min-width: 0;
  max-width: 1680px;
  margin: 0 auto;
  padding-bottom: 6px;
  color: var(--wb-ink);
}
.section-index { color:var(--wb-muted); font:500 11px/1.5 Consolas,'SFMono-Regular',monospace; }
.home-hero {
  position:relative;
  display:grid;
  grid-template-columns:minmax(0,1.1fr) minmax(320px,1fr);
  min-height:330px;
  isolation:isolate;
  overflow:hidden;
  border:1px solid #294764;
  border-radius:8px;
  background-color:var(--wb-night);
  background-image:
    radial-gradient(ellipse at 76% 42%,#20556a9e,transparent 58%),
    linear-gradient(118deg,#101f35 10%,#162d47 58%,#101e34);
  box-shadow:inset 0 1px #b5e2ff24,0 10px 24px #152e481a;
  color:var(--wb-on-night);
}
.home-hero::before {
  position:absolute;
  z-index:2;
  inset:0 auto 0 0;
  width:3px;
  background:linear-gradient(#a4f5df,#62b8cd 52%,#4373a966);
  pointer-events:none;
  content:'';
}
.hero-copy { z-index:1; display:flex; min-width:0; flex-direction:column; justify-content:space-between; gap:20px; padding:30px 18px 28px 36px; }
.hero-eyebrow { display:flex; align-items:center; gap:9px; color:var(--wb-night-muted); font-size:15px; font-weight:550; line-height:1.5; }
.focus-mark { width:8px; height:8px; flex:0 0 8px; background:var(--wb-accent); }
.hero-code { margin-left:12px; color:var(--wb-night-muted); font:12px/1.5 Consolas,'SFMono-Regular',monospace; }
.hero-copy h2 { max-width:760px; margin:14px 0 0; color:var(--wb-on-night); font-size:clamp(26px,2.5vw,38px); font-weight:650; line-height:1.35; overflow-wrap:anywhere; text-wrap:balance; }
.next-action-title { margin:0; color:var(--wb-on-night); font-size:16px; font-weight:500; line-height:1.6; }
.hero-copy p { max-width:540px; margin:7px 0 0; color:var(--wb-night-muted); font-size:14px; line-height:1.8; text-wrap:pretty; }
.hero-actions { display:flex; flex-wrap:wrap; gap:12px; margin-top:0; }
.workbench-primary.el-button { height:46px; margin:0; padding:0 16px 0 20px; border:1px solid var(--wb-accent); border-radius:5px; background:var(--wb-accent); color:var(--wb-accent-ink); font-size:14px; font-weight:650; box-shadow:0 3px 10px #030d191f; }
.workbench-primary :deep(> span) { gap:28px; }
.workbench-primary.el-button:hover { border-color:#c7fff0; background:#c7fff0; color:var(--wb-accent-ink); }
.workbench-primary .el-icon { font-size:18px; transition:transform 180ms ease; }
.workbench-primary:hover .el-icon { transform:translateX(3px); }
.workbench-switch.el-button { height:46px; margin:0; padding:0 14px; border:1px solid #637a96; border-radius:5px; background:transparent; color:var(--wb-on-night); font-size:13px; font-weight:500; }
.workbench-switch.el-button:hover { border-color:var(--wb-night-muted); background:#1b3049; color:var(--wb-on-night); }
.workbench-switch.el-button:disabled { opacity:.58; cursor:wait; }
.hero-footnote { display:flex; align-items:center; flex-wrap:wrap; gap:9px; margin-top:20px; color:var(--wb-night-muted); font-size:11px; line-height:1.6; }
.hero-footnote > svg { color:var(--wb-accent); flex:0 0 16px; }
.footnote-divider { width:1px; height:9px; margin:0 4px; background:#657f9a; }
.hero-visual { position:relative; display:flex; min-width:0; flex-direction:column; justify-content:center; padding:8px 28px 18px 16px; }
.knowledge-network {
  display:block;
  width:100%;
  max-width:550px;
  max-height:300px;
  margin:0 auto;
  transform:translate(calc(var(--hero-x,0) * 12px),calc(var(--hero-y,0) * 8px));
  transition:transform 420ms cubic-bezier(.18,.72,.28,1);
}
.flow-label { fill:#d0e2ed; font:500 15px/1.3 system-ui,'Microsoft YaHei',sans-serif; text-anchor:middle; }
.visual-caption { display:flex; align-items:center; justify-content:center; gap:9px; color:var(--wb-night-muted); font-size:11px; }
.caption-line { width:20px; height:1px; background:var(--wb-accent); }
.learning-summary { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); margin-top:18px; padding:0; overflow:hidden; border:1px solid var(--wb-line); border-radius:5px; background:var(--wb-paper); box-shadow:0 3px 10px #172c4504; }
.summary-item { display:flex; flex-direction:column; min-width:0; padding:17px 22px; border-left:2px solid var(--column-ink); }
.summary-direction,.tool-resources { --column-ink:#315d87; --column-surface:#f0f5fa; --column-line:#d8e2ed; }
.summary-stage,.tool-feedback { --column-ink:#665496; --column-surface:#f5f1fa; --column-line:#e1daed; }
.summary-resource,.tool-report { --column-ink:#15677a; --column-surface:#edf7f6; --column-line:#cfe4e7; }
.summary-time,.tool-history { --column-ink:#536b87; --column-surface:#f0f5fa; --column-line:#d8e2ed; }
.summary-topline { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:4px 10px; }
.summary-label { color:var(--wb-ink); font-size:15px; font-weight:600; line-height:1.5; }
.summary-code { color:var(--wb-muted); font:9px/1.5 Consolas,'SFMono-Regular',monospace; }
.summary-value { display:flex; align-items:center; gap:12px; min-width:0; min-height:52px; margin-top:auto; padding-top:8px; }
.summary-icon { display:grid; width:32px; height:32px; flex:0 0 32px; place-items:center; border:1px solid var(--column-line); border-radius:3px; background:var(--column-surface); color:var(--column-ink); font-size:19px; }
.summary-item strong { display:block; min-width:0; color:var(--wb-ink); font-size:18px; font-weight:650; line-height:1.3; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.summary-stage strong { font-size:23px; }
.summary-resource strong { color:var(--column-ink); font-size:29px; font-weight:600; }
.summary-time strong { font-size:16px; }
.workspace-grid { display:block; padding-top:28px; }
.learning-tools { min-width:0; }
.section-heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:19px; }
.section-index { display:block; font-size:12px; line-height:1.4; }
.section-heading h3 { margin:6px 0 0; font-size:21px; font-weight:650; line-height:1.4; }
.section-description { color:var(--wb-muted); font-size:12px; }
.tool-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); border-top:1px solid var(--wb-line); }
.tool-card { --tool-icon-size:clamp(48px,3.6vw,56px); position:relative; display:grid; grid-template-columns:var(--tool-icon-size) minmax(0,1fr) 18px; align-items:center; gap:15px; min-width:0; min-height:112px; padding:22px 25px 22px 14px; border:0; border-bottom:1px solid var(--wb-line); border-radius:0; background:transparent; color:var(--wb-ink); text-align:left; cursor:pointer; transition:background-color 180ms ease,color 180ms ease; }
.tool-card:nth-child(odd) { border-right:1px solid var(--wb-line); }
.tool-card:nth-child(even) { padding-left:27px; }
.tool-card:hover { background:var(--wb-paper); }
.tool-card::before { position:absolute; inset:0 auto 0 0; width:2px; background:var(--column-ink); content:''; opacity:0; transition:opacity 180ms ease; }
.tool-card:is(:hover,:focus-visible,:active)::before { opacity:1; }
.tool-icon { display:grid; width:var(--tool-icon-size); aspect-ratio:1; place-items:center; border:1px solid var(--column-line); border-radius:12px; background:var(--column-surface); color:var(--column-ink); font-size:clamp(30px,2.1vw,34px); }
.tool-copy { min-width:0; }
.tool-copy strong { display:block; font-size:22px; font-weight:650; line-height:1.4; }
.tool-copy small { display:block; margin-top:5px; color:var(--wb-muted); font-size:14px; line-height:1.6; overflow-wrap:anywhere; }
.tool-index { position:absolute; top:12px; right:16px; color:var(--wb-muted); font:11px/1.5 Consolas,'SFMono-Regular',monospace; }
.tool-arrow { color:#496580; font-size:18px; transition:transform 180ms ease; }
.tool-card:hover .tool-arrow { transform:translateX(3px); }
.workspace-footer { display:flex; flex-wrap:wrap; justify-content:space-between; gap:12px; margin-top:27px; padding-top:16px; color:var(--wb-muted); font-size:11px; line-height:1.8; }
.workspace-footer > span:last-child { font-size:10px; }
.workspace-footer > span:last-child > span { margin:0 7px; }
.home-page button:focus-visible { outline:3px solid var(--wb-focus); outline-offset:4px; }
.home-hero button:focus-visible { outline-color:var(--wb-accent); }
.home-page button:active { filter:brightness(.96); }
.profile-switch-description { margin:0 0 20px; color:#59697b; font-size:13px; line-height:1.6; }
.profile-options { display:flex; flex:1 1 auto; min-height:0; flex-direction:column; gap:8px; max-height:min(52dvh,440px); overflow:auto; padding:4px; margin:-4px; }
.profile-option { flex:0 0 auto; }
.profile-option { display:flex; align-items:center; gap:14px; width:100%; padding:16px; border:1px solid #dce2e8; border-radius:6px; background:#fff; color:#172c45; text-align:left; cursor:pointer; transition:background-color 180ms ease,border-color 180ms ease; }
.profile-option:hover { border-color:#7899b5; background:#f5f8fb; }
.profile-option.is-current { border-color:#39788c; background:#eff8f7; }
.profile-option-icon { display:grid; flex:0 0 36px; width:36px; height:36px; place-items:center; border:1px solid #d6e1ea; border-radius:5px; background:#f0f5fa; color:#315d87; font-size:21px; }
.profile-option-copy { flex:1; min-width:0; }
.profile-option-name { display:block; font-size:15px; line-height:1.5; overflow-wrap:anywhere; }
.profile-option-direction { display:block; margin-top:3px; color:#315d87; font-size:13px; line-height:1.5; overflow-wrap:anywhere; }
.profile-option-copy small { display:block; margin-top:5px; color:#59697b; font-size:12px; line-height:1.5; overflow-wrap:anywhere; }
.profile-option-meta { display:flex; flex:0 0 auto; flex-direction:column; align-items:flex-end; gap:8px; }
.profile-option-stage { color:#59697b; font-size:12px; }
.profile-option-current { display:flex; align-items:center; gap:4px; color:#205c6c; font-size:12px; }
.profile-option:focus-visible { outline:3px solid #2269ba; outline-offset:1px; }
.profile-switch-empty { display:flex; flex-direction:column; align-items:center; gap:12px; padding:28px 12px; color:#172c45; }
.profile-switch-empty > .el-icon { color:#315d87; font-size:32px; }
.profile-switch-empty p,.profile-switch-error p { margin:0; color:#59697b; font-size:13px; line-height:1.6; }
.profile-switch-error { display:flex; flex-direction:column; align-items:center; gap:16px; padding:20px 0; }
.profile-switch-create.el-button,.profile-switch-cancel.el-button,.profile-switch-retry.el-button { min-height:40px; margin:0; border:1px solid #b4c0cd; border-radius:5px; background:#fff; color:#172c45; font-weight:500; }
.profile-switch-create.el-button { border-color:transparent; color:#315d87; }
.profile-switch-create.el-button:hover,.profile-switch-cancel.el-button:hover,.profile-switch-retry.el-button:hover { background:#edf4f8; border-color:#7899b5; }
:global(.profile-switch-dialog) { display:flex; flex-direction:column; max-width:calc(100vw - 24px); max-height:calc(100dvh - 32px); padding:24px; border-radius:8px; }
:global(.profile-switch-dialog .el-dialog__header) { flex:0 0 auto; padding-bottom:16px; }
:global(.profile-switch-dialog .el-dialog__body) { display:flex; flex:1 1 auto; min-height:0; flex-direction:column; }
:global(.profile-switch-dialog .el-dialog__footer) { display:flex; flex:0 0 auto; justify-content:space-between; gap:12px; padding-top:20px; }
:global(.profile-switch-dialog .el-dialog__title) { color:#172c45; font-size:20px; font-weight:650; }
:global(.profile-switch-dialog .el-dialog__headerbtn:focus-visible),:global(.profile-switch-dialog button:focus-visible) { outline:3px solid #2269ba; outline-offset:2px; }
@media (min-width:1700px) {
  .hero-copy { padding:33px 0 30px 40px; }
  .home-hero { min-height:324px; }
  .hero-copy h2 { margin-top:21px; margin-bottom:15px; }
  .hero-copy p { max-width:650px; font-size:14px; }
  .knowledge-network { max-height:286px; }
  .hero-actions { margin-top:23px; }
  .summary-item { padding-block:21px; }
  .workspace-grid { padding-top:28px; }
  .tool-card { min-height:118px; }
}
@media (max-width:1200px) {
  .hero-copy { padding:30px 0 28px 28px; }
  .hero-code { display:none; }
  .hero-visual { padding-right:14px; padding-left:0; }
  .workspace-grid { gap:26px; grid-template-columns:minmax(0,1.3fr) minmax(250px,.8fr); }
  .tool-card { gap:12px; padding-right:17px; }
  .tool-card:nth-child(even) { padding-left:18px; }
}
@media (max-width:900px) {
  .home-hero { grid-template-columns:minmax(0,1fr) minmax(240px,.7fr); }
  .hero-copy h2 { font-size:27px; }
  .flow-label { font-size:18px; }
  .workspace-grid { grid-template-columns:1fr; gap:28px; }
  .summary-item { padding-inline:16px; }
  .summary-code { display:none; }
}
@media (max-width:600px) {
  :global(.profile-switch-dialog) { margin:12px auto; padding:20px; }
  .profile-options { max-height:48dvh; }
  .profile-option { gap:10px; padding:13px 10px; }
  .profile-option-icon { display:none; }
  .home-hero { display:flex; flex-direction:column; }
  .hero-copy { padding:27px 23px 0; }
  .hero-copy h2 { margin-top:19px; font-size:27px; }
  .hero-actions { gap:10px; }
  .workbench-primary :deep(> span) { gap:16px; }
  .workbench-primary.el-button { padding-inline:14px; }
  .workbench-switch.el-button { padding-inline:10px; }
  .hero-footnote { margin-top:23px; }
  .hero-visual { padding:4px 18px 20px; }
  .knowledge-network { max-width:320px; max-height:200px; }
  .learning-summary { grid-template-columns:repeat(2,minmax(0,1fr)); margin-top:18px; }
  .summary-item { padding:17px 14px; }
  .summary-item:nth-child(n+3) { border-top:1px solid var(--wb-line); }
  .summary-value { gap:9px; }
  .summary-icon { width:27px; height:27px; flex-basis:27px; font-size:17px; }
  .summary-item strong { font-size:14px; }
  .summary-resource strong { font-size:25px; }
  .workspace-grid { padding-top:24px; }
  .section-heading { margin-bottom:16px; }
  .section-heading h3 { font-size:20px; }
  .section-description { display:none; }
  .tool-grid { grid-template-columns:1fr; }
  .tool-card,.tool-card:nth-child(even) { min-height:98px; padding:20px 20px 20px 10px; }
  .tool-card:nth-child(odd) { border-right:0; }
  .workspace-footer { margin-top:16px; }
}
.home-page.is-fit-layout {
  display:grid;
  grid-template-rows:minmax(218px,1.35fr) auto minmax(150px,1fr) auto;
  gap:clamp(8px,1.2dvh,16px);
  height:100%;
  min-height:0;
  padding:0;
}
.is-fit-layout .home-hero { min-height:0; grid-template-columns:minmax(0,1.1fr) minmax(300px,1fr); }
.is-fit-layout .hero-copy { justify-content:space-between; gap:clamp(12px,1.8dvh,20px); padding:clamp(18px,2.3dvh,26px) 16px clamp(18px,2.3dvh,26px) clamp(24px,2.3vw,40px); }
.is-fit-layout .hero-copy h2 { margin:clamp(10px,1.4dvh,16px) 0 0; font-size:clamp(26px,3.7dvh,38px); line-height:1.3; }
.is-fit-layout .next-action-title { font-size:15px; line-height:1.6; }
.is-fit-layout .hero-copy p { margin-top:7px; max-width:540px; font-size:13px; line-height:1.75; }
.is-fit-layout .hero-actions { margin-top:0; }
.is-fit-layout .workbench-primary.el-button,.is-fit-layout .workbench-switch.el-button { height:40px; }
.is-fit-layout .hero-footnote { margin-top:clamp(12px,1.8dvh,18px); font-size:11px; line-height:1.5; }
.is-fit-layout .hero-visual { min-height:0; justify-content:center; padding:16px 22px 16px 8px; }
.is-fit-layout .knowledge-network { min-height:0; max-height:calc(100% - 28px); flex:1 1 0; }
.is-fit-layout .visual-caption { flex:0 0 auto; margin-top:5px; }
.is-fit-layout .learning-summary { margin:0; }
.is-fit-layout .summary-item { padding:clamp(10px,1.7dvh,18px) 19px; }
.is-fit-layout .summary-value { margin-top:auto; min-height:clamp(42px,6dvh,54px); padding-top:7px; }
.is-fit-layout .summary-item strong { font-size:clamp(15px,2.1dvh,20px); }
.is-fit-layout .summary-stage strong { font-size:clamp(19px,2.6dvh,25px); }
.is-fit-layout .summary-resource strong { font-size:clamp(25px,3.4dvh,32px); }
.is-fit-layout .summary-time strong { font-size:clamp(14px,1.8dvh,18px); }
.is-fit-layout .workspace-grid { min-height:0; gap:32px; padding:0; }
.is-fit-layout .learning-tools { display:flex; height:100%; min-height:0; flex-direction:column; }
.is-fit-layout .section-heading { flex:0 0 auto; gap:12px; margin-bottom:clamp(8px,1.1dvh,15px); }
.is-fit-layout .section-heading h3 { margin-top:2px; font-size:clamp(17px,2.3dvh,22px); line-height:1.2; }
.is-fit-layout .tool-grid { flex:1 1 0; min-height:0; grid-template-rows:repeat(2,minmax(0,1fr)); }
.is-fit-layout .tool-card { min-height:0; padding-block:10px; }
.is-fit-layout .tool-copy strong { font-size:clamp(18px,2.6dvh,22px); }
.is-fit-layout .tool-copy small { margin-top:3px; line-height:1.4; }
.is-fit-layout .tool-index { top:7px; }
.is-fit-layout .workspace-footer { margin:0; padding-top:3px; font-size:10px; line-height:1.4; }
@media (max-height:720px) and (min-width:1100px) {
  .home-page.is-fit-layout { grid-template-rows:minmax(218px,1.1fr) auto minmax(150px,1fr) auto; }
  .is-fit-layout .home-hero { grid-template-columns:minmax(0,1.25fr) minmax(260px,.8fr); }
  .is-fit-layout .hero-copy { justify-content:center; gap:0; padding-block:10px; padding-right:0; }
  .is-fit-layout .hero-copy h2 { font-size:26px; line-height:1.25; margin:8px 0 6px; }
  .is-fit-layout .next-action-title { font-size:14px; line-height:1.5; }
  .is-fit-layout .hero-copy p { margin-top:4px; max-width:620px; font-size:12px; line-height:1.6; }
  .is-fit-layout .hero-actions { margin-top:10px; }
  .is-fit-layout .hero-footnote { margin-top:10px; font-size:10px; }
  .is-fit-layout .summary-item { padding:9px 16px; }
  .is-fit-layout .summary-code { display:none; }
  .is-fit-layout .summary-icon { width:28px; height:28px; flex-basis:28px; font-size:17px; }
  .is-fit-layout .summary-value { gap:9px; }
  .is-fit-layout .section-heading { margin-bottom:7px; }
}
@media (prefers-reduced-motion:reduce) {
  .home-page *, .home-page *::before, .home-page *::after { transition:none !important; animation:none !important; }
  .knowledge-network { transform:none; }
  :global(.profile-switch-dialog *) { transition:none !important; animation:none !important; }
}
@media (min-width:1100px) {
  .tool-grid { grid-template-columns:repeat(4,minmax(0,1fr)); }
  .tool-card,.tool-card:nth-child(even) { gap:clamp(9px,1vw,15px); padding-inline:clamp(12px,1.2vw,20px); }
  .tool-card { border-right:1px solid var(--wb-line); }
  .tool-card:last-child { border-right:0; }
  .is-fit-layout .tool-grid { grid-template-rows:minmax(0,1fr); }
}
</style>
