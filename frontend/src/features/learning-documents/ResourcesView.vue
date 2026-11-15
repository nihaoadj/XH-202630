<template>
  <div class="resources-layout" :class="{ 'has-tutor-panel': tutorOpen, 'is-focus-mode': isFocusMode }">
    <div class="resources-page" :class="{ 'is-focus-mode': isFocusMode }">
    <header class="learning-toolbar workspace-filter-surface">
      <div class="toolbar-fields">
        <label class="field-label">
          <span class="field-caption">学习画像<small aria-hidden="true">PROFILE</small></span>
          <el-select v-model="selectedLearnerId" filterable placeholder="选择学习画像" class="workspace-glass-select" popper-class="refined-select-dropdown" @change="handleProfileChange">
            <el-option v-for="item in profileOptions" :key="item.learner_id" :label="item.label" :value="item.learner_id" />
          </el-select>
        </label>
        <label class="field-label">
          <span class="field-caption">资源批次<small aria-hidden="true">BATCH</small></span>
          <el-select v-model="selectedRunId" filterable :disabled="!taskGroups.length" placeholder="选择资源批次" class="workspace-glass-select" popper-class="refined-select-dropdown" @change="handleRunChange">
            <template #label="{ label }">
              <span>
                <strong v-if="activeTask?.nodeTitle" class="batch-node-name">{{ activeTask.nodeTitle }}</strong>{{ activeTask?.nodeTitle ? ' ｜ ' + activeTask.batchMeta : label }}
              </span>
            </template>
            <el-option v-for="task in taskGroups" :key="task.runId" :label="task.label" :value="task.runId">
              <strong v-if="task.nodeTitle" class="batch-node-name">{{ task.nodeTitle }}</strong>{{ task.nodeTitle ? ' ｜ ' + task.batchMeta : task.batchMeta }}
            </el-option>
          </el-select>
        </label>
      </div>
      <div v-if="activeTask" class="toolbar-actions">
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
          <button v-for="(resource, index) in activeResources" :key="resource.resource_id" type="button" class="resource-item" :class="{ 'is-active': resource.resource_id === selectedResourceId }" :aria-pressed="resource.resource_id === selectedResourceId" @click="selectedResourceId = resource.resource_id">
            <span class="resource-order">{{ String(index + 1).padStart(2, '0') }}</span>
            <span class="resource-item-copy" :title="resource.study_context_title"><strong>{{ resourceShelfTypeLabel(resource) }}<span class="resource-study-marker">{{ resource.study_marker }}</span></strong><small>{{ resource.difficulty || '待分级' }} · {{ knowledgePointSummary(resource) }}</small></span>
            <span class="resource-arrow" aria-hidden="true">→</span>
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
          >
            <template #actions>
              <el-button class="resource-feedback-button" @click="goToFeedback">反馈测评</el-button>
            </template>
          </FocusResourceSwitcher>
          <CoursewareViewer v-if="selectedResource?.resource_kind === 'interactive_courseware'" :resource="selectedResource" :focus-mode="isFocusMode" />
          <ResourceViewer
            v-else-if="selectedResource"
            :resources="[selectedResource]"
            :progress-label="resourceProgress"
            :resource-choices="[]"
            @ask-tutor="askTutorAboutSelection"
          >
            <template #header-end-actions>
              <el-button ref="tutorTriggerRef" class="tutor-trigger" @click="openTutor">
                <el-icon><TutorMark /></el-icon>
                <span>Tutor</span>
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
        { icon: TutorMark, eyebrow: '03 / REFLECTION', title: '提问与复盘', description: '向 Tutor 追问难点，用真实反馈调整下一轮重点。', detail: 'Tutor 问答 · 学习反馈' },
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
        <span v-else class="library-loading-note">正在读取学习材料…</span>
      </template>
    </PreparationWorkspace>

    <el-tooltip v-if="isFocusMode" content="退出专注学习模式" placement="left">
      <el-button class="focus-exit" :icon="Close" circle aria-label="退出专注学习模式" @click="exitFocusMode" />
    </el-tooltip>

    </div>
    <Teleport to="body">
      <button
        v-if="selectedResource && selectedResource.resource_kind !== 'interactive_courseware' && !tutorTriggerVisible && !tutorOpen"
        type="button"
        class="tutor-floating-trigger"
        :style="{ top: `${tutorFloatingTop}px` }"
        aria-label="向 Tutor 提问"
        title="向 Tutor 提问"
        @click="openTutor"
      >
        <TutorMark />
      </button>
    </Teleport>
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
import { currentProfileRating } from '../../utils/profileRating.js'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight, Close, EditPen, FullScreen, Reading } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { generateApi } from '../generation/api.js'
import { knowledgeApi } from '../knowledge/api.js'
import { profileApi } from '../learners/api.js'
import { resourceApi } from './api.js'
import { coursewareApi } from '../courseware/api'
import { resourceLibraryApi } from '../resource-library/api'
import { useAppStore } from '../../stores/app'
import { formatDateTime } from '../../utils/generationDisplay'
import { resourceShelfTypeLabel, sortResourcesForShelf } from '../../utils/resourceShelfOrder'
import { resourceFeedbackLocation, resourceStudyContext, resourceStudyMarker } from '../../utils/resourceStudyContext.js'
import { chooseStudyBatch, orderStudyBatches } from '../../utils/resourceBatchOrder.js'
import ResourceViewer from './ResourceViewer.vue'
import PreparationWorkspace from '../../components/PreparationWorkspace.vue'
import CoursewareViewer from '../courseware/CoursewareViewer.vue'
import FocusResourceSwitcher from './FocusResourceSwitcher.vue'
import TutorDrawer from '../tutor/TutorDrawer.vue'
import TutorMark from '../tutor/TutorMark.vue'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const selectedLearnerId = ref(route.query.learnerId || store.currentLearnerId || localStorage.getItem('last_learner_id') || '')
const selectedRunId = ref(route.query.runId || '')
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
const nodeNames = ref(new Map())
const resourceDetails = ref({})
let detailRequestGeneration = 0
const tutorOpen = ref(false)
const tutorQuotedText = ref('')
const tutorTriggerRef = ref(null)
const tutorTriggerVisible = ref(true)
const tutorFloatingTop = ref(88)
let tutorTriggerObserver
let tutorObserverVersion = 0

function updateTutorFloatingPosition() {
  const button = tutorTriggerRef.value?.$el
  const viewport = button?.closest('.resources-page.is-focus-mode, .content-area')
  tutorFloatingTop.value = Math.max(16, (viewport?.getBoundingClientRect().top || 0) + 16)
}

async function observeTutorTrigger() {
  const version = ++tutorObserverVersion
  tutorTriggerObserver?.disconnect()
  tutorTriggerVisible.value = true
  await nextTick()
  if (!resourcesMounted || version !== tutorObserverVersion) return
  const button = tutorTriggerRef.value?.$el
  if (!button) return
  updateTutorFloatingPosition()
  tutorTriggerObserver = new IntersectionObserver(([entry]) => {
    tutorTriggerVisible.value = entry.isIntersecting && entry.intersectionRatio >= 0.95
    updateTutorFloatingPosition()
  }, { threshold: [0, 0.95, 1] })
  tutorTriggerObserver.observe(button)
}

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
  label: `${resolveTrackName(profile.knowledge_base_id)} / ${currentProfileRating(profile) || '未分级'}`,
})))

function resolveTrackName(trackId) {
  return tracks.value.find((item) => item.track_id === trackId)?.name || trackId || '未命名方向'
}

const taskGroups = computed(() => {
  // Historical correction packages used their own run as batch_id.  Group
  // them with the source learning resources while their persisted batch is
  // being corrected by newly generated data.
  const effectiveBatchByRunId = new Map()
  const jobsByRunId = new Map(generationJobs.value.map(job => [job.run_id, job]))
  for (const job of generationJobs.value) {
    const correctionSourceRunId = job.request_payload?.constraints?.correction_focus_snapshot?.source_run_id
    if (!correctionSourceRunId) continue
    const sourceJob = jobsByRunId.get(correctionSourceRunId)
    effectiveBatchByRunId.set(job.run_id, sourceJob?.batch_id || sourceJob?.run_id || correctionSourceRunId)
  }
  const groups = new Map()
  for (const resource of visibleResources.value) {
    const batchId = effectiveBatchByRunId.get(resource.run_id) || resource.batch_id || resource.run_id || `resource:${resource.resource_id}`
    if (!groups.has(batchId)) groups.set(batchId, { runId: batchId, batchId, shortRunId: batchId.startsWith('resource:') ? '独立资源' : batchId.slice(0, 8).toUpperCase(), resources: [] })
    groups.get(batchId).resources.push(resource)
  }
  return orderStudyBatches(Array.from(groups.values()))
    .map((task) => {
    const timestamp = task.latestCreatedAt
    const batchLabel = `资源批次 ${String(task.batchNumber).padStart(2, '0')}`
    const nodeIds = new Set()
    for (const resource of task.resources) {
      const job = jobsByRunId.get(resource.run_id)
      const request = job?.request_payload
      const ids = [
        request?.constraints?.target_skill_node_ids,
        request?.target_skill_nodes,
        job?.focus_snapshot?.adopted_node_ids,
      ].find(values => Array.isArray(values) && values.length)
        || (resource.knowledge_points || []).filter(point => nodeNames.value.has(point))
      ids.forEach(id => nodeIds.add(id))
    }
    const nodeTitle = [...new Set([...nodeIds].map(id => nodeNames.value.get(id) || id))].join('、')
    const batchMeta = [batchLabel, `${task.resources.length} 份资源`, formatDateTime(timestamp)].join(' ｜ ')
    const label = nodeTitle ? `${nodeTitle} ｜ ${batchMeta}` : batchMeta
    return { ...task, batchLabel, nodeTitle, batchMeta, label }
  })
})
const activeTask = computed(() => taskGroups.value.find((item) => item.runId === selectedRunId.value) || taskGroups.value[0] || null)
const activeResources = computed(() => sortResourcesForShelf(activeTask.value?.resources || []).map(resource => ({
  ...resource,
  study_context_title: `${resourceStudyContext(resource, activeTask.value?.resources || [], generationJobs.value)} · ${formatDateTime(resource.created_at)}`,
  study_marker: resourceStudyMarker(resource, activeTask.value?.resources || []),
})))
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
  selectedRunId.value = chooseStudyBatch(taskGroups.value, {
    runId: selectedRunId.value, resourceId: selectedResourceId.value,
  })
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
  const location = resourceFeedbackLocation({ learnerId: selectedLearnerId.value, batchId,
    resource: selectedResource.value, jobs: generationJobs.value })
  if (location) router.push(location)
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
    let names = new Map()
    if (knowledgeBaseId) {
      try {
        const nodesRes = await knowledgeApi.listNodes(knowledgeBaseId)
        if (!isCurrent()) return
        const nodes = nodesRes.data?.nodes || nodesRes.data || []
        names = new Map(nodes.map(node => [node.node_id, node.name || node.node_id]))
        tiers = Object.fromEntries(nodes
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
    nodeNames.value = names
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
  nodeNames.value = new Map()
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

watch([tutorTriggerRef, isFocusMode], observeTutorTrigger, { flush: 'post' })

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
  window.addEventListener('resize', updateTutorFloatingPosition)
  try {
    await loadProfiles()
    if (resourcesMounted) await loadResources()
  } catch (error) {
    if (!resourcesMounted) return
    libraryError.value = error?.response?.data?.message || '学习画像加载失败，请刷新页面重试'
    loaded.value = true
  }
})
onBeforeUnmount(() => {
  resourcesMounted = false
  ++resourceListRequestVersion
  ++detailRequestGeneration
  ++tutorObserverVersion
  tutorTriggerObserver?.disconnect()
  window.removeEventListener('resize', updateTutorFloatingPosition)
})
</script>

<style scoped>
.tutor-floating-trigger {
  position: fixed;
  right: 36px;
  z-index: 40;
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 1px solid #ccdde6;
  border-radius: 50%;
  background: #fbfdff;
  color: #286078;
  box-shadow: 0 2px 6px rgb(31 70 91 / 11%);
  cursor: pointer;
}
.tutor-floating-trigger svg { width: 21px; height: 21px; }
.tutor-floating-trigger:hover {
  border-color: #9abecb;
  background: #edf6fa;
  color: #154d64;
}
.tutor-floating-trigger:focus-visible { outline:3px solid #16758a; outline-offset:3px; }
@media (max-width:720px) { .tutor-floating-trigger { right:28px; } }
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

.resources-page { display: flex; flex-direction: column; gap: 12px; width: 100%; max-width: none; min-height: 0; margin: 0 auto; align-self: stretch; padding-top: 20px; padding-bottom: 0; }
.library-empty.preparation-workspace::before { content: none; }
.learning-toolbar { display: grid; grid-template-columns: minmax(0, 1fr) max-content; gap: 18px; align-items: end; padding: 12px 18px 14px; }
.toolbar-fields { display: grid; min-width: 0; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.field-label { display: flex; min-width: 0; flex-direction: column; gap: 5px; color: var(--learn-muted); font-size: 12px; font-weight: 500; }
.field-caption { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.field-caption small { flex-shrink: 0; font: 11px/1.5 Consolas, 'SFMono-Regular', monospace; }
.field-label :deep(.el-select) { width: 100%; min-width: 0; }
.field-label :deep(.el-select__selected-item) { min-width: 0; max-width: 100%; }
.field-label :deep(.el-select__selection) { min-width: 0; }
.batch-node-name { color: #153e56; font-weight: 650; }
.toolbar-actions { display: flex; align-items: center; justify-content: flex-end; min-width: max-content; gap: 8px; white-space: nowrap; }
.focus-button {
  width: 44px;
  height: 44px;
  margin: 0;
  padding: 0;
  border: 1px solid #a4becf;
  border-radius: 10px;
  background: linear-gradient(155deg, #fbfdff, #dfedf6);
  color: #285775;
  font-size: 16px;
  box-shadow: inset 0 1px 0 #fff, 0 3px 6px -4px #486c85;
}
.focus-button:hover { border-color: #7399b2; background: #e2f0f9; color: #194969; }

.learning-workspace { display: flex; flex-direction: column; gap: 0; width: 100%; min-height: 0; flex: 1; }
.resources-page .learning-workspace {
  border: 1px solid transparent !important;
  border-radius: 14px !important;
  background:
    radial-gradient(ellipse at 87% 0%, rgb(190 226 230 / 24%), transparent 54%) padding-box,
    linear-gradient(180deg, #f8fbfd 0%, #fff 18%, #fff 100%) padding-box,
    linear-gradient(140deg, #b6cfdc, #d9e6ed 46%, #b4cdd5) border-box !important;
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 80%),
    0 3px 6px -3px rgb(33 64 86 / 26%),
    0 15px 30px -16px rgb(33 64 86 / 36%) !important;
}
.resources-page .resource-shelf,
.resources-page .reading-stage :deep(.focus-resource-switcher),
.resources-page .reading-stage :deep(.reader-header) {
  background: linear-gradient(90deg, #f2f7fa, #deedf1) !important;
}
.resources-page .resource-shelf,
.resources-page .reading-stage :deep(.focus-resource-switcher) {
  position: static;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  max-height: none;
  padding: 11px 14px;
  border: 0 !important;
  border-bottom: 1px solid #cbdde5 !important;
  box-shadow:
    inset 0 1px 0 rgb(255 255 255 / 88%),
    inset 0 -1px 1px rgb(111 142 167 / 10%) !important;
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
  scrollbar-color: #9ab6c2 #edf3f6;
}
.resources-page .resource-shelf { border-radius: 13px 13px 0 0 !important; }
.shelf-heading { display: flex; flex: 0 0 156px; align-items: center; justify-content: space-between; padding: 0 6px; }
.eyebrow { display: block; color: var(--learn-muted) !important; font: 10px/1.5 Consolas, 'SFMono-Regular', monospace; text-transform: uppercase; }
.shelf-heading h3 { margin: 5px 0 0; font-size: 17px; font-weight: 650; line-height: 1.5; }
.shelf-count { display: grid; min-width: 28px; height: 28px; place-items: center; border: 1px solid #c6dbe6; border-radius: 8px; background: #f5fbfd; color: #38617a; font: 600 12px/1 Consolas, monospace; }
.learning-workspace :deep(.resource-item) {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 14px;
  flex: 0 0 clamp(158px, 15vw, 208px);
  min-height: 54px;
  gap: 9px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid #ccdde6;
  border-radius: 10px;
  background: linear-gradient(150deg, #fff, #f1f6fa);
  box-shadow: inset 0 1px 0 #fff, 0 3px 6px -5px #59778d;
  color: var(--learn-ink);
  cursor: pointer;
  text-align: left;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.learning-workspace :deep(.resource-item:hover) { border-color: #96b6c8; }
.learning-workspace :deep(.resource-item.is-active) {
  border-color: #8cbac3;
  background: linear-gradient(135deg, #f6fdfd, #d8edf0);
  box-shadow: inset 0 1px 0 #fff, 0 4px 8px -5px #4a7b8b;
}
.learning-workspace :deep(.resource-order) { display: grid; width: 26px; height: 26px; place-items: center; border: 1px solid #d7e5ec; border-radius: 7px; background: #f8fbfd; color: var(--learn-muted); font: 500 11px/1 Consolas, monospace; }
.learning-workspace :deep(.resource-item.is-active .resource-order) { border-color: #93c5cb; background: #cce8eb; color: #185966; }
.learning-workspace :deep(.resource-item-copy) { display: flex; min-width: 0; flex-direction: column; gap: 4px; }
.learning-workspace :deep(.resource-item-copy :is(strong, small)) { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.learning-workspace :deep(.resource-item-copy strong) { color: var(--learn-ink); font-size: 13px; font-weight: 650; }
.learning-workspace :deep(.resource-study-marker) { color: var(--learn-muted); font-weight: 500; }
.learning-workspace :deep(.resource-item-copy small) { color: var(--learn-muted); font-size: 11px; line-height: 1.4; }
.learning-workspace :deep(.resource-item.is-active .resource-item-copy strong) { color: #164754; }
.learning-workspace :deep(.resource-item.is-active .resource-item-copy small) { color: #456c78; }
.learning-workspace :deep(.resource-arrow) { color: #537a8b; font-size: 14px; }
.learning-workspace :deep(.resource-item.is-active .resource-arrow) { color: var(--learn-teal); }
.resource-feedback-button { flex: 0 0 auto; min-width: 110px; height: 54px; margin: 0 0 0 4px; padding: 0 16px; border: 1px solid #adc4dc; border-radius: 10px; background: linear-gradient(155deg, #f9fcff, #e0ecf9); color: #254e73; font-size: 13px; font-weight: 650; box-shadow: inset 0 1px 0 #fff, 0 3px 7px -4px #7493b1; }
.resource-feedback-button:hover { border-color: #87a9c9; background: #dfecfa; color: #204968; }
.shelf-footnote { display: none; }
.reading-stage { width: 100%; min-width: 0; min-height: 0; align-self: stretch; container: resource-reader / inline-size; }

.reading-stage :deep(.reader-card) { width: 100%; min-height: 0; border: 0; border-radius: 0 0 13px 13px; background: #fff; box-shadow: none; }
.reading-stage :deep(.reader-header) {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  min-height: 68px;
  padding: 12px 24px;
  border-bottom: 1px solid #dfe9ee;
  box-shadow: inset 0 1px 0 #fff;
}
.reading-stage :deep(.reader-title-wrap) { min-width: 0; }
.reading-stage :deep(.reader-context-title) { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; min-width: 0; }
.reading-stage :deep(.learning-status) { padding: 4px 9px; border-radius: 99px; background: #e7f3f2; color: var(--learn-teal); font-size: 12px; font-weight: 600; }
.reading-stage :deep(.learning-status i) { width: 6px; height: 6px; background: #197b78; box-shadow: none; }
.reading-stage :deep(.resource-kicker) { max-width: none; min-width: 0; padding-left: 0; border-left: 0; overflow: visible; color: var(--learn-ink); font-size: 14px; font-weight: 650; line-height: 1.5; white-space: normal; overflow-wrap: anywhere; text-overflow: clip; }
.reading-stage :deep(.reader-actions) { display: flex; grid-column: 2; justify-self: end; align-items: center; justify-content: flex-end; flex-wrap: wrap; min-width: 0; max-width: 100%; gap: 8px; }
.reading-stage :deep(.learning-progress) { color: var(--learn-muted); font: 11px/1.5 Consolas, 'Microsoft YaHei', monospace; }
.reading-stage :deep(.reader-actions .el-tag) {
  height: auto;
  min-height: 26px;
  padding: 3px 9px;
  border-radius: 13px;
  font-size: 11px;
  line-height: 1.5;
  font-weight: 650;
  box-shadow: inset 0 1px 0 #fff;
}
.reading-stage :deep(.reader-actions .el-tag__content) { display: inline-flex; align-items: center; gap: 6px; }
.reading-stage :deep(.reader-actions .el-tag__content::before) {
  content: '';
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: currentColor;
}
.reading-stage :deep(.reader-actions .el-tag--success) { border-color: #bfdad9; background: linear-gradient(#f7fcfc, #e5f2f0); color: #24625c; }
.reading-stage :deep(.reader-actions .el-tag--warning) { border-color: #e1d3b8; background: linear-gradient(#fffdf8, #f8efdd); color: #805321; }
.reading-stage :deep(.reader-actions .el-tag--danger) { border-color: #e6cdcc; background: linear-gradient(#fffafa, #faeeee); color: #963e40; }
.reading-stage :deep(.reader-actions .download-button), .reading-stage .tutor-trigger { min-height: 44px; height: 44px; margin: 0; padding: 0 13px; border: 1px solid #bfcedc; border-radius: 9px; background: linear-gradient(155deg, #fcfdff, #edf3f8); color: #2b4d69; font-size: 12px; font-weight: 600; box-shadow: inset 0 1px 0 #fff, 0 3px 6px -5px #59778d; transition: border-color .18s ease, color .18s ease; }
.reading-stage :deep(.reader-actions .download-button:hover) { border-color: #91aabf; background: #e9f2f8; color: #224967; }
.reading-stage .tutor-trigger { border-color: #b4cdeb; background: linear-gradient(155deg, #fff, #e2edfc); color: #35649a; }
.tutor-trigger :deep(.el-icon) { margin-right: 2px; font-size: 15px; }
.reading-stage .tutor-trigger:hover { border-color: #8bafd9; background: linear-gradient(155deg, #f7faff, #d6e6fa); color: #284f7e; }
.reading-stage :deep(.reader-content) { padding: 32px 40px 18px; }
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
.reading-stage :deep(.knowledge-tags em) {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  max-width: 100%;
  padding: 5px 10px;
  border: 1px solid #c6dce4;
  border-radius: 7px;
  background: linear-gradient(145deg, #fbfeff, #e7f2f6);
  color: #21576a;
  box-shadow: inset 0 1px 0 #fff, 0 2px 4px -3px #5b8394;
  font: 600 12px/1.5 Consolas, 'Microsoft YaHei', monospace;
  overflow-wrap: anywhere;
}
.reading-stage :deep(.knowledge-tags em::before) {
  content: '';
  flex: 0 0 5px;
  height: 5px;
  border: 1px solid currentColor;
  border-radius: 1px;
  transform: rotate(45deg);
}
.reading-stage :deep(.source-collapse .el-collapse-item__header) { min-height: 44px; height: auto; color: var(--learn-muted); }
.reading-stage :deep(.selection-question-popover) { min-height: 44px; border-color: var(--learn-navy); border-radius: 5px; background: var(--learn-navy); color: #fff; }
.reading-stage :deep(.selection-question-popover:hover) { border-color: #224e62; background: #224e62; }
.library-loading-note { color: var(--learn-muted); font-size: 12px; line-height: 1.7; }
@media (min-width: 1100px) and (min-height: 720px) {
  .library-empty { min-height: calc(100dvh - 212px); }
}

/* Focus mode uses the same materials and buttons without changing its scroll model. */
.resources-page.is-focus-mode { min-height: 100dvh; height: 100dvh; gap: 0; padding: 0; overflow-y: auto; background: var(--learn-paper); }
.resources-page.is-focus-mode .learning-workspace { border: 0 !important; border-radius: 0 !important; background: transparent !important; box-shadow: none !important; }
.is-focus-mode .learning-toolbar, .is-focus-mode .resource-shelf { display: none; }
.is-focus-mode .learning-workspace, .is-focus-mode .reading-stage { flex: 1; min-height: calc(100dvh - 24px); }
.is-focus-mode .reading-stage :deep(.reader-card) { width: 100%; min-height: calc(100dvh - 24px); }
.is-focus-mode .reading-stage :deep(.reader-card) { border: 1px solid var(--learn-line); border-top: 0; border-radius: 0 0 6px 6px; background: #fff; box-shadow: 0 6px 22px rgb(17 40 60 / 3%); }
.focus-exit { position: fixed; right: 20px; bottom: 20px; z-index: 20; width: 44px; height: 44px; margin: 0; border-color: #b9d0dc; background: linear-gradient(145deg, #fbfdff, #e1edf5); color: #285775; box-shadow: inset 0 1px 0 #fff, 0 3px 9px rgb(31 70 91 / 15%); }
.focus-exit:hover, .focus-exit:focus-visible { border-color: #8caebf; background: #e1eef6; color: #194969; }
.resources-layout :deep(:is(button, a, summary):focus-visible) { outline: 3px solid #16758a; outline-offset: 3px; }

@media (min-width: 1101px) {
  .resources-layout.has-tutor-panel.is-focus-mode { display: flex; align-items: stretch; gap: 0; }
  .resources-layout.has-tutor-panel.is-focus-mode .resources-page { flex: 1 1 0; min-width: 0; margin: 0; }
  .resources-layout.is-focus-mode { min-height: 100dvh; height: 100dvh; }
  .resources-layout.is-focus-mode .resources-page { flex: 1 1 0; min-width: 0; }
}
@media (max-width: 760px) {
  .resources-page { min-height: auto; padding-top: 16px; }
  .learning-toolbar { grid-template-columns: minmax(0, 1fr); padding: 10px 12px 11px; gap: 12px; }
  .toolbar-fields { grid-template-columns: 1fr; }
  .toolbar-actions { min-width: 0; flex-wrap: wrap; white-space: normal; }
  .resource-shelf { align-items: stretch; }
  .shelf-heading { flex-basis: 132px; }
  .learning-workspace :deep(.resource-item) { flex-basis: 158px; }
  .reading-stage :deep(.reader-content), .reading-stage :deep(.reader-footer) { padding-left: 23px; padding-right: 23px; }
  .reading-stage :deep(.reader-card) { min-height: auto; }
  .resources-page.is-focus-mode { padding: 0; }
  .is-focus-mode .learning-workspace, .is-focus-mode .reading-stage, .is-focus-mode .reading-stage :deep(.reader-card) { min-height: 100dvh; }
  .focus-exit { right: 14px; bottom: 14px; }
}
@container resource-reader (max-width: 720px) {
  .reading-stage :deep(.reader-header) { grid-template-columns: minmax(0, 1fr); gap: 10px; padding: 12px 16px; }
  .reading-stage :deep(.reader-actions) { grid-column: 1; justify-self: stretch; }
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
