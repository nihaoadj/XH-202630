<template>
  <div class="resources-layout" :class="{ 'has-tutor-panel': tutorOpen, 'is-focus-mode': isFocusMode }">
    <div class="resources-page" :class="{ 'is-focus-mode': isFocusMode }">
    <header class="learning-toolbar">
      <div class="toolbar-title">
        <span class="eyebrow">Learning Resources</span>
        <h3>学习资源</h3>
      </div>
      <div class="toolbar-fields">
        <label class="field-label">
          <span>学习画像</span>
          <el-select v-model="selectedLearnerId" filterable placeholder="选择学习画像" popper-class="refined-select-dropdown" @change="handleProfileChange">
            <el-option v-for="item in profileOptions" :key="item.learner_id" :label="item.label" :value="item.learner_id" />
          </el-select>
        </label>
        <label class="field-label">
          <span>资源批次</span>
          <el-select v-model="selectedRunId" filterable :disabled="!taskGroups.length" placeholder="选择资源批次" popper-class="refined-select-dropdown" @change="handleRunChange">
            <el-option v-for="task in taskGroups" :key="task.runId" :label="task.label" :value="task.runId" />
          </el-select>
        </label>
      </div>
      <div class="toolbar-actions">
        <el-button class="courseware-button" :loading="coursewareBusy" :disabled="!canCreateCourseware" @click="createCourseware">生成互动课件</el-button>
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
            <span class="resource-item-copy"><strong>{{ resource.resource_type || '学习资源' }}</strong><small>{{ resource.difficulty || '待分级' }} · {{ knowledgePointSummary(resource) }}</small></span>
            <span class="resource-arrow">→</span>
          </button>
          <div class="shelf-footnote"><span class="footnote-dot"></span>按顺序完成本批次学习</div>
        </aside>

        <main class="reading-stage">
          <CoursewareViewer v-if="selectedResource?.resource_kind === 'interactive_courseware'" :resource="selectedResource" />
          <ResourceViewer
            v-else-if="selectedResource"
            :resources="[selectedResource]"
            :progress-label="resourceProgress"
            :resource-choices="isFocusMode ? activeResources : []"
            :selected-resource-id="selectedResourceId"
            @select-resource="selectedResourceId = $event"
          >
            <template #header-end-actions>
              <el-button class="tutor-trigger" @click="tutorOpen = true">
                <el-icon><ChatDotRound /></el-icon>
                <span>向 Tutor 提问</span>
              </el-button>
            </template>
          </ResourceViewer>
        </main>
      </section>
    </template>

    <el-empty v-if="!activeTask && loaded && !loading" class="library-empty">
      <template #description><p>该学习画像下暂时没有可阅读的资源</p><span>完成学习方向中的资源生成后，材料会自动归档到这里。</span></template>
      <el-button type="primary" @click="$router.push('/learning/new')">新建学习方向</el-button>
    </el-empty>

    <el-tooltip v-if="isFocusMode" content="退出专注学习模式" placement="left">
      <el-button class="focus-exit" :icon="Close" circle aria-label="退出专注学习模式" @click="exitFocusMode" />
    </el-tooltip>

    <el-dialog v-model="coursewareSourceDialogVisible" title="选择互动课件来源" width="min(620px, 92vw)">
      <p class="courseware-selector-hint">仅可选择当前反馈批次的已发布资源，不同反馈批次不可混用。课件会冻结所选版本。</p>
      <div class="courseware-preferences">
        <label><span>学习目标</span><el-input v-model="coursewarePreferences.learning_goal" maxlength="240" placeholder="例如：掌握本批次的核心检索流程" /></label>
        <label><span>预计时长（分钟）</span><el-input-number v-model="coursewarePreferences.expected_duration_minutes" :min="5" :max="240" :step="5" /></label>
        <label><span>互动强度</span><el-select v-model="coursewarePreferences.interaction_intensity"><el-option label="低" value="low" /><el-option label="中" value="medium" /><el-option label="高" value="high" /></el-select></label>
        <label><span>视觉主题</span><el-select v-model="coursewarePreferences.visual_style_id"><el-option label="编辑风" value="editorial" /><el-option label="午夜" value="midnight" /><el-option label="纸张" value="paper" /></el-select></label>
      </div>
      <el-checkbox-group v-model="selectedCoursewareSourceIds" class="courseware-source-selector">
        <el-checkbox v-for="resource in coursewareCandidates" :key="resource.resource_id" :label="resource.resource_id" :disabled="selectedCoursewareSourceIds.length >= 8 && !selectedCoursewareSourceIds.includes(resource.resource_id)">
          <strong>{{ resource.resource_type }} · {{ resource.batch_id || resource.run_id || '独立资源' }}</strong><span>{{ resource.topic || resource.title || resource.resource_id }} · {{ knowledgePointSummary(resource) }}</span>
        </el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="coursewareSourceDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="coursewareBusy" :disabled="!selectedCoursewareSourceIds.length" @click="startSelectedCourseware">开始生成</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="coursewareDialogVisible" title="互动课件生成进度" width="min(680px, 92vw)">
      <div v-if="currentCoursewareJob" class="courseware-progress-panel">
        <el-tag :type="coursewareStateType(currentCoursewareJob.status)">{{ coursewareStateLabel(currentCoursewareJob.status) }}</el-tag>
        <p v-if="currentCoursewareJob.error_message" class="courseware-error">{{ currentCoursewareJob.error_message }}</p>
        <div v-if="Object.keys(currentCoursewareJob.request_options || {}).length" class="courseware-frozen-options" aria-label="已冻结生成偏好">
          <span>已冻结偏好</span><el-tag v-for="(value, key) in currentCoursewareJob.request_options" :key="key" effect="plain">{{ key }}：{{ value }}</el-tag>
        </div>
        <ol v-if="currentCoursewareJob.scenes?.length" class="courseware-scenes">
          <li v-for="scene in currentCoursewareJob.scenes" :key="scene.scene_id">
            <span>{{ scene.scene_order + 1 }}. {{ scene.title || scene.kind }}</span>
            <small>{{ scene.status }} · 尝试 {{ scene.attempt }}<template v-if="scene.input_snapshot_hash"> · 已冻结输入</template></small>
            <el-button v-if="['failed', 'retry_queued', 'revision_required'].includes(scene.status)" link type="primary" :loading="coursewareBusy" @click="retryCoursewareScene(scene.scene_id)">仅重试此场景</el-button>
          </li>
        </ol>
        <ul v-if="currentCoursewareJob.warnings?.length" class="courseware-warnings">
          <li v-for="warning in currentCoursewareJob.warnings" :key="`${warning.code}:${warning.message}`">{{ warning.message }}</li>
        </ul>
      </div>
      <template #footer>
        <el-button v-if="currentCoursewareJob?.status === 'failed'" :loading="coursewareBusy" @click="retryCurrentCourseware">重试任务</el-button>
        <el-button @click="coursewareDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    </div>
    <TutorDrawer
    v-model="tutorOpen"
    :embedded="isFocusMode"
    :full-height="isFocusMode"
    :learner-id="selectedLearnerId"
    :resource="selectedResource"
    :batch-id="activeTask?.batchId || ''"
    :run-id="selectedResource?.run_id || ''"
    context-type="resource_help"
    :title="selectedResource ? `${selectedResource.resource_type || '学习资源'} · Tutor` : '学习导引'"
  />
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Close, FullScreen, Refresh } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { generateApi, knowledgeApi, profileApi, resourceApi } from '../../api'
import { coursewareApi } from '../courseware/api'
import { buildCoursewareRequest, sameFeedbackBatchSources } from '../courseware/sourcePolicy'
import { resourceLibraryApi } from '../resource-library/api'
import { useCoursewareJob } from '../courseware/useCoursewareJob'
import { useAppStore } from '../../stores/app'
import { formatDateTime } from '../../utils/generationDisplay'
import ResourceViewer from './ResourceViewer.vue'
import CoursewareViewer from '../courseware/CoursewareViewer.vue'
import TutorDrawer from '../tutor/TutorDrawer.vue'

const route = useRoute()
const router = useRouter()
const store = useAppStore()
const selectedLearnerId = ref(route.query.learnerId || store.currentLearnerId || localStorage.getItem('last_learner_id') || '')
const selectedRunId = ref(route.query.runId || localStorage.getItem('current_generation_run_id') || '')
const selectedResourceId = ref('')
const resources = ref([])
const loaded = ref(false)
const loading = ref(false)
const profiles = ref([])
const tracks = ref([])
const generationJobs = ref([])
const resourceDetails = ref({})
let detailRequestGeneration = 0
const tutorOpen = ref(false)
const coursewareDialogVisible = ref(false)
const coursewareSourceDialogVisible = ref(false)
const selectedCoursewareSourceIds = ref([])
const coursewarePreferences = ref({ learning_goal: '', expected_duration_minutes: 30, interaction_intensity: 'medium', visual_style_id: 'editorial' })
const {
  busy: coursewareBusy,
  create: startCoursewareJob,
  currentJob: currentCoursewareJob,
  restoreActiveRun: restoreCoursewareActiveRun,
  retry: retryCoursewareJob,
  retryScene: retryCoursewareSceneJob,
  streamProgress: streamCoursewareProgress,
  waitForTerminal: waitForCoursewareTerminal,
} = useCoursewareJob()

const activeProfile = computed(() => profiles.value.find((item) => item.learner_id === selectedLearnerId.value) || null)
const isFocusMode = computed(() => route.query.focus === '1')
const activeDirectionName = computed(() => resolveTrackName(activeProfile.value?.knowledge_base_id))
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
  const groups = new Map()
  for (const resource of visibleResources.value) {
    const batchId = resource.batch_id || resource.run_id || `resource:${resource.resource_id}`
    if (!groups.has(batchId)) groups.set(batchId, { runId: batchId, batchId, shortRunId: batchId.startsWith('resource:') ? '独立资源' : batchId.slice(0, 8).toUpperCase(), resources: [] })
    groups.get(batchId).resources.push(resource)
  }
  const jobsByBatch = new Map()
  for (const job of generationJobs.value) {
    const batchId = job.batch_id || job.run_id
    if (!jobsByBatch.has(batchId)) jobsByBatch.set(batchId, [])
    jobsByBatch.get(batchId).push(job)
  }
  let initialIndex = 0
  let feedbackIndex = 0
  return Array.from(groups.values())
    .sort((left, right) => String(left.resources[0]?.created_at || '').localeCompare(String(right.resources[0]?.created_at || '')))
    .map((task) => {
    const timestamp = task.resources[0]?.created_at || task.resources[0]?.updated_at
    const isFeedbackBatch = (jobsByBatch.get(task.batchId) || []).some(
      (job) => Boolean(job.request_payload?.constraints?.feedback_attempt_id),
    )
    const batchLabel = isFeedbackBatch
      ? `反馈批次 ${String(++feedbackIndex).padStart(2, '0')}`
      : `初始资源批次 ${String(++initialIndex).padStart(2, '0')}`
    return { ...task, batchLabel, label: `${batchLabel} · ${task.resources.length} 份资源 · ${formatDateTime(timestamp)}` }
  })
})
const activeTask = computed(() => taskGroups.value.find((item) => item.runId === selectedRunId.value) || taskGroups.value[0] || null)
const activeResources = computed(() => activeTask.value?.resources || [])
const coursewareSourceIds = computed(() => activeResources.value
  .filter((item) => item.resource_kind !== 'interactive_courseware')
  .map((item) => item.resource_id))
const coursewareCandidates = computed(() => {
  const source = sameFeedbackBatchSources(visibleResources.value, activeTask.value?.batchId)
  const activeTopic = activeResources.value.find((item) => item.resource_type === '讲义')?.topic
  return [...source].sort((left, right) => {
    const leftScore = Number(Boolean(activeTopic && left.topic === activeTopic)) + Number(left.resource_type === '讲义')
    const rightScore = Number(Boolean(activeTopic && right.topic === activeTopic)) + Number(right.resource_type === '讲义')
    return rightScore - leftScore || String(left.created_at || '').localeCompare(String(right.created_at || ''))
  })
})
const canCreateCourseware = computed(() => !coursewareBusy.value && coursewareCandidates.value.length > 0
  && coursewareCandidates.value.some((item) => item.resource_type === '讲义'))
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
  detailRequestGeneration += 1
  const generation = detailRequestGeneration
  if (!resourceId || resourceDetails.value[resourceId]) return
  try {
    const response = selectedResource.value?.resource_kind === 'interactive_courseware'
      ? await coursewareApi.get(resourceId)
      : await resourceApi.get(resourceId)
    if (generation !== detailRequestGeneration) return
    const detail = response.data?.resource || response.data?.item || response.data
    if (detail?.resource_id === resourceId) {
      resourceDetails.value = { ...resourceDetails.value, [resourceId]: detail }
    }
  } catch (error) {
    if (generation !== detailRequestGeneration) return
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || error?.response?.data?.message || '资源正文加载失败')
  }
}

async function createCourseware() {
  if (!canCreateCourseware.value || !selectedLearnerId.value) return
  try {
    const response = await fetch('/health/ready', { credentials: 'include' })
    const report = await response.json()
    if (!response.ok || report.status !== 'ready') {
      ElMessage.warning('AI/Worker 当前未就绪，请先检查服务状态后再生成。')
      return
    }
  } catch (_) {
    ElMessage.warning('无法检查 AI/Worker readiness，已阻止无提示降级生成。')
    return
  }
  selectedCoursewareSourceIds.value = coursewareCandidates.value
    .filter((item) => item.resource_type === '讲义' || item.topic === activeResources.value.find((resource) => resource.resource_type === '讲义')?.topic)
    .slice(0, 8)
    .map((item) => item.resource_id)
  coursewareSourceDialogVisible.value = true
}

async function startSelectedCourseware() {
  if (!selectedCoursewareSourceIds.value.length || !selectedLearnerId.value) return
  try {
    const created = await startCoursewareJob({
      ...buildCoursewareRequest({ learnerId: selectedLearnerId.value, sourceIds: selectedCoursewareSourceIds.value, preferences: coursewarePreferences.value }),
    })
    const runId = created?.run_id
    coursewareSourceDialogVisible.value = false
    coursewareDialogVisible.value = true
    const stopProgressStream = streamCoursewareProgress(runId)
    let status
    try {
      status = await waitForCoursewareTerminal(runId)
    } finally {
      stopProgressStream()
    }
    if (['published', 'published_with_warnings'].includes(status?.status)) {
      ElMessage.success(status.status === 'published' ? '互动课件已生成' : '互动课件已生成，部分可选场景已跳过')
      await loadResources()
      selectedRunId.value = status.run_id
      selectedResourceId.value = status.resource_id || ''
      return
    }
    if (['failed', 'rejected_admission'].includes(status?.status)) {
      ElMessage.error(status.error_message || '互动课件生成未完成')
      return
    }
    ElMessage.info('课件仍在生成，可稍后刷新资源库查看')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '互动课件创建失败')
  }
}

async function retryCoursewareScene(sceneId) {
  try {
    await retryCoursewareSceneJob(sceneId)
    ElMessage.success('已提交场景级重试；冻结来源与其他已批准场景会被保留')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '场景重试失败')
  }
}

async function retryCurrentCourseware() {
  const runId = currentCoursewareJob.value?.run_id
  if (!runId) return
  try {
    await retryCoursewareJob()
    ElMessage.success('已提交重试，已批准场景和冻结快照会被复用')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '课件重试失败')
  }
}

function coursewareStateLabel(status) {
  return ({ queued: '等待中', admitting: '校验来源', snapshotting: '冻结快照', design_reviewing: '课程设计', composing: '生成场景', trace_reviewing: '来源审核', quality_reviewing: '质量审核', rendering: '渲染课件', validating: '安全校验', approved_pending_publish: '等待发布', published: '已发布', published_with_warnings: '已发布（有警告）', failed: '失败', rejected_admission: '来源未通过' })[status] || status
}

function coursewareStateType(status) {
  if (['published', 'published_with_warnings'].includes(status)) return 'success'
  if (['failed', 'rejected_admission'].includes(status)) return 'danger'
  if (status === 'approved_pending_publish') return 'warning'
  return 'primary'
}

function handleRunChange(value) {
  if (value && !value.startsWith('resource:')) localStorage.setItem('current_generation_run_id', value)
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
  profiles.value = profileRes.data.items || profileRes.data.profiles || []
  tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
  if (!profiles.value.length) { selectedLearnerId.value = ''; return }
  if (!profiles.value.some((item) => item.learner_id === selectedLearnerId.value)) selectedLearnerId.value = store.currentLearnerId || profiles.value[0].learner_id
  syncProfileContext()
}

async function loadResources() {
  if (!selectedLearnerId.value) {
    resources.value = []; loaded.value = true; selectedRunId.value = ''; selectedResourceId.value = ''
    return
  }
  loading.value = true
  try {
    const [res, jobsRes] = await Promise.all([
      resourceLibraryApi.listByLearner(selectedLearnerId.value),
      generateApi.listJobs(selectedLearnerId.value),
    ])
    detailRequestGeneration += 1
    resourceDetails.value = {}
    resources.value = (res.data || []).map((item) => ({
      ...item,
      resource_id: item.id,
      created_at: item.created_at || item.published_at,
    }))
    generationJobs.value = jobsRes.data.items || []
    loaded.value = true
    syncSelectedRun()
    syncSelectedResource()
    await loadSelectedResourceDetail()
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '资源加载失败')
  } finally {
    loading.value = false
  }
}

async function handleProfileChange() {
  syncProfileContext()
  selectedRunId.value = ''
  selectedResourceId.value = ''
  await loadResources()
}

watch(activeTask, () => {
  syncSelectedResource()
  void loadSelectedResourceDetail()
})
watch(selectedResourceId, () => {
  void loadSelectedResourceDetail()
})
async function resumeCoursewareTracking() {
  const restored = await restoreCoursewareActiveRun()
  if (!restored || ['published', 'published_with_warnings', 'quarantined', 'failed', 'rejected_admission', 'release_blocked', 'cancelled', 'timed_out'].includes(restored.status)) return
  coursewareDialogVisible.value = true
  const stopProgressStream = streamCoursewareProgress(restored.run_id)
  void waitForCoursewareTerminal(restored.run_id).then(async (status) => {
    if (['published', 'published_with_warnings'].includes(status?.status)) {
      await loadResources()
      selectedRunId.value = status.run_id
      selectedResourceId.value = status.resource_id || ''
    }
  }).finally(stopProgressStream)
}

onMounted(async () => {
  await loadProfiles()
  await loadResources()
  await resumeCoursewareTracking()
})
</script>

<style scoped>
.resources-page { display: flex; flex-direction: column; gap: 20px; max-width: 1540px; margin: 0 auto; padding-bottom: 24px; }
.library-hero { position: relative; display: flex; align-items: flex-end; justify-content: space-between; gap: 28px; min-height: 210px; padding: 36px 40px; overflow: hidden; border-radius: 24px; background: radial-gradient(circle at 84% 20%, rgba(45, 212, 191, .38), transparent 24%), radial-gradient(circle at 78% 120%, rgba(96, 165, 250, .35), transparent 42%), linear-gradient(120deg, #102d51 0%, #123360 51%, #17447e 100%); box-shadow: 0 18px 38px rgba(20, 61, 91, .17); color: #fff; }
.hero-orbit { position: absolute; border: 1px solid rgba(255, 255, 255, .2); border-radius: 50%; pointer-events: none; }
.hero-orbit-one { right: 146px; top: -112px; width: 330px; height: 330px; }.hero-orbit-two { right: -38px; bottom: -164px; width: 330px; height: 330px; }
.hero-copy, .hero-actions { position: relative; z-index: 1; }.eyebrow { display: block; color: #2058a7; font-size: 12px; font-weight: 800; letter-spacing: 0; line-height: 1.2; text-transform: uppercase; }.library-hero .eyebrow { color: rgba(214, 249, 247, .75); }
.hero-copy h2 { margin: 10px 0 0; font-size: 32px; letter-spacing: -.03em; }.hero-copy p { max-width: 630px; margin: 10px 0 0; color: rgba(235, 249, 255, .82); font-size: 15px; line-height: 1.7; }.hero-actions { display: flex; flex: 0 0 auto; gap: 10px; }.hero-actions :deep(.el-button) { height: 40px; border-radius: 10px; font-weight: 650; }.hero-actions :deep(.el-button--primary) { border-color: #f7fffe; background: #f7fffe; color: #17447e; }.hero-refresh { border-color: rgba(255, 255, 255, .38) !important; background: rgba(255, 255, 255, .08) !important; color: #fff !important; }
.selection-card { display: grid; grid-template-columns: minmax(260px, .85fr) minmax(460px, 1.15fr); gap: 26px; align-items: center; padding: 22px 26px; border: 1px solid #dce6f2; border-radius: 18px; background: rgba(255,255,255,.92); box-shadow: 0 10px 30px rgba(38,69,105,.05); }.selection-title { display: flex; align-items: center; gap: 13px; }.step-badge { display: grid; width: 38px; height: 38px; place-items: center; border-radius: 12px; background: #eaf2ff; color: #255db7; font-size: 13px; font-weight: 800; }.selection-title strong { color: #172a45; font-size: 16px; }.selection-title p { margin: 5px 0 0; color: #72819a; font-size: 13px; }.selection-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }.field-label { display: flex; flex-direction: column; gap: 7px; color: #65758e; font-size: 12px; font-weight: 650; }.field-label :deep(.el-select) { width: 100%; }.field-label :deep(.el-select__wrapper) { min-height: 40px; border-radius: 9px; box-shadow: 0 0 0 1px #d8e2ef inset; }
.path-overview { display: flex; align-items: stretch; justify-content: space-between; gap: 24px; padding: 25px 30px; border: 1px solid #dfe8f2; border-radius: 18px; background: linear-gradient(105deg, #f7fbff, #f3fbfa); }.path-heading h3, .shelf-heading h3 { margin: 7px 0 0; color: #162d49; font-size: 22px; letter-spacing: -.02em; }.path-heading p { margin: 9px 0 0; color: #61728b; font-size: 14px; }.path-stats { display: grid; grid-template-columns: repeat(3, minmax(106px, 1fr)); min-width: 380px; border-left: 1px solid #dbe7ed; }.stat-item { display: flex; flex-direction: column; justify-content: center; padding-left: 25px; }.stat-item + .stat-item { border-left: 1px solid #dbe7ed; }.stat-item span { color: #74859b; font-size: 12px; }.stat-item strong { margin-top: 7px; color: #173654; font-size: 24px; line-height: 1; }.stat-item small { color: #8091a8; font-size: 12px; font-weight: 500; }.task-stamp strong { color: #176b70; font-size: 15px; letter-spacing: .04em; }
.learning-workspace { display: grid; grid-template-columns: 290px minmax(0, 1fr); align-items: start; gap: 20px; }.resource-shelf { position: sticky; top: 0; padding: 23px 15px 15px; border: 1px solid #dce6ef; border-radius: 18px; background: #fff; box-shadow: 0 12px 30px rgba(35,62,94,.05); }.shelf-heading { display: flex; align-items: flex-start; justify-content: space-between; padding: 0 10px 18px; }.shelf-heading h3 { font-size: 18px; }.shelf-count { display: grid; min-width: 28px; height: 28px; place-items: center; border-radius: 9px; background: #e8f1ff; color: #2058a7; font-size: 12px; font-weight: 800; }.resource-item { display: grid; grid-template-columns: 30px minmax(0, 1fr) 14px; width: 100%; gap: 10px; align-items: center; padding: 13px 10px; border: 1px solid transparent; border-radius: 12px; background: transparent; color: #344963; cursor: pointer; text-align: left; transition: .18s ease; }.resource-item:hover { background: #f4f8fd; }.resource-item.is-active { border-color: #b4d1ee; background: linear-gradient(100deg, #eaf4ff, #e8f1ff); box-shadow: 0 7px 15px rgba(53,110,157,.1); }.resource-order { display: grid; width: 28px; height: 28px; place-items: center; border-radius: 8px; background: #eff4fa; color: #71839b; font-size: 10px; font-weight: 800; }.resource-item.is-active .resource-order { background: #1e6ed2; color: #fff; }.resource-item-copy { display: flex; min-width: 0; flex-direction: column; gap: 4px; }.resource-item-copy strong, .resource-item-copy small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.resource-item-copy strong { color: #203853; font-size: 14px; }.resource-item-copy small { color: #77889d; font-size: 11px; }.resource-arrow { color: #91a1b6; font-size: 16px; transition: transform .18s ease; }.resource-item.is-active .resource-arrow { color: #2058a7; transform: translateX(2px); }.shelf-footnote { display: flex; align-items: center; gap: 7px; margin: 15px 10px 2px; padding-top: 14px; border-top: 1px solid #e9eef5; color: #8594a8; font-size: 11px; }.footnote-dot { width: 6px; height: 6px; border-radius: 50%; background: #34b5a2; }.reading-stage { min-width: 0; }.reading-stage-topline { display: flex; justify-content: space-between; margin: 0 5px 9px; color: #718198; font-size: 12px; font-weight: 650; }.reading-stage-topline span:last-child { color: #2058a7; }
.library-empty { padding: 58px 20px; border: 1px dashed #c9d7e6; border-radius: 18px; background: rgba(255,255,255,.72); }.library-empty :deep(.el-empty__description p) { margin: 0; color: #344a65; font-size: 16px; }.library-empty :deep(.el-empty__description span) { display: block; margin-top: 7px; color: #8592a4; font-size: 13px; }
@media (max-width: 1160px) { .selection-card, .learning-workspace { grid-template-columns: 1fr; }.resource-shelf { position: static; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px; }.shelf-heading, .shelf-footnote { grid-column: 1 / -1; } }
@media (max-width: 760px) { .library-hero, .path-overview { flex-direction: column; align-items: flex-start; }.library-hero { min-height: auto; padding: 28px 24px; }.hero-copy h2 { font-size: 27px; }.selection-fields, .path-stats, .resource-shelf { grid-template-columns: 1fr; }.path-stats { width: 100%; min-width: 0; border-top: 1px solid #dbe7ed; border-left: 0; }.stat-item { padding: 16px 0 0; }.stat-item + .stat-item { margin-top: 12px; border-top: 1px solid #dbe7ed; border-left: 0; } }

/* The learning view keeps context compact so the reader remains the primary surface. */
.resources-page {
  min-height: 0;
  gap: 12px;
  max-width: none;
  width: 100%;
  align-self: stretch;
  padding-bottom: 0;
}

.learning-toolbar {
  display: grid;
  grid-template-columns: minmax(150px, .55fr) minmax(540px, 1.45fr) 84px;
  gap: 18px;
  align-items: end;
  padding: 15px 18px;
  border: 1px solid #dbe6f2;
  border-radius: 10px;
  background: rgba(255, 255, 255, .94);
  box-shadow: 0 8px 22px rgba(35, 62, 94, .045);
}

.toolbar-title { display: flex; flex-direction: column; gap: 5px; padding-bottom: 1px; }
.toolbar-title .eyebrow { color: #2058a7; font-size: 12px; font-weight: 800; letter-spacing: 0; text-transform: uppercase; }
.toolbar-title h3 { margin: 0; color: #172033; font-size: 28px; line-height: 1.1; }
.toolbar-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.field-label { gap: 5px; font-size: 11px; }
.field-label :deep(.el-select__wrapper) { min-height: 36px; border-radius: 8px; }
.refresh-button { width: 36px; height: 36px; margin: 0; border-color: #cbd9e8; color: #2058a7; }
.toolbar-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
.focus-button { width: 36px; height: 36px; margin: 0; border-color: #9fc5ec; color: #2058a7; background: #f5f9ff; }
.focus-button:hover, .focus-button:focus-visible { border-color: #2f8b7b; color: #fff; background: #2058a7; }

.learning-context {
  display: flex;
  align-items: center;
  gap: 18px;
  min-height: 62px;
  padding: 10px 18px;
  border: 1px solid #dbe9ee;
  border-radius: 10px;
  background: linear-gradient(90deg, #f8fcff, #f2faf8);
}

.context-heading { display: flex; min-width: 220px; flex-direction: column; gap: 4px; }
.context-heading strong { color: #183653; font-size: 17px; }
.context-caption { color: #6e8199; font-size: 13px; }
.context-stats { display: flex; gap: 18px; margin-left: auto; color: #547087; font-size: 12px; white-space: nowrap; }
.context-stats span + span { padding-left: 18px; border-left: 1px solid #d7e6eb; }
.context-stats b { color: #1b6e6b; font-size: 17px; }

.learning-workspace {
  display: flex;
  flex-direction: column;
  gap: 0;
  width: 100%;
  min-height: 0;
  flex: 1;
}

.resource-shelf {
  position: static;
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  max-height: none;
  padding: 10px 12px;
  border-bottom: 1px solid #dbe6ef;
  border-radius: 10px 10px 0 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.shelf-heading { flex: 0 0 156px; align-items: center; padding: 0 6px; }
.shelf-count { align-self: center; }
.shelf-heading h3 { color: #172033; font-size: 17px; }
.resource-item { flex: 0 0 clamp(158px, 15vw, 208px); width: auto; min-height: 54px; padding: 8px 7px; border-color: #d9e1ec; border-radius: 9px; background: #fff; }
.resource-item .resource-order { width: 26px; height: 26px; }
.resource-item .resource-item-copy strong { font-size: 13px; }
.resource-item .resource-item-copy small { font-size: 10px; }
.resource-item .resource-arrow { font-size: 14px; }
.shelf-footnote { display: none; }
.reading-stage { width: 100%; min-width: 0; min-height: 0; align-self: stretch; }
.reading-stage :deep(.reader-card) {
  width: 100%;
  border-top: 0;
  border-radius: 0 0 10px 10px;
}
.tutor-trigger {
  height: 32px;
  margin: 0;
  padding: 0 11px;
  border-color: #9cd8cf;
  border-radius: 8px;
  background: linear-gradient(135deg, #edfafa, #eaf4ff);
  color: #18756e;
  font-weight: 750;
  box-shadow: 0 3px 9px rgba(38, 133, 120, .12);
}
.tutor-trigger :deep(.el-icon) { margin-right: 1px; font-size: 15px; }
.tutor-trigger:hover, .tutor-trigger:focus-visible { border-color: #238f82; background: #238f82; color: #fff; box-shadow: 0 6px 15px rgba(35, 143, 130, .24); }

.resources-layout { min-height: 0; }
@media (min-width: 1101px) {
  .resources-layout.has-tutor-panel.is-focus-mode { display: flex; align-items: stretch; gap: 0; }
  .resources-layout.has-tutor-panel.is-focus-mode .resources-page { flex: 1 1 0; min-width: 0; margin: 0; }
  .resources-layout.has-tutor-panel.is-focus-mode .reading-stage :deep(.reader-header) { flex-wrap: wrap; align-items: flex-start; gap: 10px; }
  .resources-layout.has-tutor-panel.is-focus-mode .reading-stage :deep(.reader-title-wrap) { min-width: 0; grid-template-columns: minmax(0, 1fr); }
  .resources-layout.has-tutor-panel.is-focus-mode .reading-stage :deep(.reader-actions) { flex-wrap: wrap; justify-content: flex-end; margin-left: auto; }
  .resources-layout.is-focus-mode { min-height: 100dvh; height: 100dvh; }
  .resources-layout.is-focus-mode .resources-page { flex: 1 1 0; min-width: 0; }
}

.representation-switch { display: flex; justify-content: flex-end; margin-bottom: 10px; }
.representation-switch :deep(.el-button) { min-width: 96px; }
.reading-stage :deep(.reader-card) { min-height: 0; }

.resources-page.is-focus-mode { min-height: 100dvh; height: 100dvh; gap: 0; padding: 0; overflow-y: auto; background: #f3f7fb; }
.is-focus-mode .learning-toolbar, .is-focus-mode .resource-shelf { display: none; }
.is-focus-mode .learning-workspace, .is-focus-mode .reading-stage { flex: 1; min-height: calc(100dvh - 24px); }
.is-focus-mode .reading-stage :deep(.reader-card) { width: 100%; min-height: calc(100dvh - 24px); }
.focus-exit { position: fixed; right: 20px; bottom: 20px; z-index: 20; width: 42px; height: 42px; margin: 0; border-color: #9fc5ec; box-shadow: 0 8px 22px rgb(23 58 72 / 20%); color: #fff; background: #2058a7; }
.focus-exit:hover, .focus-exit:focus-visible { border-color: #17447e; color: #fff; background: #17447e; }
.courseware-progress-panel { display: grid; gap: 14px; }
.courseware-preferences { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin:14px 0; padding:14px; border:1px solid #dbe6f2; border-radius:10px; background:#f8fbff; }.courseware-preferences label { display:flex; flex-direction:column; gap:5px; color:#52677f; font-size:12px; }.courseware-preferences :deep(.el-input-number), .courseware-preferences :deep(.el-select) { width:100%; }.courseware-frozen-options { display:flex; flex-wrap:wrap; align-items:center; gap:7px; padding:9px; border:1px solid #dbe9ee; border-radius:8px; background:#f5fbfa; color:#527087; font-size:12px; }
.courseware-selector-hint { margin: 0 0 14px; color: #66788f; font-size: 13px; line-height: 1.65; }
.courseware-source-selector { display: grid; gap: 10px; }
.courseware-source-selector :deep(.el-checkbox) { display: flex; align-items: flex-start; width: 100%; height: auto; margin: 0; padding: 11px; border: 1px solid #dce6ef; border-radius: 9px; }
.courseware-source-selector :deep(.el-checkbox__label) { display: grid; gap: 3px; padding-left: 9px; color: #344963; }
.courseware-source-selector strong { color: #173654; font-size: 13px; }
.courseware-source-selector span { color: #73849a; font-size: 12px; }
.courseware-error { margin: 0; color: #b42318; }
.courseware-scenes, .courseware-warnings { display: grid; gap: 8px; margin: 0; padding-left: 22px; }
.courseware-scenes li { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #344963; }
.courseware-scenes small { color: #71839b; white-space: nowrap; }
.courseware-warnings { color: #9a5b13; font-size: 13px; }

@media (max-width: 1160px) {
  .learning-toolbar { grid-template-columns: 1fr 84px; }
  .toolbar-title { display: none; }
  .learning-workspace { display: flex; flex-direction: column; }
}

@media (max-width: 760px) {
  .resources-page { min-height: auto; }
  .learning-toolbar { grid-template-columns: 1fr 84px; padding: 12px; }
  .toolbar-fields { grid-template-columns: 1fr; }
  .learning-workspace { display: flex; flex-direction: column; }
  .resource-shelf { align-items: stretch; }
  .shelf-heading { flex-basis: 132px; }
  .resource-item { flex-basis: 158px; }
  .reading-stage :deep(.reader-card) { min-height: auto; }
  .resources-page.is-focus-mode { padding: 0; }
  .is-focus-mode .learning-workspace, .is-focus-mode .reading-stage, .is-focus-mode .reading-stage :deep(.reader-card), .is-focus-mode .reading-stage :deep(.html-guide-card) { min-height: 100dvh; }
  .focus-exit { right: 14px; bottom: 14px; }
}
</style>
