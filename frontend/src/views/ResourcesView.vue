<template>
  <div class="resources-page">
    <section class="toolbar-card">
      <div>
        <h3>资源查看</h3>
        <p>按学习者查看历史生成资源。若刚完成后台生成，可按本次任务查看结果并直接下载。</p>
      </div>

      <div class="toolbar-form">
        <el-input v-model="learnerId" placeholder="输入学习者 ID" class="input" />
        <el-input v-model="runId" placeholder="输入任务 ID（可选）" class="input" />
        <el-button type="primary" @click="loadResources">加载资源</el-button>
        <el-button @click="$router.push('/generate')">去生成新资源</el-button>
      </div>
    </section>

    <el-empty v-if="loaded && !resources.length" description="当前条件下还没有可展示的资源" />
    <ResourceViewer v-else :resources="resources" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRoute } from 'vue-router'
import { resourceApi } from '../api'
import { useAppStore } from '../stores/app'
import ResourceViewer from '../components/ResourceViewer.vue'

const route = useRoute()
const store = useAppStore()
const learnerId = ref(
  route.query.learnerId || store.currentLearnerId || localStorage.getItem('last_learner_id') || 'stu_001'
)
const runId = ref(route.query.runId || localStorage.getItem('current_generation_run_id') || '')
const resources = ref([])
const loaded = ref(false)

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
