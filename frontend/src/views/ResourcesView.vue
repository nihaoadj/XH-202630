<template>
  <div class="resources-page">
    <section class="toolbar-card">
      <div>
        <h3>资源查看</h3>
        <p>{{ currentLearnerLabel }}。页面会默认展示当前生成任务，并支持切换查看历史任务资源。</p>
      </div>

      <div class="toolbar-form">
        <el-select
          v-model="selectedRunId"
          filterable
          placeholder="选择生成任务"
          class="task-select"
          @change="handleRunChange"
        >
          <el-option
            v-for="task in taskGroups"
            :key="task.runId"
            :label="task.label"
            :value="task.runId"
          />
        </el-select>
        <el-button type="primary" @click="loadResources">刷新任务</el-button>
        <el-button @click="$router.push('/generate')">去生成新资源</el-button>
      </div>
    </section>

    <el-card v-if="activeTask" class="summary-card">
      <div class="summary-row">
        <span>当前任务：{{ activeTask.shortRunId }}</span>
        <span>{{ activeTask.resources.length }} 份资源</span>
        <span>{{ activeTask.topic || '未命名主题' }}</span>
      </div>
    </el-card>

    <el-empty v-if="loaded && !activeResources.length" description="当前还没有可展示的任务资源" />
    <ResourceViewer v-else :resources="activeResources" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import { resourceApi } from '../api'
import { useAppStore } from '../stores/app'
import ResourceViewer from '../components/ResourceViewer.vue'

const route = useRoute()
const store = useAppStore()
const learnerId = ref(
  route.query.learnerId || store.currentLearnerId || localStorage.getItem('last_learner_id') || ''
)
const selectedRunId = ref(route.query.runId || localStorage.getItem('current_generation_run_id') || '')
const resources = ref([])
const loaded = ref(false)

const currentLearnerLabel = computed(() => {
  const name =
    store.currentUserProfile?.display_name ||
    store.currentProfile?.learning_preferences?.metadata?.user_profile_snapshot?.display_name ||
    '当前用户'
  const direction = store.currentLearningDirectionName || localStorage.getItem('learning_direction_name') || '未选择方向'
  return `${name} / ${direction}`
})

const taskGroups = computed(() => {
  const groups = new Map()
  for (const resource of resources.value) {
    const runId = resource.run_id || `resource:${resource.resource_id}`
    if (!groups.has(runId)) {
      groups.set(runId, {
        runId,
        shortRunId: runId.startsWith('resource:') ? '未关联任务' : runId.slice(0, 8).toUpperCase(),
        topic: resource.topic || '',
        resources: [],
      })
    }
    groups.get(runId).resources.push(resource)
  }
  return Array.from(groups.values()).map((task) => ({
    ...task,
    label: `${task.shortRunId} / ${task.resources.length} 份资源 / ${task.topic || '未命名主题'}`,
  }))
})

const activeTask = computed(() => {
  if (!taskGroups.value.length) return null
  return (
    taskGroups.value.find((item) => item.runId === selectedRunId.value) ||
    taskGroups.value[0]
  )
})

const activeResources = computed(() => activeTask.value?.resources || [])

function syncSelectedRun() {
  if (!taskGroups.value.length) {
    selectedRunId.value = ''
    return
  }
  const currentRunId = localStorage.getItem('current_generation_run_id') || ''
  if (selectedRunId.value && taskGroups.value.some((item) => item.runId === selectedRunId.value)) {
    return
  }
  if (currentRunId && taskGroups.value.some((item) => item.runId === currentRunId)) {
    selectedRunId.value = currentRunId
    return
  }
  selectedRunId.value = taskGroups.value[0].runId
}

function handleRunChange(value) {
  if (value && !value.startsWith('resource:')) {
    localStorage.setItem('current_generation_run_id', value)
  }
}

async function loadResources() {
  if (!learnerId.value) return
  try {
    const res = await resourceApi.listByLearner(learnerId.value)
    resources.value = res.data.resources || []
    loaded.value = true
    syncSelectedRun()
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '资源加载失败')
  }
}

onMounted(loadResources)
</script>

<style scoped>
.resources-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.toolbar-card,
.summary-card {
  padding: 22px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.toolbar-card {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
}

.toolbar-card h3 {
  margin: 0;
}

.toolbar-card p {
  margin: 8px 0 0;
  color: #667085;
}

.toolbar-form {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.task-select {
  width: min(420px, 100%);
}

.summary-row {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
  color: #475467;
}

@media (max-width: 920px) {
  .toolbar-card {
    flex-direction: column;
  }

  .task-select {
    width: min(100%, 360px);
  }
}
</style>
