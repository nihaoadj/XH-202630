<template>
  <div class="generate-page">
    <section class="control-panel">
      <div class="panel-title">
        <div>
          <span class="eyebrow">Resource Generation</span>
          <h3>学习资源生成</h3>
        </div>
      </div>

      <div class="task-selector">
        <div class="selector-field">
          <span>学习画像</span>
          <el-select
            v-model="selectedLearnerId"
            filterable
            placeholder="选择学习画像"
            class="task-select"
            popper-class="refined-select-dropdown profile-select-dropdown"
            @change="handleProfileChange"
          >
            <el-option
              v-for="item in profileOptions"
              :key="item.learner_id"
              :label="item.label"
              :value="item.learner_id"
            >
              <div class="profile-option">
                <span>{{ item.label }}</span>
                <el-tooltip content="删除学习画像" placement="right">
                  <el-button
                    class="profile-delete"
                    text
                    circle
                    :icon="Delete"
                    aria-label="删除学习画像"
                    @mousedown.stop
                    @click.stop="deleteProfile(item)"
                  />
                </el-tooltip>
              </div>
            </el-option>
          </el-select>
        </div>
        <div class="selector-field">
          <span>资源批次</span>
          <el-select
            v-model="selectedRunId"
            filterable
            :disabled="!jobs.length"
            :placeholder="jobs.length ? '选择要查看的生成任务' : '暂无资源批次'"
            class="task-select"
            popper-class="refined-select-dropdown"
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
      <div v-else class="job-summary">
        <div class="summary-item">
          <span>学习方向</span>
          <strong>{{ learningDirectionName || '-' }}</strong>
        </div>
        <div class="summary-item">
          <span>任务编号</span>
          <strong>-</strong>
        </div>
        <div class="summary-item">
          <span>任务状态</span>
          <strong class="status-value status-idle">尚未生成</strong>
        </div>
        <div class="summary-item">
          <span>资源数量</span>
          <strong>0 份</strong>
        </div>
        <div class="summary-item">
          <span>创建时间</span>
          <strong>-</strong>
        </div>
        <div class="summary-item">
          <span>完成时间</span>
          <strong>-</strong>
        </div>
      </div>

      <p v-if="selectedJob?.error_message" class="error-message">{{ selectedJob.error_message }}</p>

      <div class="status-actions">
        <el-button
          v-if="selectedJob && (selectedJob.job_status === 'running' || selectedJob.job_status === 'queued')"
          class="status-action status-action-refresh"
          :icon="Refresh"
          @click="refreshStatus"
        >
          刷新状态
        </el-button>
        <el-button
          v-if="selectedJob && selectedJob.job_status === 'failed'"
          class="status-action status-action-retry"
          :icon="RefreshRight"
          @click="retryGeneration"
          :loading="retrying"
        >
          重新生成
        </el-button>
        <el-button
          v-if="selectedJob && selectedJob.job_status === 'completed'"
          class="status-action status-action-resource"
          :icon="hasRetryableResources ? RefreshRight : Refresh"
          @click="hasRetryableResources ? regeneratePendingResources() : loadResourcesForSelectedJob()"
          :loading="hasRetryableResources ? retrying : loadingResources"
        >
          {{ hasRetryableResources ? `重新生成失败资源（${retryableResourceTypes.length}）` : '刷新资源' }}
        </el-button>
        <el-button
          v-if="selectedJob"
          class="status-action status-action-append"
          :icon="Plus"
          :loading="appendingResources"
          @click="appendResources"
        >
          追加资源
        </el-button>
        <el-button class="status-action status-action-history" :icon="Clock" @click="$router.push('/learning/history')">
          查看学习历史
        </el-button>
      </div>
    </section>

    <section v-if="selectedJob" class="studio-grid">
      <div class="process-panel">
        <div class="panel-title compact">
          <div>
            <span class="eyebrow">Workflow Trace</span>
            <h3>生成过程</h3>
          </div>
          <el-tag :type="connectionStatus === 'live' ? 'success' : 'info'" effect="plain">
            {{ connectionStatus === 'live' ? '节点级同步' : '任务记录' }}
          </el-tag>
        </div>
        <AgentVisualization
          v-if="selectedRunId"
          :trace="timelineState.steps"
          :markers="timelineState.markers"
          :connection-status="connectionStatus"
          :legacy-partial="timelineState.replayCompleteness === 'legacy_partial'"
          :resource-executions="timelineState.resourceExecutions"
          :resource-progress-summary="selectedJob?.resource_progress_summary || timelineState.resourceProgressSummary"
          :retrying-resource-key="retryingResourceKey"
          :retry-enabled="['completed', 'failed'].includes(selectedJob.job_status)"
          @open-child-run="openChildRun"
          @open-resource="openGeneratedResource"
          @retry-resource="retryResource"
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
            v-if="selectedJob.job_status !== 'completed' && !resources.length"
            :description="selectedJob.job_status === 'failed' ? '该任务生成失败，当前没有可展示的资源。' : '该任务仍在生成中，完成后这里会展示本任务的资源。'"
          />
          <el-empty
            v-else-if="resourcesLoaded && !resources.length"
            description="该任务已完成，但暂时还没有查到资源内容。可以稍后再刷新一次。"
          />
          <template v-if="resources.length">
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
                popper-class="refined-select-dropdown"
              >
                <el-option
                  v-for="item in resources"
                  :key="item.resource_id"
                  :label="resourceLabel(item)"
                  :value="item.resource_id"
                />
              </el-select>
              <el-button class="learning-mode-action" @click="enterLearningMode">
                <el-icon><Reading /></el-icon>
                <span>进入学习模式</span>
                <el-icon class="mode-arrow"><ArrowRight /></el-icon>
              </el-button>
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

    <el-dialog
      v-model="appendDialogVisible"
      title="追加学习资源"
      width="min(520px, calc(100vw - 32px))"
      :close-on-click-modal="false"
    >
      <p class="append-resource-hint">请选择要加入当前资源批次的资源类型。</p>
      <el-checkbox-group v-model="selectedAppendResourceTypes" class="append-resource-options">
        <el-checkbox
          v-for="option in appendResourceOptions"
          :key="option.type"
          :label="option.type"
          :disabled="option.alreadyIncluded"
        >
          {{ option.type }}<span v-if="option.alreadyIncluded" class="append-resource-existing">（本批次已有）</span>
        </el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="appendDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="appendingResources" @click="confirmAppendResources">开始追加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowRight, Clock, Delete, Plus, Reading, Refresh, RefreshRight } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
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
const router = useRouter()

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
const retryingResourceKey = ref('')
const appendingResources = ref(false)
const appendDialogVisible = ref(false)
const selectedAppendResourceTypes = ref([])
const selectedRunId = ref(initialRunId)
const selectedResourceId = ref('')
const profiles = ref([])
const tracks = ref([])
const timelineState = ref(createInitialTimelineState())
const connectionStatus = ref('idle')
let streamClient = null
let streamGeneration = 0
let publishedResourceRefreshTimer = null

const activeProfile = computed(
  () => profiles.value.find((item) => item.learner_id === selectedLearnerId.value) || null
)
const profileOptions = computed(() =>
  profiles.value.map((profile) => ({
    ...profile,
    label: `${profileDisplayName(profile)} / ${resolveTrackName(profile.knowledge_base_id)} / ${profile.skill_level || '未分级'} / 创建于 ${profileCreatedAt(profile)}`,
  }))
)
const selectedJob = computed(
  () => jobs.value.find((item) => item.run_id === selectedRunId.value) || null
)
const shortRunId = computed(() => (selectedJob.value?.run_id ? selectedJob.value.run_id.slice(0, 8).toUpperCase() : '-'))
const selectedResource = computed(
  () => resources.value.find((item) => item.resource_id === selectedResourceId.value) || null
)
const retryableResourceTypes = computed(() => {
  const retryableStates = new Set(['failed', 'human_review', 'revision_requested'])
  const types = (timelineState.value.resourceExecutions || [])
    .filter((item) => retryableStates.has(item.resource_execution_state))
    .map((item) => item.resource_type)
    .filter(Boolean)
  return [...new Set(types)]
})
const hasRetryableResources = computed(() => (
  selectedJob.value?.job_status === 'completed' && retryableResourceTypes.value.length > 0
))
const supportedAppendResourceTypes = ['讲义', '实操指南', '分阶测试题', '复习清单', '案例分析']
const appendResourceOptions = computed(() => {
  const existingTypes = new Set(selectedJob.value?.request_payload?.resource_types || [])
  return supportedAppendResourceTypes.map((type) => ({
    type,
    alreadyIncluded: existingTypes.has(type),
  }))
})

function enterLearningMode() {
  if (!selectedJob.value || !selectedResource.value) return
  router.push({
    path: '/resources',
    query: {
      learnerId: selectedLearnerId.value,
      runId: selectedJob.value.batch_id || selectedJob.value.run_id,
    },
  })
}

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

async function openGeneratedResource(item) {
  if (!item?.resource_id || !selectedJob.value) return
  if (!resources.value.some((resource) => resource.resource_id === item.resource_id)) {
    await loadResourcesForSelectedJob()
  }
  if (resources.value.some((resource) => resource.resource_id === item.resource_id)) {
    selectedResourceId.value = item.resource_id
  }
}

function profileCreatedAt(profile) {
  return profile?.created_at ? formatDateTime(profile.created_at) : '时间未知'
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

function cancelPublishedResourceRefresh() {
  if (publishedResourceRefreshTimer !== null) {
    clearTimeout(publishedResourceRefreshTimer)
    publishedResourceRefreshTimer = null
  }
}

function queuePublishedResourceRefresh(runId) {
  if (runId !== selectedRunId.value || publishedResourceRefreshTimer !== null) return
  // A resource_published event is appended only after the resource itself is
  // durable. Coalesce a burst from the same reviewer/finalizer node so the
  // resource list and job summary refresh once rather than once per resource.
  publishedResourceRefreshTimer = setTimeout(() => {
    publishedResourceRefreshTimer = null
    if (runId === selectedRunId.value) void refreshStatus()
  }, 0)
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
      if (event.event_type === 'resource_published') queuePublishedResourceRefresh(runId)
    },
    onTerminal: async () => {
      if (generation !== streamGeneration) return
      connectionStatus.value = 'terminal'
      await refreshStatus()
      // The durable Run event can be observed immediately before the
      // background task marks its GenerationJob completed. Keep a short
      // fallback poll only for that hand-off window so the UI cannot remain
      // stuck at "generating" after the SSE stream has ended.
      if (selectedJob.value && ['queued', 'running'].includes(selectedJob.value.job_status)) {
        startPolling()
      }
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
  if (initialRunId && items.some((item) => item.run_id === initialRunId)) return initialRunId
  const currentJob = items.find((item) => item.job_status === 'running' || item.job_status === 'queued')
  if (currentJob) return currentJob.run_id
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
    jobs.value = (res.data.items || []).filter((item) => !item.superseded_by_run_id)
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
  if (!selectedLearnerId.value || !selectedJob.value?.run_id) {
    resources.value = []
    resourcesLoaded.value = true
    selectedResourceId.value = ''
    return
  }

  loadingResources.value = true
  try {
    const res = await resourceApi.listByLearner(selectedLearnerId.value, {
      // This page is scoped to the selected task Run. Cross-run aggregation
      // belongs to the learner-facing Learning Resources page.
      run_id: selectedJob.value.run_id,
      page: 1,
      page_size: 100,
    })
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
    timelineState.value = applyRunSnapshot(timelineState.value, nextJob)
    persistSelectedJob()

    const hasPublishedResources = Number(nextJob.resource_progress_summary?.published || 0) > 0
    if (nextJob.job_status === 'completed') {
      stopPolling()
      await loadResourcesForSelectedJob()
    } else if (hasPublishedResources) {
      await loadResourcesForSelectedJob()
    } else if (nextJob.job_status === 'failed') {
      stopPolling()
    }
  } catch (error) {
    console.error(error)
    stopPolling()
    ElMessage.error(error?.response?.data?.message || '任务状态获取失败')
  }
}

async function refreshJobs() {
  await loadJobs(false)
  if (selectedJob.value?.job_status === 'completed' || selectedJob.value?.resource_progress_summary?.published) {
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
  if (selectedJob.value.job_status === 'completed' || selectedJob.value.resource_progress_summary?.published) {
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
  if (selectedJob.value?.job_status === 'completed' || selectedJob.value?.resource_progress_summary?.published) {
    await loadResourcesForSelectedJob()
  } else {
    resourcesLoaded.value = true
  }
  await startRealtime(selectedRunId.value)
}

async function deleteProfile(profile) {
  try {
    await ElMessageBox.confirm(
      `将删除“${profile.label}”及其关联画像数据，此操作无法撤销。`,
      '删除学习画像',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
    await profileApi.delete(profile.learner_id)
    profiles.value = profiles.value.filter((item) => item.learner_id !== profile.learner_id)
    if (selectedLearnerId.value === profile.learner_id) {
      selectedLearnerId.value = profiles.value[0]?.learner_id || ''
      selectedRunId.value = ''
      selectedResourceId.value = ''
      if (selectedLearnerId.value) {
        syncProfileContext()
        await loadJobs(true)
      } else {
        jobs.value = []
        localStorage.removeItem('last_learner_id')
        localStorage.removeItem('current_generation_run_id')
      }
    }
    ElMessage.success('学习画像已删除')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '删除学习画像失败')
  }
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
  const failedJob = selectedJob.value
  const payload = failedJob?.request_payload
  if (!failedJob?.run_id || !payload?.learner_id || !Array.isArray(payload?.resource_types) || !payload.resource_types.length) {
    ElMessage.warning('该任务缺少原始生成参数，无法保证重试内容一致')
    return
  }

  retrying.value = true
  resources.value = []
  resourcesLoaded.value = false
  selectedResourceId.value = ''
  stopPolling()

  try {
    const batchId = selectedJob.value?.batch_id || selectedJob.value?.run_id
    const res = await generateApi.continueBatch(batchId, {
      learner_id: failedJob.learner_id,
      resource_types: payload.resource_types,
      instructions: payload.constraints?.continuation_instructions || '重新生成失败任务的学习材料。',
      source_run_id: failedJob.run_id,
    })
    selectedRunId.value = res.data.run_id
    await loadJobs(false)
    await startRealtime(selectedRunId.value)
    ElMessage.success('已在原资源批次中重新发起生成任务')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '重新生成失败')
  } finally {
    retrying.value = false
  }
}

function appendResources() {
  const sourceJob = selectedJob.value
  const payload = sourceJob?.request_payload
  if (!sourceJob?.learner_id || !payload) {
    ElMessage.warning('该任务缺少追加资源所需的原始参数')
    return
  }
  selectedAppendResourceTypes.value = appendResourceOptions.value
    .filter((option) => !option.alreadyIncluded)
    .map((option) => option.type)
  appendDialogVisible.value = true
}

async function regeneratePendingResources() {
  const sourceJob = selectedJob.value
  const resourceTypes = retryableResourceTypes.value
  if (!sourceJob?.learner_id || !resourceTypes.length) {
    ElMessage.warning('当前任务没有可重新生成的资源')
    return
  }
  retrying.value = true
  try {
    const batchId = sourceJob.batch_id || sourceJob.run_id
    const response = await generateApi.continueBatch(batchId, {
      learner_id: sourceJob.learner_id,
      resource_types: resourceTypes,
      source_run_id: sourceJob.run_id,
      replace_existing_types: true,
      instructions: `统一重新生成本任务中未通过审核的资源：${resourceTypes.join('、')}。`,
    })
    selectedRunId.value = response.data.run_id
    localStorage.setItem('current_generation_run_id', selectedRunId.value)
    resources.value = []
    resourcesLoaded.value = false
    selectedResourceId.value = ''
    await loadJobs(false)
    await startRealtime(selectedRunId.value)
    ElMessage.success(`已创建一个新任务，统一重新生成：${resourceTypes.join('、')}`)
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '重新生成失败资源失败')
  } finally {
    retrying.value = false
  }
}

async function confirmAppendResources() {
  const sourceJob = selectedJob.value
  const resourceTypes = [...new Set(selectedAppendResourceTypes.value)]
  if (!sourceJob?.learner_id || !resourceTypes.length) {
    ElMessage.warning('请至少选择一种要追加的资源类型')
    return
  }
  appendingResources.value = true
  try {
    const batchId = sourceJob.batch_id || sourceJob.run_id
    const response = await generateApi.continueBatch(batchId, {
      learner_id: sourceJob.learner_id,
      resource_types: resourceTypes,
      instructions: '追加指定类型的学习资源，并与本批次已有资源保持衔接。',
      source_run_id: sourceJob.run_id,
    })
    selectedRunId.value = response.data.run_id
    localStorage.setItem('current_generation_run_id', selectedRunId.value)
    resources.value = []
    resourcesLoaded.value = false
    selectedResourceId.value = ''
    await loadJobs(false)
    await startRealtime(selectedRunId.value)
    appendDialogVisible.value = false
    ElMessage.success(`已追加：${resourceTypes.join('、')}`)
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '追加资源失败')
  } finally {
    appendingResources.value = false
  }
}

async function retryResource(item) {
  const sourceJob = selectedJob.value
  const payload = sourceJob?.request_payload
  if (!sourceJob?.learner_id || !payload || !item?.resource_type) {
    ElMessage.warning('该资源缺少重新生成所需的任务参数')
    return
  }

  const key = item.key || `${item.resource_spec_id}:${item.representation || 'text'}`
  retryingResourceKey.value = key
  try {
    const batchId = sourceJob.batch_id || sourceJob.run_id
    const response = await generateApi.continueBatch(batchId, {
      learner_id: sourceJob.learner_id,
      resource_types: [item.resource_type],
      source_run_id: sourceJob.run_id,
      replace_existing_types: true,
      instructions: `重新生成本批次的${item.resource_type}，用新版本替换学习列表中的旧版本。`,
    })
    selectedRunId.value = response.data.run_id
    localStorage.setItem('current_generation_run_id', selectedRunId.value)
    resources.value = []
    resourcesLoaded.value = false
    selectedResourceId.value = ''
    await loadJobs(false)
    await startRealtime(selectedRunId.value)
    ElMessage.success(`已在当前批次重新生成${item.resource_type}`)
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.detail || '重新生成资源失败')
  } finally {
    retryingResourceKey.value = ''
  }
}

onMounted(async () => {
  await loadProfiles()
  await loadJobs(true)
  if (selectedJob.value?.job_status === 'completed' || selectedJob.value?.resource_progress_summary?.published) {
    await loadResourcesForSelectedJob()
  } else {
    resourcesLoaded.value = true
  }
  await startRealtime(selectedRunId.value)
})

onBeforeUnmount(() => {
  cancelPublishedResourceRefresh()
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
  color: #2058a7;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0;
  text-transform: uppercase;
}

.summary-item span {
  display: block;
  color: #6a7689;
  font-size: 13px;
  margin-bottom: 5px;
}

.control-panel,
.process-panel,
.resources-panel,
.empty-studio {
  padding: 20px 24px;
}

.control-panel {
  padding-top: 14px;
  padding-bottom: 14px;
}

.panel-title {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
  padding-bottom: 10px;
  border-bottom: 1px solid #e4ebf3;
}

.panel-title.compact {
  padding-bottom: 14px;
  margin-bottom: 18px;
}

.panel-title h3 {
  margin: 3px 0 0;
  font-size: 19px;
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
  gap: 12px;
  margin: 10px 0;
  max-width: none;
}

.selector-field {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  column-gap: 18px;
  min-width: 0;
  min-height: 54px;
  padding: 7px 14px;
  border: 1px solid #d6e0ec;
  border-radius: 8px;
  background: linear-gradient(180deg, #ffffff, #f8fbff);
}

.selector-field span {
  margin: 0;
  color: #63728a;
  font-size: 13px;
  font-weight: 700;
}

.selector-field :deep(.el-select__wrapper) {
  min-height: 36px;
  padding: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.selector-field :deep(.el-select__placeholder),
.selector-field :deep(.el-select__selected-item) {
  color: #172033;
  font-size: 15px;
  font-weight: 600;
}

.task-select {
  width: 100%;
}

:deep(.refined-select-dropdown.el-popper) {
  overflow: hidden;
  border: 1px solid #d8e3ef;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 16px 36px rgba(30, 52, 80, 0.14);
}

:deep(.refined-select-dropdown .el-popper__arrow::before) {
  border-color: #d8e3ef;
  background: #fff;
}

:deep(.refined-select-dropdown .el-select-dropdown__list) {
  padding: 6px;
}

:deep(.refined-select-dropdown .el-select-dropdown__item) {
  height: 44px;
  margin: 2px 0;
  padding: 0 12px;
  border-radius: 7px;
  color: #41536c;
  font-size: 14px;
  font-weight: 600;
  line-height: 44px;
}

:deep(.refined-select-dropdown .el-select-dropdown__item.hover),
:deep(.refined-select-dropdown .el-select-dropdown__item:hover) {
  background: #f1f6fb;
  color: #204f80;
}

:deep(.refined-select-dropdown .el-select-dropdown__item.is-selected) {
  background: #e8f3f1;
  color: #216557;
  font-weight: 750;
}

.profile-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  width: 100%;
}

.profile-option > span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.profile-delete {
  flex: 0 0 auto;
  width: 28px;
  height: 28px;
  opacity: 0;
  color: #a65a53;
}

:deep(.profile-select-dropdown .el-select-dropdown__item:hover) .profile-delete,
:deep(.profile-select-dropdown .el-select-dropdown__item.is-selected) .profile-delete {
  opacity: 1;
}

.profile-delete:hover,
.profile-delete:focus-visible {
  background: #fff0ee;
  color: #b9483e;
}

.job-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 0.95fr)) repeat(3, minmax(0, 1.05fr));
  border: 1px solid #d9e1ec;
  border-radius: 8px;
  overflow: hidden;
  background: #f8fbff;
}

.summary-item {
  min-height: 58px;
  padding: 9px 14px;
  border-right: 1px solid #d9e1ec;
  background: linear-gradient(180deg, #fff, #f7fafc);
}

.summary-item:last-child {
  border-right: 0;
}

.summary-item strong {
  display: block;
  color: #172033;
  font-size: 15px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.summary-item .status-value {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
}

.status-value::before {
  content: '';
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #7a8798;
}

.status-completed {
  color: #2058a7;
}

.status-completed::before {
  background: #4a90ff;
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
  border-color: #2058a7;
  background: #2058a7;
  color: #fff;
}

.status-action:hover,
.status-action:focus-visible {
  transform: translateY(-1px);
  box-shadow: 0 8px 18px rgb(37 73 111 / 10%);
}

.status-action-refresh,
.status-action-resource {
  border-color: #c9d9ec;
  background: #fff;
  color: #315878;
}

.status-action-refresh:hover,
.status-action-resource:hover {
  border-color: #93bce6;
  background: #f5faff;
  color: #1e609e;
}

.status-action-append {
  border-color: #b7ddd3;
  background: #f4fbf8;
  color: #216b5a;
}

.status-action-append:hover {
  border-color: #76bba9;
  background: #e9f7f1;
}

.status-action-retry {
  border-color: #edc486;
  background: linear-gradient(135deg, #fffaf0, #fff3dc);
  color: #a35d12;
}

.status-action-retry:hover {
  border-color: #dd9b43;
  background: #ffedcd;
}

.status-action-history {
  border-color: transparent;
  background: #f1f5f9;
  color: #52647c;
}

.status-action-history:hover,
.status-action-history:focus-visible {
  border-color: #c8d7e8;
  background: #eef5fc;
  color: #285d98;
}

.studio-grid {
  display: grid;
  grid-template-columns: minmax(300px, 0.42fr) minmax(620px, 1.58fr);
  gap: 20px;
  align-items: start;
}

.process-panel,
.resources-panel {
  min-width: 0;
}

.process-panel {
  position: sticky;
  top: 16px;
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

.process-panel :deep(.workflow-timeline) {
  max-height: min(680px, calc(100vh - 180px));
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

.resource-toolbar > .el-button {
  flex: 0 0 auto;
}

.learning-mode-action {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-width: 148px;
  height: 38px;
  border-color: #2058a7;
  background: #2058a7;
  color: #fff;
  font-weight: 700;
}

.learning-mode-action:hover,
.learning-mode-action:focus-visible {
  border-color: #17447e;
  background: #17447e;
  color: #fff;
}

.learning-mode-action .mode-arrow {
  margin-left: 1px;
  font-size: 14px;
  transition: transform .18s ease;
}

.learning-mode-action:hover .mode-arrow {
  transform: translateX(2px);
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

.append-resource-hint {
  margin: 0 0 14px;
  color: #5d6b82;
  font-size: 14px;
}

.append-resource-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px 16px;
}

.append-resource-options :deep(.el-checkbox) {
  min-width: 0;
  margin-right: 0;
}

.append-resource-existing {
  color: #98a4b5;
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

  .process-panel {
    position: static;
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

  .append-resource-options {
    grid-template-columns: 1fr;
  }

}
</style>

