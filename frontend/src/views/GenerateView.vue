<template>
  <div class="generate-page">
    <section class="hero-card">
      <div class="hero-copy">
        <h2>资源生成状态</h2>
        <p>资源生成完成后会直接展示在当前页面，你可以点开对应资源查看内容、知识点和下载入口，不再单独跳到资源查看页。</p>
      </div>
      <el-tag v-if="learningDirectionName" type="info" effect="plain">
        当前学习方向：{{ learningDirectionName }}
      </el-tag>
    </section>

    <el-card class="status-card">
      <template #header>
        <div class="status-head">
          <span>生成任务</span>
          <el-tag :type="statusTagType(job.status)">{{ statusLabel(job.status) }}</el-tag>
        </div>
      </template>

      <el-empty
        v-if="!job.runId"
        description="当前还没有生成任务。请先在学习方向流程中完成诊断并发起资源生成。"
      />

      <template v-else>
        <div class="job-summary">
          <p><strong>用户：</strong>{{ currentDisplayName }}</p>
          <p><strong>主题：</strong>{{ job.topic || '-' }}</p>
          <p><strong>任务编号：</strong>{{ shortRunId }}</p>
          <p v-if="job.errorMessage"><strong>错误信息：</strong>{{ job.errorMessage }}</p>
        </div>

        <div class="status-actions">
          <el-button
            v-if="job.status === 'running' || job.status === 'queued'"
            @click="refreshStatus"
          >
            刷新状态
          </el-button>
          <el-button
            v-if="job.status === 'completed'"
            type="primary"
            plain
            @click="loadResources"
            :loading="loadingResources"
          >
            刷新资源
          </el-button>
          <el-button @click="$router.push('/learning/history')">查看学习历史</el-button>
        </div>
      </template>
    </el-card>

    <el-card v-if="job.runId && job.status === 'completed'" class="resources-card">
      <template #header>
        <div class="status-head">
          <div>
            <span>本次生成资源</span>
            <p class="section-tip">点击下方资源卡片即可查看生成结果与引用来源。</p>
          </div>
          <el-tag type="success" effect="plain">{{ resources.length }} 份资源</el-tag>
        </div>
      </template>

      <div v-loading="loadingResources">
        <el-empty
          v-if="resourcesLoaded && !resources.length"
          description="任务已完成，但暂时还没有查到资源内容。可以稍后再刷新一次。"
        />
        <ResourceViewer v-else-if="resources.length" :resources="resources" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { generateApi, resourceApi } from '../api'
import ResourceViewer from '../components/ResourceViewer.vue'
import { useAppStore } from '../stores/app'

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

const pollTimer = ref(null)
const loadingResources = ref(false)
const resourcesLoaded = ref(false)
const resources = ref([])

const job = reactive({
  runId: new URLSearchParams(window.location.search).get('runId') || localStorage.getItem('current_generation_run_id') || '',
  status: localStorage.getItem('current_generation_status') || '',
  learnerId:
    new URLSearchParams(window.location.search).get('learnerId') ||
    localStorage.getItem('last_learner_id') ||
    store.currentLearnerId ||
    '',
  topic: '',
  errorMessage: '',
})

const shortRunId = computed(() => (job.runId ? job.runId.slice(0, 8).toUpperCase() : '-'))

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

function persistJobState() {
  localStorage.setItem('current_generation_run_id', job.runId || '')
  localStorage.setItem('current_generation_status', job.status || '')
}

function stopPolling() {
  if (pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

function startPolling() {
  stopPolling()
  pollTimer.value = setInterval(refreshStatus, 5000)
}

async function loadResources() {
  if (!job.learnerId) return
  loadingResources.value = true
  try {
    const params = job.runId ? { run_id: job.runId } : {}
    const res = await resourceApi.listByLearner(job.learnerId, params)
    resources.value = res.data.resources || []
    resourcesLoaded.value = true
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '资源列表加载失败')
  } finally {
    loadingResources.value = false
  }
}

async function refreshStatus() {
  if (!job.runId) return
  try {
    const res = await generateApi.getJobStatus(job.runId)
    job.status = res.data.job_status
    job.learnerId = res.data.learner_id
    job.topic = res.data.topic
    job.errorMessage = res.data.error_message || ''
    persistJobState()

    if (job.status === 'completed') {
      stopPolling()
      await loadResources()
    } else if (job.status === 'failed') {
      stopPolling()
    }
  } catch (error) {
    console.error(error)
    stopPolling()
    ElMessage.error(error?.response?.data?.message || '任务状态获取失败')
  }
}

if (job.runId) {
  refreshStatus()
  if (job.status === 'queued' || job.status === 'running' || !job.status) {
    startPolling()
  }
}

onBeforeUnmount(stopPolling)
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

.job-summary p {
  margin: 0 0 10px;
  color: #1f2937;
}

.status-actions {
  justify-content: flex-end;
  margin-top: 18px;
  flex-wrap: wrap;
}

@media (max-width: 920px) {
  .hero-card,
  .status-head {
    flex-direction: column;
  }
}
</style>
