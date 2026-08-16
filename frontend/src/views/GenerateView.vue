<template>
  <div class="generate-page">
    <section class="control-panel">
      <div class="panel-title">
        <div>
          <span class="eyebrow">Batch Selection</span>
          <h3>选择学习画像与资源批次</h3>
          <p>默认定位到最新任务，也可以切换历史批次查看当时生成的教学资源。</p>
        </div>
        <el-button class="ghost-button" @click="refreshJobs" :loading="loadingJobs">刷新任务</el-button>
      </div>

      <el-empty
        v-if="!jobs.length"
        description="当前还没有生成任务。请先在学习方向流程中完成诊断并发起资源生成。"
      />

      <template v-else>
        <div class="task-selector">
          <div class="selector-field">
            <span>学习画像</span>
            <el-select
              v-model="selectedLearnerId"
              filterable
              placeholder="选择学习画像"
              class="task-select"
              @change="handleProfileChange"
            >
              <el-option
                v-for="item in profileOptions"
                :key="item.learner_id"
                :label="item.label"
                :value="item.learner_id"
              />
            </el-select>
          </div>
          <div class="selector-field">
            <span>资源批次</span>
            <el-select
              v-model="selectedRunId"
              filterable
              placeholder="选择要查看的生成任务"
              class="task-select"
              @change="handleTaskChange"
            >
              <el-option
                v-for="task in jobs"
                :key="task.run_id"
                :label="taskLabel(task)"
                :value="task.run_id"
              />
            </el-select>
          </div>
        </div>

        <div v-if="selectedJob" class="job-summary">
          <div class="summary-item">
            <span>学习方向</span>
            <strong>{{ learningDirectionName || '-' }}</strong>
          </div>
          <div class="summary-item">
            <span>任务编号</span>
            <strong>{{ shortRunId }}</strong>
          </div>
          <div class="summary-item">
            <span>任务状态</span>
            <strong class="status-value" :class="`status-${selectedJob.job_status || 'idle'}`">
              {{ statusLabel(selectedJob.job_status) }}
            </strong>
          </div>
          <div class="summary-item">
            <span>资源数量</span>
            <strong>{{ resources.length }} 份</strong>
          </div>
          <div class="summary-item">
            <span>创建时间</span>
            <strong>{{ formatDateTime(selectedJob.created_at) }}</strong>
          </div>
          <div class="summary-item">
            <span>完成时间</span>
            <strong>{{ selectedJob.finished_at ? formatDateTime(selectedJob.finished_at) : '等待完成' }}</strong>
          </div>
        </div>

        <p v-if="selectedJob?.error_message" class="error-message">{{ selectedJob.error_message }}</p>

        <div class="status-actions">
          <el-button
            v-if="selectedJob && (selectedJob.job_status === 'running' || selectedJob.job_status === 'queued')"
            @click="refreshStatus"
          >
            刷新状态
          </el-button>
          <el-button
            v-if="selectedJob && selectedJob.job_status === 'failed'"
            type="primary"
            @click="retryGeneration"
            :loading="retrying"
          >
            重新生成
          </el-button>
          <el-button
            v-if="selectedJob && selectedJob.job_status === 'completed'"
            class="primary-action"
            @click="loadResourcesForSelectedJob"
            :loading="loadingResources"
          >
            刷新资源
          </el-button>
          <el-button @click="$router.push('/learning/history')">查看学习历史</el-button>
        </div>
      </template>
    </section>

    <section v-if="selectedJob" class="studio-grid">
      <div class="process-panel">
        <div class="panel-title compact">
          <div>
            <span class="eyebrow">Workflow Trace</span>
            <h3>生成过程</h3>
          </div>
          <el-tag :type="connectionStatus === 'live' ? 'success' : 'info'" effect="plain">
            {{ connectionStatus === 'live' ? '实时同步' : '任务记录' }}
          </el-tag>
        </div>
        <AgentVisualization
          v-if="selectedRunId"
          :trace="timelineState.steps"
          :markers="timelineState.markers"
          :connection-status="connectionStatus"
          :legacy-partial="timelineState.replayCompleteness === 'legacy_partial'"
          @open-child-run="openChildRun"
        />
      </div>

      <div class="resources-panel">
        <div class="panel-title compact">
          <div>
            <span class="eyebrow">Teaching Assets</span>
            <h3>{{ selectedJob.job_status === 'completed' ? '任务资源' : '资源预览' }}</h3>
          </div>
          <el-tag :type="selectedJob.job_status === 'completed' ? 'success' : 'info'" effect="plain">
            {{ resources.length }} 份资源
          </el-tag>
        </div>

        <div v-loading="loadingResources" class="resource-stage">
          <el-empty
            v-if="selectedJob.job_status !== 'completed'"
            :description="selectedJob.job_status === 'failed' ? '该任务生成失败，当前没有可展示的资源。' : '该任务仍在生成中，完成后这里会展示本任务的资源。'"
          />
          <el-empty
            v-else-if="resourcesLoaded && !resources.length"
            description="该任务已完成，但暂时还没有查到资源内容。可以稍后再刷新一次。"
          />
          <template v-else-if="resources.length">
            <div class="resource-toolbar">
              <div>
                <span class="eyebrow">Now Reading</span>
                <strong>{{ selectedResource ? resourceLabel(selectedResource) : '选择资源' }}</strong>
              </div>
              <el-select
                v-model="selectedResourceId"
                filterable
                placeholder="选择要阅读的资源"
                class="resource-select"
              >
                <el-option
                  v-for="item in resources"
                  :key="item.resource_id"
                  :label="resourceLabel(item)"
                  :value="item.resource_id"
                />
              </el-select>
            </div>
            <ResourceViewer v-if="selectedResource" :resources="[selectedResource]" />
          </template>
        </div>
      </div>
    </section>

    <section v-else class="empty-studio">
      <div>
        <span class="eyebrow">Waiting</span>
        <h3>还没有可查看的生成任务</h3>
        <p>完成一次学习方向诊断并发起资源生成后，这里会展示资源批次、过程记录与阅读入口。</p>
      </div>
      <el-button type="primary" @click="$router.push('/learning/new')">新建学习方向</el-button>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generateApi, knowledgeApi, profileApi, resourceApi, runApi } from '../api'
import { createRunEventClient } from '../api/runEvents'
import ResourceViewer from '../components/ResourceViewer.vue'
import AgentVisualization from '../components/AgentVisualization.vue'
import { useAppStore } from '../stores/app'
import {
  formatDateTime,
  formatResourceLabel,
  formatSupplementalRequirements,
  formatTaskLabel,
} from '../utils/generationDisplay'
import {
  applyRunSnapshot,
  createInitialTimelineState,
  hydrateWorkflowTimeline,
  reduceWorkflowEvent,
} from '../utils/workflowEventReducer'

const store = useAppStore()

const learningDirectionName = computed(
  () => store.currentLearningDirectionName || localStorage.getItem('learning_direction_name') || ''
)

const currentDisplayName = computed(
  () =>
    store.currentUserProfile?.display_name ||
    store.currentProfile?.learning_preferences?.metadata?.user_profile_snapshot?.display_name ||
    '当前用户'
)

const selectedLearnerId = ref(
  new URLSearchParams(window.location.search).get('learnerId') ||
  localStorage.getItem('last_learner_id') ||
  store.currentLearnerId ||
  ''
)
const initialRunId =
  new URLSearchParams(window.location.search).get('runId') ||
  localStorage.getItem('current_generation_run_id') ||
  ''

const pollTimer = ref(null)
const jobs = ref([])
const loadingJobs = ref(false)
const loadingResources = ref(false)
const resourcesLoaded = ref(false)
const resources = ref([])
const retrying = ref(false)
const selectedRunId = ref(initialRunId)
const selectedResourceId = ref('')
const profiles = ref([])
const tracks = ref([])
const timelineState = ref(createInitialTimelineState())
const connectionStatus = ref('idle')
let streamClient = null
let streamGeneration = 0

const activeProfile = computed(
  () => profiles.value.find((item) => item.learner_id === selectedLearnerId.value) || null
)
const profileOptions = computed(() =>
  profiles.value.map((profile) => ({
    ...profile,
    label: `${resolveTrackName(profile.knowledge_base_id)} / ${profile.skill_level || '未分级'}`,
  }))
)
const selectedJob = computed(
  () => jobs.value.find((item) => item.run_id === selectedRunId.value) || null
)
const shortRunId = computed(() => (selectedJob.value?.run_id ? selectedJob.value.run_id.slice(0, 8).toUpperCase() : '-'))
const selectedResource = computed(
  () => resources.value.find((item) => item.resource_id === selectedResourceId.value) || null
)

function statusLabel(status) {
  return (
    {
      queued: '排队中',
      running: '生成中',
      completed: '已完成',
      failed: '失败',
    }[status] || '未开始'
  )
}

function statusTagType(status) {
  return (
    {
      queued: 'info',
      running: 'warning',
      completed: 'success',
      failed: 'danger',
    }[status] || 'info'
  )
}

function resolveTrackName(trackId) {
  return tracks.value.find((item) => item.track_id === trackId)?.name || trackId || '未命名方向'
}

function profileDisplayName(profile) {
  const snapshot = profile?.learning_preferences?.metadata?.user_profile_snapshot
  return snapshot?.display_name || snapshot?.name || profile?.learner_type || '未命名画像'
}

function taskLabel(task) {
  const prefix = task.job_status === 'running' || task.job_status === 'queued' ? '当前' : '历史'
  return `${prefix} / ${task.run_id.slice(0, 8).toUpperCase()} / ${formatDateTime(task.finished_at || task.created_at)}`
}

function persistSelectedJob() {
  localStorage.setItem('current_generation_run_id', selectedJob.value?.run_id || '')
  localStorage.setItem('current_generation_status', selectedJob.value?.job_status || '')
}

function resourceLabel(resource) {
  return formatResourceLabel(resource, resolveTrackName(activeProfile.value?.knowledge_base_id))
}

function readLastGenerationRequest() {
  try {
    const raw = localStorage.getItem('last_generation_request')
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function stopPolling() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

function closeRealtime() {
  streamGeneration += 1
  streamClient?.close()
  streamClient = null
}

async function hydrateTimeline(runId) {
  let state = createInitialTimelineState()
  let afterSequence = 0
  let firstPage = true
  try {
    while (true) {
      const response = await runApi.timeline(runId, { after_sequence: afterSequence, limit: 500 })
      if (firstPage) {
        state = hydrateWorkflowTimeline(response.data)
        firstPage = false
      } else {
        for (const event of response.data.events || []) state = reduceWorkflowEvent(state, event)
      }
      if (!response.data.next_event_sequence) break
      afterSequence = response.data.next_event_sequence
    }
  } catch (error) {
    // A queued GenerationJob can legitimately precede AgentRun creation.
    if (error?.response?.status !== 404) throw error
  }
  timelineState.value = state
  return state.lastSequence
}

async function startRealtime(runId) {
  closeRealtime()
  stopPolling()
  timelineState.value = createInitialTimelineState()
  if (!runId) {
    connectionStatus.value = 'idle'
    return
  }
  const generation = streamGeneration
  connectionStatus.value = 'connecting'
  let lastSequence = 0
  try {
    lastSequence = await hydrateTimeline(runId)
  } catch (error) {
    console.error(error)
    connectionStatus.value = 'fallback'
    startPolling()
    return
  }
  if (generation !== streamGeneration) return
  streamClient = createRunEventClient({
    runId,
    afterSequence: lastSequence,
    onSnapshot: (snapshot) => {
      if (generation !== streamGeneration) return
      timelineState.value = applyRunSnapshot(timelineState.value, snapshot)
      connectionStatus.value = snapshot.is_terminal ? 'terminal' : 'live'
    },
    onWorkflowEvent: (event) => {
      if (generation !== streamGeneration) return
      timelineState.value = reduceWorkflowEvent(timelineState.value, event)
    },
    onTerminal: () => {
      if (generation !== streamGeneration) return
      connectionStatus.value = 'terminal'
      void refreshStatus()
    },
    onError: (error) => {
      if (generation !== streamGeneration) return
      if (error?.code !== 'SSE_TRANSPORT_DISCONNECTED') connectionStatus.value = 'error'
    },
    onFallback: () => {
      if (generation !== streamGeneration) return
      connectionStatus.value = 'fallback'
      startPolling()
    },
  })
  streamClient.connect()
}

function startPolling() {
  stopPolling()
  if (!selectedJob.value || !['queued', 'running'].includes(selectedJob.value.job_status)) {
    return
  }
  pollTimer.value = setInterval(refreshStatus, 5000)
}

function pickDefaultRunId(items) {
  if (!items.length) return ''
  const currentJob = items.find((item) => item.job_status === 'running' || item.job_status === 'queued')
  if (currentJob) return currentJob.run_id
  if (initialRunId && items.some((item) => item.run_id === initialRunId)) return initialRunId
  return items[0].run_id
}

function syncProfileContext() {
  const profile = activeProfile.value
  if (!profile) return
  store.resumeProfile(profile, profile.knowledge_base_id, resolveTrackName(profile.knowledge_base_id))
  localStorage.setItem('last_learner_id', profile.learner_id)
}

async function loadProfiles() {
  const [profileRes, domainRes] = await Promise.all([
    profileApi.list({ page: 1, page_size: 50 }),
    knowledgeApi.listDomains(),
  ])
  profiles.value = profileRes.data.items || profileRes.data.profiles || []
  tracks.value = (domainRes.data.domains || []).flatMap((domain) => domain.tracks || [])
  if (!profiles.value.length) {
    selectedLearnerId.value = ''
    return
  }
  if (!profiles.value.some((item) => item.learner_id === selectedLearnerId.value)) {
    selectedLearnerId.value = store.currentLearnerId || profiles.value[0].learner_id
  }
  syncProfileContext()
}

async function loadJobs(preferDefault = false) {
  if (!selectedLearnerId.value) {
    jobs.value = []
    selectedRunId.value = ''
    resources.value = []
    resourcesLoaded.value = false
    closeRealtime()
    stopPolling()
    connectionStatus.value = 'idle'
    return
  }
  loadingJobs.value = true
  try {
    const res = await generateApi.listJobs(selectedLearnerId.value)
    jobs.value = (res.data.items || []).filter((item) => item.job_status !== 'failed')
    if (!jobs.value.length) {
      closeRealtime()
      selectedRunId.value = ''
      timelineState.value = createInitialTimelineState()
      connectionStatus.value = 'idle'
      resources.value = []
      resourcesLoaded.value = false
      selectedResourceId.value = ''
      stopPolling()
      return
    }

    if (
      preferDefault ||
      !selectedRunId.value ||
      !jobs.value.some((item) => item.run_id === selectedRunId.value)
    ) {
      selectedRunId.value = pickDefaultRunId(jobs.value)
    }

    persistSelectedJob()
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '任务列表加载失败')
  } finally {
    loadingJobs.value = false
  }
}

async function loadResourcesForSelectedJob() {
  if (!selectedLearnerId.value || !selectedJob.value?.run_id || selectedJob.value.job_status !== 'completed') {
    resources.value = []
    resourcesLoaded.value = true
    selectedResourceId.value = ''
    return
  }

  loadingResources.value = true
  try {
    const res = await resourceApi.listByLearner(selectedLearnerId.value, { run_id: selectedJob.value.run_id })
    resources.value = res.data.resources || []
    resourcesLoaded.value = true
    if (!resources.value.length) {
      selectedResourceId.value = ''
    } else if (!resources.value.some((item) => item.resource_id === selectedResourceId.value)) {
      selectedResourceId.value = resources.value[0].resource_id
    }
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '资源列表加载失败')
  } finally {
    loadingResources.value = false
  }
}

async function refreshStatus() {
  if (!selectedJob.value?.run_id) return
  try {
    const res = await generateApi.getJobStatus(selectedJob.value.run_id)
    const nextJob = res.data
    jobs.value = jobs.value.map((item) => (item.run_id === nextJob.run_id ? nextJob : item))
    persistSelectedJob()

    if (nextJob.job_status === 'completed') {
      stopPolling()
      await loadResourcesForSelectedJob()
    } else if (nextJob.job_status === 'failed') {
      stopPolling()
      resources.value = []
      resourcesLoaded.value = true
      selectedResourceId.value = ''
    }
  } catch (error) {
    console.error(error)
    stopPolling()
    ElMessage.error(error?.response?.data?.message || '任务状态获取失败')
  }
}

async function refreshJobs() {
  await loadJobs(false)
  if (selectedJob.value?.job_status === 'completed') {
    await loadResourcesForSelectedJob()
  }
  await startRealtime(selectedRunId.value)
}

async function handleTaskChange() {
  persistSelectedJob()
  stopPolling()
  resources.value = []
  resourcesLoaded.value = false
  selectedResourceId.value = ''

  if (!selectedJob.value) return
  if (selectedJob.value.job_status === 'completed') {
    await loadResourcesForSelectedJob()
  } else {
    resourcesLoaded.value = true
  }
  await startRealtime(selectedRunId.value)
}

async function handleProfileChange() {
  syncProfileContext()
  selectedRunId.value = ''
  selectedResourceId.value = ''
  resources.value = []
  resourcesLoaded.value = false
  timelineState.value = createInitialTimelineState()
  closeRealtime()
  stopPolling()
  await loadJobs(true)
  if (selectedJob.value?.job_status === 'completed') {
    await loadResourcesForSelectedJob()
  } else {
    resourcesLoaded.value = true
  }
  await startRealtime(selectedRunId.value)
}

async function openChildRun(runId) {
  selectedRunId.value = runId
  localStorage.setItem('current_generation_run_id', runId)
  await loadJobs(false)
  resources.value = []
  resourcesLoaded.value = false
  selectedResourceId.value = ''
  await startRealtime(runId)
}

async function retryGeneration() {
  const payload = readLastGenerationRequest()
  if (!payload?.learner_id || !payload?.topic || !Array.isArray(payload?.resource_types)) {
    ElMessage.warning('缺少上一轮生成参数，请返回学习方向页面重新发起生成')
    return
  }

  retrying.value = true
  resources.value = []
  resourcesLoaded.value = false
  selectedResourceId.value = ''
  stopPolling()

  try {
    const res = await generateApi.createJob(payload)
    selectedRunId.value = res.data.run_id
    await loadJobs(true)
    await startRealtime(selectedRunId.value)
    ElMessage.success('已重新发起生成任务')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '重新生成失败')
  } finally {
    retrying.value = false
  }
}

onMounted(async () => {
  await loadProfiles()
  await loadJobs(true)
  if (selectedJob.value?.job_status === 'completed') {
    await loadResourcesForSelectedJob()
  } else {
    resourcesLoaded.value = true
  }
  await startRealtime(selectedRunId.value)
})

onBeforeUnmount(() => {
  closeRealtime()
  stopPolling()
})
</script>

<style scoped>
.generate-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
  color: #172033;
}

.control-panel,
.process-panel,
.resources-panel,
.empty-studio {
  border: 1px solid #d9e1ec;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 18px 42px rgba(32, 47, 73, 0.08);
}

.eyebrow {
  display: block;
  color: #2f6e5f;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.summary-item span {
  display: block;
  color: #6a7689;
  font-size: 13px;
  margin-bottom: 8px;
}

.control-panel,
.process-panel,
.resources-panel,
.empty-studio {
  padding: 24px 28px;
}

.panel-title {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
  padding-bottom: 18px;
  border-bottom: 1px solid #e4ebf3;
}

.panel-title.compact {
  padding-bottom: 14px;
  margin-bottom: 18px;
}

.panel-title h3 {
  margin: 5px 0 0;
  font-size: 22px;
  line-height: 1.25;
}

.panel-title p {
  margin: 8px 0 0;
  color: #5d6b82;
  line-height: 1.6;
}

.ghost-button {
  border-color: #b8c8db;
  color: #243246;
}

.task-selector {
  display: grid;
  grid-template-columns: minmax(280px, 0.95fr) minmax(360px, 1.05fr);
  gap: 16px;
  margin: 22px 0;
  max-width: none;
}

.selector-field {
  min-width: 0;
  padding: 14px 16px;
  border: 1px solid #d6e0ec;
  border-radius: 8px;
  background: linear-gradient(180deg, #ffffff, #f8fbff);
}

.selector-field span {
  display: block;
  margin-bottom: 8px;
  color: #63728a;
  font-size: 13px;
  font-weight: 700;
}

.selector-field :deep(.el-select__wrapper) {
  min-height: 42px;
  padding: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.selector-field :deep(.el-select__placeholder),
.selector-field :deep(.el-select__selected-item) {
  color: #172033;
  font-size: 17px;
  font-weight: 600;
}

.task-select {
  width: 100%;
}

.job-summary {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  border: 1px solid #d9e1ec;
  border-radius: 8px;
  overflow: hidden;
  background: #f8fbff;
}

.summary-item {
  min-height: 92px;
  padding: 16px 18px;
  border-right: 1px solid #d9e1ec;
  background: linear-gradient(180deg, #fff, #f7fafc);
}

.summary-item:last-child {
  border-right: 0;
}

.summary-item strong {
  display: block;
  color: #172033;
  font-size: 18px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.summary-item .status-value {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
}

.status-value::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #7a8798;
}

.status-completed {
  color: #2f6e5f;
}

.status-completed::before {
  background: #2f8f6a;
}

.status-running,
.status-queued {
  color: #9a6a1b;
}

.status-running::before,
.status-queued::before {
  background: #d99a2b;
}

.status-failed {
  color: #a43f37;
}

.status-failed::before {
  background: #c94a43;
}

.error-message {
  margin: 16px 0 0;
  padding: 12px 14px;
  border-radius: 8px;
  color: #9f322b;
  background: #fff2f0;
  border: 1px solid #ffd2cd;
}

.status-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 18px;
  flex-wrap: wrap;
}

.primary-action {
  border-color: #2f6e5f;
  background: #2f6e5f;
  color: #fff;
}

.studio-grid {
  display: grid;
  grid-template-columns: minmax(360px, 0.88fr) minmax(520px, 1.12fr);
  gap: 20px;
  align-items: start;
}

.process-panel,
.resources-panel {
  min-width: 0;
}

.process-panel :deep(.el-card) {
  border: 0;
  box-shadow: none;
  background: transparent;
}

.process-panel :deep(.el-card__header) {
  display: none;
}

.process-panel :deep(.el-card__body) {
  padding: 0;
}

.process-panel :deep(.el-timeline) {
  padding-left: 8px;
}

.process-panel :deep(.el-timeline-item__content strong) {
  font-size: 16px;
  color: #172033;
}

.resource-stage {
  min-height: 360px;
}

.resource-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  padding: 16px;
  margin-bottom: 18px;
  border: 1px solid #d9e1ec;
  border-radius: 8px;
  background:
    linear-gradient(135deg, rgba(47, 110, 95, 0.08), transparent 42%),
    #f8fbff;
}

.resource-toolbar strong {
  display: block;
  margin-top: 4px;
  font-size: 18px;
  color: #172033;
}

.resource-select {
  width: min(420px, 46%);
  min-width: 260px;
}

.resources-panel :deep(.resource-reader) {
  box-shadow: none;
}

.empty-studio {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 20px;
}

.empty-studio h3 {
  margin: 6px 0 8px;
  font-size: 22px;
}

.empty-studio p {
  margin: 0;
  color: #5d6b82;
}

@media (max-width: 1200px) {
  .job-summary {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .summary-item {
    border-bottom: 1px solid #d9e1ec;
  }

  .studio-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 920px) {
  .panel-title,
  .task-selector,
  .resource-toolbar,
  .empty-studio {
    flex-direction: column;
  }

  .task-selector {
    display: grid;
    grid-template-columns: 1fr;
  }

  .job-summary {
    grid-template-columns: 1fr;
  }

  .summary-item {
    border-right: 0;
  }

  .resource-select {
    width: 100%;
    min-width: 0;
  }
}
</style>
