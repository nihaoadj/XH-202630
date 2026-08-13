<template>
  <div class="generate-page">
    <section class="hero-card">
      <div class="hero-copy">
        <h2>资源生成状态</h2>
        <p>默认展示当前正在进行的生成任务；如果你想回看之前的任务，也可以在下方切换历史任务并查看该任务下的资源。</p>
      </div>
      <el-tag v-if="learningDirectionName" type="info" effect="plain">
        当前学习方向：{{ learningDirectionName }}
      </el-tag>
    </section>

    <el-card class="status-card">
      <template #header>
        <div class="status-head">
          <div>
            <span>生成任务</span>
            <p class="section-tip">默认优先定位到当前生产中的任务，也支持下拉查看历史任务。</p>
          </div>
          <el-button text @click="refreshJobs" :loading="loadingJobs">刷新任务</el-button>
        </div>
      </template>

      <el-empty
        v-if="!jobs.length"
        description="当前还没有生成任务。请先在学习方向流程中完成诊断并发起资源生成。"
      />

      <template v-else>
        <div class="task-selector">
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

        <div v-if="selectedJob" class="job-summary">
          <p><strong>用户：</strong>{{ currentDisplayName }}</p>
          <p><strong>学习方向：</strong>{{ learningDirectionName || '-' }}</p>
          <p><strong>任务编号：</strong>{{ shortRunId }}</p>
          <p><strong>任务状态：</strong><el-tag :type="statusTagType(selectedJob.job_status)">{{ statusLabel(selectedJob.job_status) }}</el-tag></p>
          <p><strong>创建时间：</strong>{{ formatDateTime(selectedJob.created_at) }}</p>
          <p v-if="selectedJob.finished_at"><strong>完成时间：</strong>{{ formatDateTime(selectedJob.finished_at) }}</p>
          <p v-if="selectedJob.error_message"><strong>错误信息：</strong>{{ selectedJob.error_message }}</p>
        </div>

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
            type="primary"
            plain
            @click="loadResourcesForSelectedJob"
            :loading="loadingResources"
          >
            刷新资源
          </el-button>
          <el-button @click="$router.push('/learning/history')">查看学习历史</el-button>
        </div>
      </template>
    </el-card>

    <AgentVisualization
      v-if="selectedRunId"
      :trace="timelineState.steps"
      :markers="timelineState.markers"
      :connection-status="connectionStatus"
      :legacy-partial="timelineState.replayCompleteness === 'legacy_partial'"
      @open-child-run="openChildRun"
    />

    <el-card v-if="selectedJob" class="resources-card">
      <template #header>
        <div class="status-head">
          <div>
            <span>{{ selectedJob.job_status === 'completed' ? '任务资源' : '任务资源预览' }}</span>
            <p class="section-tip">资源按任务维度展示；先选任务，再从该任务下选择任意一份资源阅读。</p>
          </div>
          <el-tag :type="selectedJob.job_status === 'completed' ? 'success' : 'info'" effect="plain">
            {{ resources.length }} 份资源
          </el-tag>
        </div>
      </template>

      <div v-loading="loadingResources">
        <el-empty
          v-if="selectedJob.job_status !== 'completed'"
          :description="selectedJob.job_status === 'failed' ? '该任务生成失败，当前没有可展示的资源。' : '该任务仍在生成中，完成后这里会展示本任务的资源。'"
        />
        <el-empty
          v-else-if="resourcesLoaded && !resources.length"
          description="该任务已完成，但暂时还没有查到资源内容。可以稍后再刷新一次。"
        />
        <template v-else-if="resources.length">
          <div class="resource-selector">
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
    </el-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generateApi, resourceApi, runApi } from '../api'
import { createRunEventClient } from '../api/runEvents'
import ResourceViewer from '../components/ResourceViewer.vue'
import AgentVisualization from '../components/AgentVisualization.vue'
import { useAppStore } from '../stores/app'
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

const learnerId =
  new URLSearchParams(window.location.search).get('learnerId') ||
  localStorage.getItem('last_learner_id') ||
  store.currentLearnerId ||
  ''
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
const timelineState = ref(createInitialTimelineState())
const connectionStatus = ref('idle')
let streamClient = null
let streamGeneration = 0

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

function taskLabel(task) {
  const prefix = task.job_status === 'running' || task.job_status === 'queued' ? '当前' : '历史'
  return `${prefix} / ${task.run_id.slice(0, 8).toUpperCase()} / ${task.topic || '未命名主题'} / ${formatDateTime(task.finished_at || task.created_at)}`
}

function persistSelectedJob() {
  localStorage.setItem('current_generation_run_id', selectedJob.value?.run_id || '')
  localStorage.setItem('current_generation_status', selectedJob.value?.job_status || '')
}

function resourceLabel(resource) {
  return `${resource.resource_type} / ${resource.difficulty} / ${resource.topic || '未命名主题'}`
}

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
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

async function loadJobs(preferDefault = false) {
  if (!learnerId) return
  loadingJobs.value = true
  try {
    const res = await generateApi.listJobs(learnerId)
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
  if (!learnerId || !selectedJob.value?.run_id || selectedJob.value.job_status !== 'completed') {
    resources.value = []
    resourcesLoaded.value = true
    selectedResourceId.value = ''
    return
  }

  loadingResources.value = true
  try {
    const res = await resourceApi.listByLearner(learnerId, { run_id: selectedJob.value.run_id })
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
  gap: 18px;
}

.hero-card,
.status-card,
.resources-card {
  padding: 22px;
  border-radius: 16px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.hero-card {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.hero-copy h2 {
  margin: 0;
  font-size: 28px;
}

.hero-copy p {
  margin: 10px 0 0;
  color: #667085;
  line-height: 1.7;
  max-width: 760px;
}

.status-head,
.status-actions {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.status-head p,
.section-tip {
  margin: 6px 0 0;
  color: #667085;
  font-size: 13px;
}

.task-selector {
  margin-bottom: 18px;
}

.task-select,
.resource-select {
  width: min(560px, 100%);
}

.job-summary p {
  margin: 0 0 10px;
  color: #1f2937;
}

.status-actions {
  justify-content: flex-end;
  margin-top: 18px;
  flex-wrap: wrap;
}

.resource-selector {
  margin-bottom: 18px;
}

@media (max-width: 920px) {
  .hero-card,
  .status-head {
    flex-direction: column;
  }
}
</style>
