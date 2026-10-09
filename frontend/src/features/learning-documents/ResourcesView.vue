<template>
  <div class="resources-layout" :class="{ 'has-tutor-panel': tutorOpen, 'is-focus-mode': isFocusMode }">
    <div class="resources-page" :class="{ 'is-focus-mode': isFocusMode }">
    <header class="learning-toolbar">
      <div class="toolbar-fields">
        <label class="field-label">
          <span class="field-caption">学习画像<small aria-hidden="true">PROFILE</small></span>
          <el-select v-model="selectedLearnerId" filterable placeholder="选择学习画像" popper-class="refined-select-dropdown" @change="handleProfileChange">
            <el-option v-for="item in profileOptions" :key="item.learner_id" :label="item.label" :value="item.learner_id" />
          </el-select>
        </label>
        <label class="field-label">
          <span class="field-caption">资源批次<small aria-hidden="true">BATCH</small></span>
          <el-select v-model="selectedRunId" filterable :disabled="!taskGroups.length" placeholder="选择资源批次" popper-class="refined-select-dropdown" @change="handleRunChange">
            <el-option v-for="task in taskGroups" :key="task.runId" :label="task.label" :value="task.runId" />
          </el-select>
        </label>
      </div>
      <div class="toolbar-actions">
        <el-button class="courseware-button" @click="openCoursewareGeneration">前往资源生成</el-button>
        <el-tooltip content="刷新资源" placement="bottom">
          <el-button class="refresh-button" :icon="Refresh" circle :loading="loading" aria-label="刷新资源" @click="loadResources" />
        </el-tooltip>
        <el-tooltip content="进入专注学习模式" placement="bottom">
          <el-button class="focus-button" :icon="FullScreen" circle aria-label="进入专注学习模式" @click="enterFocusMode" />
        </el-tooltip>
      </div>
    </header>

    <template v-if="activeTask">
      <section class="learning-workspace">
        <aside class="resource-shelf">
          <div class="shelf-heading">
            <div><span class="eyebrow">Current Materials</span><h3>本次资源</h3></div>
            <span class="shelf-count">{{ activeTask.resources.length }}</span>
          </div>
          <button v-for="(resource, index) in activeResources" :key="resource.resource_id" type="button" class="resource-item" :class="{ 'is-active': resource.resource_id === selectedResourceId }" @click="selectedResourceId = resource.resource_id">
            <span class="resource-order">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="resource-item-copy"><strong>{{ resourceShelfTypeLabel(resource) }}</strong><small>{{ resource.difficulty || '待分级' }} · {{ knowledgePointSummary(resource) }}</small></span>
            <span class="resource-arrow">→</span>
          </button>
          <el-button class="resource-feedback-button" @click="goToFeedback">反馈测评</el-button>
          <div class="shelf-footnote"><span class="footnote-dot"></span>按顺序完成本批次学习</div>
        </aside>

        <main class="reading-stage" v-module-motion="{ key: selectedLearnerId + ':' + selectedRunId + ':' + selectedResourceId, ready: !loading && !!selectedResource }">
          <FocusResourceSwitcher
            v-if="isFocusMode"
            :resources="activeResources"
            :selected-resource-id="selectedResourceId"
            @select-resource="selectedResourceId = $event"
          />
          <CoursewareViewer v-if="selectedResource?.resource_kind === 'interactive_courseware'" :resource="selectedResource" :focus-mode="isFocusMode" />
          <ResourceViewer
            v-else-if="selectedResource"
            :resources="[selectedResource]"
            :progress-label="resourceProgress"
            :resource-choices="[]"
            @ask-tutor="askTutorAboutSelection"
          >
            <template #header-end-actions>
              <el-button class="tutor-trigger" @click="openTutor">
                <el-icon><ChatDotRound /></el-icon>
                <span>向 Tutor 提问</span>
              </el-button>
            </template>
          </ResourceViewer>
        </main>
      </section>
    </template>

    <PreparationWorkspace
      v-if="!activeTask"
      class="library-empty"
      :pending="loading"
      :title="libraryPreparation.title"
      :status="libraryPreparation.status"
      :description="libraryPreparation.description"
      :capabilities="[
        { icon: Reading, eyebrow: '01 / CONTENT', title: '阅读与理解', description: '从概念、案例到知识要点，让理解有清晰的结构。', detail: '讲义 · 案例 · 复习清单' },
        { icon: EditPen, eyebrow: '02 / PRACTICE', title: '实践与验证', description: '沿着实操步骤应用知识，通过测评检验学习效果。', detail: '实操指南 · 分阶测评' },
        { icon: ChatDotRound, eyebrow: '03 / REFLECTION', title: '提问与复盘', description: '向 Tutor 追问难点，用真实反馈调整下一轮重点。', detail: 'Tutor 问答 · 学习反馈' },
      ]"
      footer-title="从理解，到实践，再到复盘。"
      footer-description="已发布的材料会归档到这里，围绕你的目标持续学习。"
    >
      <template #actions>
        <template v-if="loaded && !loading">
          <el-button v-if="libraryError" type="primary" @click="retryResources">重新加载</el-button>
          <el-button v-if="activeProfile" :type="libraryError ? 'default' : 'primary'" @click="openCoursewareGeneration">前往资源生成<el-icon aria-hidden="true"><ArrowRight /></el-icon></el-button>
          <el-button :type="activeProfile ? 'default' : 'primary'" @click="$router.push('/learning/new')">新建学习方向</el-button>
        </template>
        <span v-else class="library-loading-note">{{ loading ? '正在读取学习材料…' : '可使用上方刷新资源重新获取材料' }}</span>
      </template>
    </PreparationWorkspace>

    <el-tooltip v-if="isFocusMode" content="退出专注学习模式" placement="left">
      <el-button class="focus-exit" :icon="Close" circle aria-label="退出专注学习模式" @click="exitFocusMode" />
    </el-tooltip>

    </div>
    <TutorDrawer
    v-model="tutorOpen"
    :embedded="isFocusMode"
    :full-height="isFocusMode"
    :learner-id="selectedLearnerId"
    :resource="selectedResource"
    :batch-id="activeTask?.batchId || ''"
    :run-id="selectedResource?.run_id || ''"
    :quoted-text="tutorQuotedText"
    context-type="resource_help"
    :title="selectedResource ? `${resourceShelfTypeLabel(selectedResource)} · Tutor` : '学习导引'"
    @clear-quoted-text="tutorQuotedText = ''"
  />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight, ChatDotRound, Close, EditPen, FullScreen, Reading, Refresh } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { generateApi, knowledgeApi, profileApi, resourceApi } from '../../api'
import { coursewareApi } from '../courseware/api'
import { resourceLibraryApi } from '../resource-library/api'
import { useAppStore } from '../../stores/app'
import { formatDateTime } from '../../utils/generationDisplay'
import { resourceShelfTypeLabel, sortResourcesForShelf } from '../../utils/resourceShelfOrder'
import ResourceViewer from './ResourceViewer.vue'
import PreparationWorkspace from '../../components/PreparationWorkspace.vue'
import CoursewareViewer from '../courseware/CoursewareViewer.vue'
import FocusResourceSwitcher from './FocusResourceSwitcher.vue'
import TutorDrawer from '../tutor/TutorDrawer.vue'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const selectedLearnerId = ref(route.query.learnerId || store.currentLearnerId || localStorage.getItem('last_learner_id') || '')
const selectedRunId = ref(route.query.runId || localStorage.getItem('current_generation_run_id') || '')
const selectedResourceId = ref(route.query.resourceId || '')
const resources = ref([])
const loaded = ref(false)
const loading = ref(false)
const libraryError = ref('')
let resourceListRequestVersion = 0
let resourcesMounted = true
const profiles = ref([])
const tracks = ref([])
const generationJobs = ref([])
const nodeTiers = ref({})
const resourceDetails = ref({})
let detailRequestGeneration = 0
const tutorOpen = ref(false)
const tutorQuotedText = ref('')

const activeProfile = computed(() => profiles.value.find((item) => item.learner_id === selectedLearnerId.value) || null)
const isFocusMode = computed(() => route.query.focus === '1')
const activeDirectionName = computed(() => resolveTrackName(activeProfile.value?.knowledge_base_id))
// Presentation only: describe existing data without changing task or resource selection.
const libraryPreparation = computed(() => {
  if (loading.value) return {
    title: '正在准备你的学习空间', status: '正在加载材料',
    description: '正在读取学习画像与已发布资源。材料载入后，即可选择批次开始阅读。',
  }
  if (libraryError.value) return {
    title: '学习材料暂未载入', status: '加载失败', description: libraryError.value,
  }
  if (!loaded.value) return {
    title: '准备你的学习空间', status: '材料尚未载入',
    description: '选择学习画像，读取本轮材料。若内容尚未显示，可使用上方刷新资源重新获取。',
  }
  if (!activeProfile.value) return {
    title: '让第一份材料，成为学习的起点。', status: '等待建立学习方向',
    description: '先确定学习目标并完成诊断，再生成与你的起点相匹配的材料。',
  }
  const jobs = generationJobs.value
    .filter(job => !job.learner_id || job.learner_id === selectedLearnerId.value)
    .filter(job => !job.superseded_by_run_id)
    .slice().sort((left, right) => String(right.created_at || '').localeCompare(String(left.created_at || '')))
  const pendingJob = jobs.find(job => ['queued', 'running'].includes(job.job_status))
  if (pendingJob) return {
    title: '本轮学习材料正在准备中', status: pendingJob.job_status === 'queued' ? '生成任务排队中' : '生成任务进行中',
    description: '当前尚无已发布的可读材料。可在资源生成页查看实际进展，发布后刷新这里开始学习。',
  }
  if (jobs[0]?.job_status === 'failed') return {
    title: '本轮材料尚未就绪', status: '生成任务未完成',
    description: '当前还没有可读的发布结果。前往资源生成页查看原因，处理后再继续学习。',
  }
  return {
    title: '把你的下一步，交给清晰的学习材料。', status: '暂无已发布材料',
    description: jobs.length ? '该学习画像下暂时没有可阅读的资源，可前往生成页查看发布结果或刷新资源。' : '当前方向还没有可阅读的材料。生成一批资源，讲义与实操内容就会归档到这里。',
  }
})
// End presentation-only preparation state.
const visibleResources = computed(() => {
  const supersededRunIds = new Set(
    generationJobs.value.filter((job) => job.superseded_by_run_id).map((job) => job.run_id),
  )
  const publishedTypesByRun = new Map()
  for (const resource of resources.value) {
    if (!publishedTypesByRun.has(resource.run_id)) publishedTypesByRun.set(resource.run_id, new Set())
    publishedTypesByRun.get(resource.run_id).add(resource.resource_type)
  }
  const latestReplacementRunByType = new Map()
  for (const job of generationJobs.value) {
    if (job.superseded_by_run_id) continue
    const batchId = job.batch_id || job.run_id
    const requestedTypes = new Set(job.request_payload?.resource_types || [])
    // A continuation can inherit stale replacement metadata from its source
    // request. It must only replace types that this Run actually generated;
    // otherwise a later checklist/case Run can hide an already-published test.
    const types = (job.request_payload?.constraints?.replacement_resource_types || [])
      .filter((type) => (
        requestedTypes.has(type)
        && publishedTypesByRun.get(job.run_id)?.has(type)
      ))
    for (const type of types) {
      const key = `${batchId}:${type}`
      const current = latestReplacementRunByType.get(key)
      if (!current || String(current.created_at || '') < String(job.created_at || '')) {
        latestReplacementRunByType.set(key, job)
      }
    }
  }
  // A full-batch regeneration replaces the source run. Keep its workflow
  // history, but never mix its published artifacts into the current batch.
  return resources.value.filter((resource) => {
    if (supersededRunIds.has(resource.run_id)) return false
    const batchId = resource.batch_id || resource.run_id
    const replacement = latestReplacementRunByType.get(`${batchId}:${resource.resource_type}`)
    return !replacement || resource.run_id === replacement.run_id
  })
})
const profileOptions = computed(() => profiles.value.map((profile) => ({
  ...profile,
  label: `${resolveTrackName(profile.knowledge_base_id)} / ${profile.skill_level || '未分级'}`,
})))

function resolveTrackName(trackId) {
  return tracks.value.find((item) => item.track_id === trackId)?.name || trackId || '未命名方向'
}

const taskGroups = computed(() => {
  // Historical correction packages used their own run as batch_id.  Group
  // them with the source learning resources while their persisted batch is
  // being corrected by newly generated data.
  const effectiveBatchByRunId = new Map()
  for (const job of generationJobs.value) {
    const correctionSourceRunId = job.request_payload?.constraints?.correction_focus_snapshot?.source_run_id
    if (!correctionSourceRunId) continue
    const sourceJob = generationJobs.value.find((candidate) => candidate.run_id === correctionSourceRunId)
    effectiveBatchByRunId.set(job.run_id, sourceJob?.batch_id || sourceJob?.run_id || correctionSourceRunId)
  }
  const groups = new Map()
  for (const resource of visibleResources.value) {
    const batchId = effectiveBatchByRunId.get(resource.run_id) || resource.batch_id || resource.run_id || `resource:${resource.resource_id}`
    if (!groups.has(batchId)) groups.set(batchId, { runId: batchId, batchId, shortRunId: batchId.startsWith('resource:') ? '独立资源' : batchId.slice(0, 8).toUpperCase(), resources: [] })
    groups.get(batchId).resources.push(resource)
  }
  return Array.from(groups.values())
    .sort((left, right) => String(left.resources[0]?.created_at || '').localeCompare(String(right.resources[0]?.created_at || '')))
    .map((task, taskIndex) => {
    const timestamp = task.resources[0]?.created_at || task.resources[0]?.updated_at
    const batchLabel = `资源批次 ${String(taskIndex + 1).padStart(2, '0')}`
    return { ...task, batchLabel, label: `${batchLabel} · ${task.resources.length} 份资源 · ${formatDateTime(timestamp)}` }
  })
})
const activeTask = computed(() => taskGroups.value.find((item) => item.runId === selectedRunId.value) || taskGroups.value[0] || null)
const activeResources = computed(() => sortResourcesForShelf(activeTask.value?.resources || []))
const selectedResource = computed(() => {
  const resource = activeResources.value.find(
    (item) => item.resource_id === selectedResourceId.value,
  ) || activeResources.value[0] || null
  if (!resource?.resource_id) return resource
  return resourceDetails.value[resource.resource_id] || resource
})
const activeResourceIndex = computed(() => {
  const index = activeResources.value.findIndex((item) => item.resource_id === selectedResource.value?.resource_id)
  return index < 0 ? 0 : index + 1
})
const resourceProgress = computed(() => `第 ${String(activeResourceIndex.value).padStart(2, '0')} 份 / 共 ${String(activeResources.value.length).padStart(2, '0')} 份`)

function knowledgePointSummary(resource) {
  const points = resource.knowledge_points || []
  if (!points.length) return '核心知识学习'
  return points.length === 1 ? points[0] : `${points[0]} 等 ${points.length} 个知识点`
}

function syncSelectedRun() {
  if (!taskGroups.value.length) { selectedRunId.value = ''; return }
  if (selectedRunId.value && taskGroups.value.some((item) => item.runId === selectedRunId.value)) return
  const currentRunId = localStorage.getItem('current_generation_run_id') || ''
  const currentResource = visibleResources.value.find((item) => item.run_id === currentRunId)
  const currentBatchId = currentResource?.batch_id || currentResource?.run_id || currentRunId
  selectedRunId.value = taskGroups.value.some((item) => item.runId === currentBatchId)
    ? currentBatchId
    : taskGroups.value[0].runId
}

function syncSelectedResource() {
  if (!activeResources.value.some((item) => item.resource_id === selectedResourceId.value)) selectedResourceId.value = activeResources.value[0]?.resource_id || ''
}

async function loadSelectedResourceDetail() {
  const resourceId = selectedResourceId.value || activeResources.value[0]?.resource_id
  const learnerId = selectedLearnerId.value
  const selected = selectedResource.value
  detailRequestGeneration += 1
  const generation = detailRequestGeneration
  const isCurrent = () => resourcesMounted && generation === detailRequestGeneration && learnerId === selectedLearnerId.value
  if (!resourceId || resourceDetails.value[resourceId]) return
  try {
    const response = selected?.resource_kind === 'interactive_courseware'
      ? await coursewareApi.get(resourceId)
      : await resourceApi.get(resourceId)
    if (!isCurrent()) return
    const detail = response.data?.resource || response.data?.item || response.data
    if (detail?.resource_id === resourceId) {
      // The courseware detail endpoint intentionally exposes only the
      // courseware contract. Keep the library discriminator so a loaded
      // detail is still rendered by CoursewareViewer rather than Markdown.
      resourceDetails.value = {
        ...resourceDetails.value,
        [resourceId]: { ...selected, ...detail },
      }
    }
  } catch (error) {
    if (!isCurrent()) return
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || error?.response?.data?.message || '资源正文加载失败')
  }
}

function resourceTierLabel(resource) {
  const tiers = [...new Set((resource?.knowledge_points || [])
    .map((point) => nodeTiers.value[String(point || '').trim()])
    .filter((tier) => Number.isInteger(tier)))]
  return tiers.length ? tiers.map((tier) => `第 ${tier} 阶`).join('、') : ''
}

function openCoursewareGeneration() {
  router.push({
    path: '/generate',
    query: {
      learnerId: selectedLearnerId.value || undefined,
      runId: activeTask.value?.batchId || undefined,
    },
  })
}

function goToFeedback() {
  const batchId = activeTask.value?.batchId || activeTask.value?.runId
  if (!selectedLearnerId.value || !batchId) return
  router.push({ path: '/feedback', query: { learnerId: selectedLearnerId.value, batchId } })
}

function askTutorAboutSelection(selectedText) {
  tutorQuotedText.value = selectedText
  tutorOpen.value = true
}

function openTutor() {
  tutorQuotedText.value = ''
  tutorOpen.value = true
}

function handleRunChange(value) {
  if (value && !value.startsWith('resource:')) localStorage.setItem('current_generation_run_id', value)
  router.replace({ query: { ...route.query, runId: value || undefined, resourceId: undefined } })
  syncSelectedResource()
}

function enterFocusMode() {
  router.replace({ query: { ...route.query, focus: '1' } })
}

function exitFocusMode() {
  const query = { ...route.query }
  delete query.focus
  router.replace({ query })
}

function syncProfileContext() {
  const profile = activeProfile.value
  if (!profile) return
  store.resumeProfile(profile, profile.knowledge_base_id, resolveTrackName(profile.knowledge_base_id))
  localStorage.setItem('last_learner_id', profile.learner_id)
}

async function loadProfiles() {
  const [profileRes, domainRes] = await Promise.all([profileApi.list({ page: 1, page_size: 50 }), knowledgeApi.listDomains()])
  if (!resourcesMounted) return
  profiles.value = profileRes.data.items || profileRes.data.profiles || []
  tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
  if (!profiles.value.length) { selectedLearnerId.value = ''; return }
  if (!profiles.value.some((item) => item.learner_id === selectedLearnerId.value)) selectedLearnerId.value = profiles.value[0].learner_id
  syncProfileContext()
}

async function loadResources() {
  const version = ++resourceListRequestVersion
  const learnerId = selectedLearnerId.value
  const knowledgeBaseId = activeProfile.value?.knowledge_base_id
  const isCurrent = () => resourcesMounted && version === resourceListRequestVersion && selectedLearnerId.value === learnerId
  if (!learnerId || !resourcesMounted) {
    resources.value = []; loaded.value = true; selectedRunId.value = ''; selectedResourceId.value = ''
    return
  }
  loading.value = true
  libraryError.value = ''
  try {
    let tiers = {}
    if (knowledgeBaseId) {
      try {
        const nodesRes = await knowledgeApi.listNodes(knowledgeBaseId)
        if (!isCurrent()) return
        tiers = Object.fromEntries((nodesRes.data?.nodes || nodesRes.data || [])
          .map((node) => [node.node_id, node.tier])
          .filter(([, tier]) => Number.isInteger(tier)))
      } catch (error) {
        if (!isCurrent()) return
        console.warn('学习节点阶级加载失败，标题将隐藏阶级信息', error)
      }
    }
    if (!isCurrent()) return
    const [res, jobsRes] = await Promise.all([
      resourceLibraryApi.listByLearner(learnerId),
      generateApi.listJobs(learnerId),
    ])
    if (!isCurrent()) return
    if ((res.data || []).some((item) => item.learner_id && item.learner_id !== learnerId)) throw new Error('学习材料与当前画像不一致，请重新加载')
    nodeTiers.value = tiers
    detailRequestGeneration += 1
    resourceDetails.value = {}
    resources.value = (res.data || []).map((item) => ({
      ...item,
      resource_id: item.id,
      created_at: item.created_at || item.published_at,
      tier_label: resourceTierLabel(item),
    }))
    generationJobs.value = jobsRes.data.items || []
    loaded.value = true
    syncSelectedRun()
    syncSelectedResource()
    await loadSelectedResourceDetail()
  } catch (error) {
    if (!isCurrent()) return
    libraryError.value = error?.response?.data?.message || error?.message || '资源加载失败'
    loaded.value = true
    ElMessage.error(libraryError.value)
  } finally {
    if (isCurrent()) loading.value = false
  }
}

async function handleProfileChange() {
  syncProfileContext()
  ++detailRequestGeneration
  resources.value = []
  generationJobs.value = []
  resourceDetails.value = {}
  nodeTiers.value = {}
  loaded.value = false
  selectedRunId.value = ''
  selectedResourceId.value = ''
  await loadResources()
}

async function retryResources() {
  try {
    if (!profiles.value.length) await loadProfiles()
    await loadResources()
  } catch (error) {
    if (resourcesMounted) libraryError.value = error?.response?.data?.message || '学习画像加载失败，请重试'
  }
}

watch(activeTask, () => {
  syncSelectedResource()
  void loadSelectedResourceDetail()
})
watch(selectedResourceId, () => {
  tutorQuotedText.value = ''
  void loadSelectedResourceDetail()
  if (selectedResourceId.value && route.query.resourceId !== selectedResourceId.value) {
    router.replace({ query: { ...route.query, resourceId: selectedResourceId.value } })
  }
})
onMounted(async () => {
  try {
    await loadProfiles()
    if (resourcesMounted) await loadResources()
  } catch (error) {
    if (!resourcesMounted) return
    libraryError.value = error?.response?.data?.message || '学习画像加载失败，请刷新页面重试'
    loaded.value = true
  }
})
onBeforeUnmount(() => { resourcesMounted = false; ++resourceListRequestVersion; ++detailRequestGeneration })
</script>

<style scoped>
/* The existing toolbar, resource shelf and full-width reader keep their layout. */
.resources-layout {
  --learn-ink: #132c40;
  --learn-muted: #536b7d;
  --learn-navy: #11283c;
  --learn-teal: #086575;
  --learn-mint: #9cecdf;
  --learn-line: #d9e4eb;
  --learn-paper: #f5f7fa;
  --rag-ink: var(--learn-ink);
  --rag-line: var(--learn-line);
  --rag-surface-alt: #f8fafb;
  --rag-blue-700: var(--learn-navy);
  --rag-blue-800: #1d4055;
  --rag-blue-500: #187487;
  --rag-blue-50: #edf6f7;
  --rag-radius: 6px;
  --rag-shadow-soft: 0 4px 16px rgb(17 40 60 / 3%);
  min-height: 0;
  color: var(--learn-ink);
}

/* This route owns its shell colours; the existing header placement is retained. */
:global(.app-shell:has(.resources-layout)) {
  --rag-line: #d9e4eb;
  --rag-line-strong: #c5d5df;
  --rag-blue-700: #11283c;
  --rag-blue-800: #1d4055;
  --rag-blue-500: #187487;
  --rag-blue-50: #edf6f7;
  background: #f5f7fa;
}
:global(.app-shell:has(.resources-layout) .topbar-kicker) { color: #086575; font: 11px/1.5 Consolas, 'SFMono-Regular', monospace; }
:global(.app-shell:has(.resources-layout) .topbar h1) { color: #132c40; font-weight: 700; }
:global(.app-shell:has(.resources-layout) .topbar p) { color: #536b7d; }
:global(.app-shell:has(.resources-layout) .topbar-action) { min-height: 44px; border-radius: 5px; font-size: 12px; font-weight: 600; }
:global(.app-shell:has(.resources-layout) .topbar-meta > div) { background: transparent; box-shadow: none; }
:global(.app-shell:has(.resources-layout) .topbar-meta span) { color: #536b7d; }
:global(.app-shell:has(.resources-layout) .topbar-meta strong) { color: #132c40; }

.resources-page { display: flex; flex-direction: column; gap: 12px; width: 100%; max-width: none; min-height: 0; margin: 0 auto; align-self: stretch; padding-top: 20px; padding-bottom: 0; }
.learning-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) max-content; gap: 18px; align-items: end; padding: 15px 18px; border: 1px solid var(--learn-line); border-top: 2px solid var(--learn-navy); }
.toolbar-fields { display: grid; min-width: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.field-label { display: flex; min-width: 0; flex-direction: column; gap: 5px; color: var(--learn-muted); font-size: 12px; font-weight: 500; }
.field-caption { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.field-caption small { flex-shrink: 0; font: 11px/1.5 Consolas, 'SFMono-Regular', monospace; }
.field-label :deep(.el-select) { width: 100%; min-width: 0; }
.field-label :deep(.el-select__wrapper) { min-height: 44px; padding-inline: 12px; background: #fff; box-shadow: 0 0 0 1px #cbdbe4 inset; transition: box-shadow .18s ease, background-color .18s ease; }
.field-label :deep(.el-select__wrapper:hover) { box-shadow: 0 0 0 1px #7099a7 inset; }
.field-label :deep(.el-select__wrapper.is-focused) { box-shadow: 0 0 0 2px var(--learn-teal) inset; }
.field-label :deep(.el-select__selected-item) { min-width: 0; max-width: 100%; color: var(--learn-ink); font-size: 13px; font-weight: 500; }
.field-label :deep(.el-select__selection) { min-width: 0; }
.toolbar-actions { display: flex; align-items: center; justify-content: flex-end; min-width: max-content; gap: 8px; white-space: nowrap; }
.courseware-button, .refresh-button, .focus-button { height: 44px; min-height: 44px; margin: 0; border: 1px solid #b9cdd8; border-radius: 5px; background: #fff; color: var(--learn-ink); font-size: 12px; font-weight: 600; transition: border-color .18s ease, background-color .18s ease, color .18s ease; }
.courseware-button { padding: 0 14px; }
.refresh-button, .focus-button { width: 44px; padding: 0; }
.focus-button { border-color: #a7cfd0; background: #edf7f6; color: var(--learn-teal); }
.courseware-button:hover, .refresh-button:hover, .focus-button:hover { border-color: var(--learn-teal); background: #e8f3f4; color: var(--learn-teal); }

.learning-workspace { display: flex; flex-direction: column; gap: 0; width: 100%; min-height: 0; flex: 1; }
.resource-shelf { position: static; display: flex; align-items: center; gap: 8px; width: 100%; max-height: none; padding: 10px 12px; border: 1px solid var(--learn-line); border-radius: 6px 6px 0 0 !important; background: #fff; box-shadow: none !important; overflow-x: auto; overflow-y: hidden; scrollbar-width: thin; scrollbar-color: #9ab6c2 #edf3f6; }
.shelf-heading { display: flex; flex: 0 0 156px; align-items: center; justify-content: space-between; padding: 0 6px; }
.eyebrow { display: block; color: var(--learn-muted) !important; font: 10px/1.5 Consolas, 'SFMono-Regular', monospace; text-transform: uppercase; }
.shelf-heading h3 { margin: 5px 0 0; font-size: 17px; font-weight: 650; line-height: 1.5; }
.shelf-count { display: grid; min-width: 28px; height: 28px; place-items: center; border: 1px solid #c6dfe0; border-radius: 4px; background: #edf7f6; color: var(--learn-teal); font: 600 12px/1 Consolas, monospace; }
.resource-item { display: grid; grid-template-columns: 30px minmax(0, 1fr) 14px; flex: 0 0 clamp(158px, 15vw, 208px); width: auto; min-height: 54px; gap: 10px; align-items: center; padding: 8px 7px; border: 1px solid var(--learn-line); border-radius: 5px; background: #fff; color: var(--learn-ink); cursor: pointer; text-align: left; transition: border-color .18s ease; }
.resource-item:hover { border-color: #8bb6bf !important; background: #f1f7f8 !important; box-shadow: none !important; }
.resource-item.is-active { border-color: #8bbfbe !important; background: #edf8f6 !important; box-shadow: inset 3px 0 #167c7c !important; color: var(--learn-ink); }
.resource-order { display: grid; width: 26px; height: 26px; place-items: center; border: 1px solid #dde7ed; border-radius: 4px; background: #f0f4f7; color: var(--learn-muted); font: 500 11px/1 Consolas, monospace; }
.resource-item.is-active .resource-order { border-color: #aadbd5; background: #c4eee6; color: #125c67; }
.resource-item-copy { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.resource-item-copy strong, .resource-item-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.resource-item-copy strong { color: var(--learn-ink); font-size: 13px; font-weight: 650; }
.resource-item-copy small { color: var(--learn-muted); font-size: 11px; line-height: 1.4; }
.resource-item.is-active .resource-item-copy strong { color: #164754; }
.resource-item.is-active .resource-item-copy small { color: #456c78; }
.resource-arrow { color: #537a8b; font-size: 14px; }
.resource-item.is-active .resource-arrow { color: var(--learn-teal); }
.resource-feedback-button { flex: 0 0 auto; min-width: 110px; height: 54px; margin: 0 0 0 4px; padding: 0 16px; border: 1px solid #86d3c8; border-radius: 5px; background: var(--learn-mint); color: var(--learn-navy); font-size: 13px; font-weight: 650; box-shadow: none; transition: background-color .18s ease, border-color .18s ease; }
.resource-feedback-button:hover { border-color: #56b5aa; background: #c1f3eb; color: var(--learn-navy); }
.shelf-footnote { display: none; }
.reading-stage { width: 100%; min-width: 0; min-height: 0; align-self: stretch; }

.reading-stage :deep(.reader-card) { width: 100%; min-height: 0; border-color: var(--learn-line); border-top: 0; border-radius: 0 0 6px 6px; background: #fff; box-shadow: 0 6px 22px rgb(17 40 60 / 3%); }
.reading-stage :deep(.reader-header) { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 16px; min-height: 68px; padding: 12px 24px; border-bottom: 1px solid var(--learn-line); background: #f8fbfc; }
.reading-stage :deep(.reader-title-wrap) { min-width: 0; }
.reading-stage :deep(.reader-context-title) { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; min-width: 0; }
.reading-stage :deep(.learning-status) { color: var(--learn-teal); font-size: 12px; font-weight: 500; }
.reading-stage :deep(.learning-status i) { background: #197b78; box-shadow: 0 0 0 3px #e1f1ef; }
.reading-stage :deep(.resource-kicker) { max-width: none; min-width: 0; padding-left: 10px; border-color: #cedee4; overflow: visible; color: var(--learn-ink); font-size: 14px; font-weight: 650; line-height: 1.5; white-space: normal; overflow-wrap: anywhere; text-overflow: clip; }
.reading-stage :deep(.reader-actions) { display: flex; grid-column: 2; justify-self: end; align-items: center; justify-content: flex-end; flex-wrap: wrap; min-width: 0; max-width: 100%; gap: 8px; }
.reading-stage :deep(.learning-progress) { color: var(--learn-muted); font: 11px/1.5 Consolas, 'Microsoft YaHei', monospace; }
.reading-stage :deep(.reader-actions .el-tag) { height: auto; min-height: 28px; padding: 4px 9px; border-radius: 4px; font-size: 11px; line-height: 1.5; font-weight: 600; }
.reading-stage :deep(.el-tag--success) { border-color: #badfd5; background: #f0f8f5; color: #166952; }
.reading-stage :deep(.el-tag--warning) { border-color: #e7d7b8; background: #fcf7ec; color: #8b4c08; }
.reading-stage :deep(.el-tag--danger) { border-color: #edc6c6; background: #fff4f3; color: #a03235; }
.reading-stage :deep(.download-button), .tutor-trigger { min-height: 44px; height: 44px; margin: 0; padding: 0 13px; border: 1px solid #b9cdd8; border-radius: 5px; background: #fff; color: var(--learn-ink); font-size: 12px; font-weight: 600; box-shadow: none; transition: border-color .18s ease, background-color .18s ease, color .18s ease; }
.reading-stage :deep(.download-button:hover) { border-color: var(--learn-teal); background: #edf6f7; color: var(--learn-teal); }
.tutor-trigger { border-color: var(--learn-navy); background: var(--learn-navy); color: #fff; }
.tutor-trigger :deep(.el-icon) { margin-right: 2px; font-size: 15px; }
.tutor-trigger:hover { border-color: #224e62; background: #224e62; color: var(--learn-mint); }
.reading-stage :deep(.reader-content) { padding: 32px 40px 18px; }
.reading-stage :deep(.content-label) { gap: 9px; margin-bottom: 21px; color: var(--learn-teal); font-size: 12px; font-weight: 600; }
.reading-stage :deep(.content-label span) { width: 3px; height: 16px; border-radius: 1px; background: #0d7580; }
.reading-stage :deep(.resource-content) { color: #334c60; font-size: 16px; line-height: 1.85; overflow-wrap: anywhere; }
.reading-stage :deep(.resource-content h1), .reading-stage :deep(.resource-content h2), .reading-stage :deep(.resource-content h3), .reading-stage :deep(.resource-content h4) { color: var(--learn-ink); font-weight: 700; line-height: 1.5; }
.reading-stage :deep(.resource-content h1) { font-size: clamp(24px, 2vw, 30px); margin-top: 22px; margin-bottom: 24px; }
.reading-stage :deep(.resource-content h2) { margin-top: 30px; padding-bottom: 10px; border-bottom: 1px solid #e4edf1; font-size: 23px; }
.reading-stage :deep(.resource-content h3) { font-size: 19px; }
.reading-stage :deep(.resource-content h4) { font-size: 17px; }
.reading-stage :deep(.resource-content strong) { color: var(--learn-ink); font-weight: 650; }
.reading-stage :deep(.resource-content li::marker) { color: var(--learn-teal); }
.reading-stage :deep(.resource-content code) { border: 1px solid #d7e8eb; border-radius: 3px; background: #f0f6f7; color: #095b6c; }
.reading-stage :deep(.resource-content pre) { border: 1px solid #244b5e; border-radius: 5px; background: var(--learn-navy); color: #dceef4; }
.reading-stage :deep(.resource-content pre code) { border: 0; background: transparent; color: inherit; }
.reading-stage :deep(.resource-content blockquote) { margin: 18px 0; padding: 14px 18px; border-left: 3px solid #69bcb8; background: #f2f8f8; color: #3b6273; }
.reading-stage :deep(.resource-content a) { color: var(--learn-teal); text-decoration: underline; text-underline-offset: 3px; }
.reading-stage :deep(.reader-footer) { border-color: var(--learn-line); background: #f8fafb; }
.reading-stage :deep(.knowledge-tags > span) { color: var(--learn-muted); }
.reading-stage :deep(.knowledge-tags em) { border: 1px solid #d3e5e7; border-radius: 4px; background: #eef6f6; color: var(--learn-teal); }
.reading-stage :deep(.source-collapse .el-collapse-item__header) { min-height: 44px; height: auto; color: var(--learn-muted); }
.reading-stage :deep(.selection-question-popover) { min-height: 44px; border-color: var(--learn-navy); border-radius: 5px; background: var(--learn-navy); color: #fff; }
.reading-stage :deep(.selection-question-popover:hover) { border-color: #224e62; background: #224e62; }
.library-loading-note { color: var(--learn-muted); font-size: 12px; line-height: 1.7; }
@media (min-width: 1100px) and (min-height: 720px) {
  .library-empty { min-height: calc(100dvh - 212px); }
}

/* Tutor keeps its original drawer/embedded placement and adopts this page's palette. */
.resources-layout :deep(.tutor-panel) { border-color: var(--learn-line); background: #f8fafb; }
.resources-layout :deep(.tutor-panel-header) { border-color: #2b465a; background: var(--learn-navy); }
.resources-layout :deep(.tutor-heading span) { color: var(--learn-mint); }
.resources-layout :deep(.tutor-heading strong) { color: #fff; }
.resources-layout :deep(.tutor-heading small) { color: #bed6e1; }
.resources-layout :deep(.tutor-close) { width: 44px; height: 44px; border-color: #4b6a7b; border-radius: 5px; background: transparent; color: #e0eef2; }
.resources-layout :deep(.tutor-close:hover) { border-color: #9cecdf; background: #24485b; color: #9cecdf; }
.resources-layout :deep(.tutor-welcome) { border-color: var(--learn-line); border-radius: 6px; background: #fff; box-shadow: none; }
.resources-layout :deep(.welcome-mark) { border-radius: 5px; background: var(--learn-navy); color: var(--learn-mint); box-shadow: none; }
.resources-layout :deep(.welcome-eyebrow) { color: var(--learn-teal); }
.resources-layout :deep(.starter-prompts button) { min-height: 54px; border-color: var(--learn-line); border-radius: 5px; background: #f8fafb; }
.resources-layout :deep(.starter-prompts button:hover) { border-color: #6aa7b0; background: #edf6f7; box-shadow: none; }
.resources-layout :deep(.starter-prompts button small) { color: var(--learn-muted); }
.resources-layout :deep(.composer-editor) { border-radius: 6px; background: #f8fafb; }
.resources-layout :deep(.composer-actions) { border-color: var(--learn-line); background: #edf5f6; }
.resources-layout :deep(.composer-send:not(.is-disabled)) { border-radius: 5px; background: var(--learn-navy); color: #fff; box-shadow: none; }
.resources-layout :deep(.composer-send:not(.is-disabled):hover) { background: #224e62; color: var(--learn-mint); box-shadow: none; transform: none; }

/* Focus mode uses the same materials and buttons without changing its scroll model. */
.resources-page.is-focus-mode { min-height: 100dvh; height: 100dvh; gap: 0; padding: 0; overflow-y: auto; background: var(--learn-paper); }
.is-focus-mode .learning-toolbar, .is-focus-mode .resource-shelf { display: none; }
.is-focus-mode .learning-workspace, .is-focus-mode .reading-stage { flex: 1; min-height: calc(100dvh - 24px); }
.is-focus-mode .reading-stage :deep(.reader-card) { width: 100%; min-height: calc(100dvh - 24px); }
.reading-stage :deep(.focus-resource-switcher) { border-color: var(--learn-line); border-radius: 0; background: #f8fafb; }
.reading-stage :deep(.focus-resource-switcher button) { border-color: var(--learn-line); border-radius: 5px; color: var(--learn-ink); transition: border-color .18s ease; }
.reading-stage :deep(.focus-resource-switcher button:hover) { background: #edf6f7; }
.reading-stage :deep(.focus-resource-switcher button.is-active) { border-color: #8bbfbe; background: #edf8f6; color: #164754; box-shadow: inset 3px 0 #167c7c; }
.reading-stage :deep(.focus-resource-switcher button span) { border-radius: 4px; color: var(--learn-muted); }
.reading-stage :deep(.focus-resource-switcher button.is-active span) { background: #c4eee6; color: #125c67; }
.reading-stage :deep(.focus-resource-switcher button small) { color: var(--learn-muted); }
.reading-stage :deep(.focus-resource-switcher button.is-active small) { color: #456c78; }
.reading-stage :deep(.focus-resource-switcher button.is-active i) { color: var(--learn-teal); }
.focus-exit { position: fixed; right: 20px; bottom: 20px; z-index: 20; width: 44px; height: 44px; margin: 0; border-color: #416b7b; background: var(--learn-navy); color: #fff; box-shadow: 0 4px 16px rgb(17 40 60 / 16%); }
.focus-exit:hover { border-color: #578c94; background: #224e62; color: var(--learn-mint); }
.resources-layout :deep(:is(button, a, summary):focus-visible) { outline: 3px solid #16758a; outline-offset: 3px; }
:global(.app-shell:has(.resources-layout) .topbar button:focus-visible) { outline: 3px solid #16758a; outline-offset: 3px; }

@media (min-width: 1101px) {
  .resources-layout.has-tutor-panel.is-focus-mode { display: flex; align-items: stretch; gap: 0; }
  .resources-layout.has-tutor-panel.is-focus-mode .resources-page { flex: 1 1 0; min-width: 0; margin: 0; }
  .resources-layout.has-tutor-panel.is-focus-mode .reading-stage :deep(.reader-header) { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .resources-layout.has-tutor-panel.is-focus-mode .reading-stage :deep(.reader-actions) { grid-column: 1; }
  .resources-layout.is-focus-mode { min-height: 100dvh; height: 100dvh; }
  .resources-layout.is-focus-mode .resources-page { flex: 1 1 0; min-width: 0; }
}
@media (max-width: 760px) {
  .resources-page { min-height: auto; padding-top: 16px; }
  .learning-toolbar { grid-template-columns: minmax(0, 1fr); padding: 12px; gap: 12px; }
  .toolbar-fields { grid-template-columns: 1fr; }
  .toolbar-actions { min-width: 0; flex-wrap: wrap; white-space: normal; }
  .resource-shelf { align-items: stretch; }
  .shelf-heading { flex-basis: 132px; }
  .resource-item { flex-basis: 158px; }
  .reading-stage :deep(.reader-header) { grid-template-columns: minmax(0, 1fr); gap: 10px; padding: 12px 16px; }
  .reading-stage :deep(.reader-actions) { grid-column: 1; justify-self: stretch; }
  .reading-stage :deep(.reader-content), .reading-stage :deep(.reader-footer) { padding-left: 23px; padding-right: 23px; }
  .reading-stage :deep(.reader-card) { min-height: auto; }
  .resources-page.is-focus-mode { padding: 0; }
  .is-focus-mode .learning-workspace, .is-focus-mode .reading-stage, .is-focus-mode .reading-stage :deep(.reader-card) { min-height: 100dvh; }
  .focus-exit { right: 14px; bottom: 14px; }
}
@media (max-width: 600px) {
  /* Collapsed desktop selectors must not squeeze the five mobile navigation icons. */
  :global(.app-shell:has(.resources-layout) .sidebar .sidebar-inner) { grid-template-columns: minmax(0, 1fr) 44px 44px; grid-template-rows: auto; gap: 4px; padding: 7px 8px; }
  :global(.app-shell:has(.resources-layout) .sidebar .brand-block) { display: none; }
  :global(.app-shell:has(.resources-layout) .sidebar .nav-text) { display: none; }
  :global(.app-shell:has(.resources-layout) .sidebar .nav-list) { grid-template-columns: repeat(5, minmax(0, 1fr)); grid-template-rows: auto; gap: 2px; }
  :global(.app-shell:has(.resources-layout) .sidebar .nav-item) { width: auto; min-width: 0; min-height: 44px; padding: 6px 4px; }
  :global(.app-shell:has(.resources-layout) .sidebar .sidebar-toggle), :global(.app-shell:has(.resources-layout) .sidebar .logout-button) { width: 44px; min-width: 44px; }
}
@media (prefers-reduced-motion: reduce) {
  .resources-layout *, .resources-layout :deep(*) { transition: none !important; animation: none !important; }
}
</style>
