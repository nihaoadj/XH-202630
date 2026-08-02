<template>
  <div class="resources-page">
    <section class="toolbar-card">
      <div>
        <h3>资源查看</h3>
        <p>{{ currentLearnerLabel }}。如果刚完成后台生成，可以按本次任务查看结果并直接下载。</p>
      </div>

      <div class="toolbar-form">
        <el-input v-model="learnerId" placeholder="画像编号（内部使用）" class="input" />
        <el-input v-model="runId" placeholder="任务编号（可选）" class="input" />
        <el-button type="primary" @click="loadResources">加载资源</el-button>
        <el-button @click="$router.push('/generate')">去生成新资源</el-button>
      </div>
    </section>

    <el-empty v-if="loaded && !resources.length" description="当前条件下还没有可展示的资源" />
    <ResourceViewer v-else :resources="resources" />
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
const runId = ref(route.query.runId || localStorage.getItem('current_generation_run_id') || '')
const resources = ref([])
const loaded = ref(false)
const currentLearnerLabel = computed(() => {
  const name =
    store.currentUserProfile?.display_name ||
    store.currentProfile?.learning_preferences?.metadata?.user_profile_snapshot?.display_name ||
    '当前用户'
  const direction = store.currentLearningDirectionName || localStorage.getItem('learning_direction_name') || '未选择方向'
  const task = runId.value ? ` · 任务 ${runId.value.slice(0, 8).toUpperCase()}` : ''
  return `${name} / ${direction}${task}`
})

async function loadResources() {
  try {
    const params = {}
    if (runId.value) {
      params.run_id = runId.value
    }
    const res = await resourceApi.listByLearner(learnerId.value, params)
    resources.value = res.data.resources || []
    loaded.value = true
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

.toolbar-card {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
  padding: 22px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
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

.input {
  width: 280px;
}

@media (max-width: 920px) {
  .toolbar-card {
    flex-direction: column;
  }

  .input {
    width: min(100%, 320px);
  }
}
</style>
