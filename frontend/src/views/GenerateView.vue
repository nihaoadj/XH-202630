<template>
  <div class="generate-page">
    <section class="hero-card">
      <div>
        <h2>资源生成状态</h2>
        <p>提交后无需停留在原页面。任务完成后，这里会出现跳转资源页的按钮。</p>
      </div>
      <el-tag v-if="learningDirectionId" type="info">当前学习方向：{{ learningDirectionId }}</el-tag>
    </section>

    <el-card class="status-card">
      <template #header>
        <div class="status-head">
          <span>生成任务</span>
          <el-tag :type="statusTagType(job.status)">{{ statusLabel(job.status) }}</el-tag>
        </div>
      </template>

      <el-empty v-if="!job.runId" description="当前还没有生成任务。请先在新建学习方向的第 5 步发起生成。" />

      <template v-else>
        <p><strong>任务 ID：</strong>{{ job.runId }}</p>
        <p><strong>主题：</strong>{{ job.topic || '-' }}</p>
        <p><strong>学习画像：</strong>{{ job.learnerId || '-' }}</p>
        <p v-if="job.errorMessage"><strong>错误信息：</strong>{{ job.errorMessage }}</p>

        <div class="status-actions">
          <el-button
            v-if="job.status === 'completed'"
            type="primary"
            @click="goToResources"
          >
            查看生成资源
          </el-button>
          <el-button
            v-if="job.status === 'running' || job.status === 'queued'"
            @click="refreshStatus"
          >
            刷新状态
          </el-button>
          <el-button @click="$router.push('/learning/history')">查看学习历史</el-button>
        </div>
      </template>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { generateApi } from '../api'
import { useAppStore } from '../stores/app'

const route = useRoute()
const router = useRouter()
const store = useAppStore()

const learningDirectionId = computed(() => store.currentLearningDirectionId || localStorage.getItem('learning_direction_id') || '')

const pollTimer = ref(null)
const job = reactive({
  runId: route.query.runId || localStorage.getItem('current_generation_run_id') || '',
  status: localStorage.getItem('current_generation_status') || '',
  learnerId: route.query.learnerId || localStorage.getItem('last_learner_id') || store.currentLearnerId || '',
  topic: '',
  errorMessage: '',
})

function statusLabel(status) {
  return {
    queued: '排队中',
    running: '生成中',
    completed: '已完成',
    failed: '失败',
  }[status] || '未开始'
}

function statusTagType(status) {
  return {
    queued: 'info',
    running: 'warning',
    completed: 'success',
    failed: 'danger',
  }[status] || 'info'
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

async function refreshStatus() {
  if (!job.runId) return
  try {
    const res = await generateApi.getJobStatus(job.runId)
    job.status = res.data.job_status
    job.learnerId = res.data.learner_id
    job.topic = res.data.topic
    job.errorMessage = res.data.error_message || ''
    persistJobState()
    if (job.status === 'completed' || job.status === 'failed') {
      stopPolling()
    }
  } catch (error) {
    console.error(error)
    stopPolling()
    ElMessage.error(error?.response?.data?.message || '任务状态获取失败')
  }
}

function goToResources() {
  router.push({
    path: '/resources',
    query: {
      learnerId: job.learnerId,
      runId: job.runId,
    },
  })
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
.status-card {
  padding: 22px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.hero-card {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
}

.hero-card h2 {
  margin: 0;
}

.hero-card p {
  margin: 8px 0 0;
  color: #667085;
}

.status-head,
.status-actions {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.status-actions {
  justify-content: flex-end;
  margin-top: 18px;
  flex-wrap: wrap;
}

@media (max-width: 920px) {
  .hero-card {
    flex-direction: column;
  }
}
</style>
