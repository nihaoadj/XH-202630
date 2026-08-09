<template>
  <div class="report-page">
    <section class="report-toolbar">
      <div>
        <h2>学习报告</h2>
        <p>{{ currentLearnerLabel }}</p>
      </div>
      <div class="report-actions">
        <el-input v-model="learnerId" placeholder="画像编号（内部使用）" class="report-input" />
        <el-button type="primary" @click="loadReport">查询</el-button>
      </div>
    </section>

    <ReportChart :data="report" />

    <el-row :gutter="20" style="margin-top: 20px;">
      <el-col :span="12">
        <el-card>
          <template #header>最近资源</template>
          <el-empty v-if="!recentResources.length" description="暂无资源" />
          <el-timeline v-else>
            <el-timeline-item
              v-for="item in recentResources"
              :key="item.resource_id"
              :timestamp="item.difficulty"
            >
              <strong>{{ item.resource_type }}</strong>
              <p>{{ item.topic || '未命名主题' }}</p>
              <p>{{ (item.knowledge_points || []).join('、') }}</p>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card>
          <template #header>最近反馈</template>
          <el-empty v-if="!recentFeedback.length" description="暂无反馈" />
          <el-table v-else :data="recentFeedback" style="width: 100%;">
            <el-table-column label="资源" min-width="180">
              <template #default="{ row }">
                {{ feedbackResourceLabel(row) }}
              </template>
            </el-table-column>
            <el-table-column prop="correct_rate" label="正确率" width="100">
              <template #default="{ row }">{{ Math.round(row.correct_rate * 100) }}%</template>
            </el-table-column>
            <el-table-column prop="decision" label="决策" width="120" />
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { reportApi } from '../api'
import { useAppStore } from '../stores/app'
import ReportChart from '../components/ReportChart.vue'

const store = useAppStore()
const learnerId = ref(localStorage.getItem('last_learner_id') || '')
const report = reactive({})
const recentResources = computed(() => report.recent_resources || [])
const recentFeedback = computed(() => report.recent_feedback || [])
const currentLearnerLabel = computed(() => {
  const name =
    store.currentUserProfile?.display_name ||
    store.currentProfile?.learning_preferences?.metadata?.user_profile_snapshot?.display_name ||
    '当前用户'
  const direction = store.currentLearningDirectionName || localStorage.getItem('learning_direction_name') || '未选择方向'
  return `${name} / ${direction}`
})

function feedbackResourceLabel(row) {
  const resource = recentResources.value.find((item) => item.resource_id === row.resource_id)
  if (resource) {
    return `${resource.resource_type} / ${resource.topic || '未命名主题'}`
  }
  return row.resource_id ? `资源 ${row.resource_id.slice(0, 8)}` : '未命名资源'
}

async function loadReport() {
  try {
    const res = await reportApi.get(learnerId.value)
    Object.assign(report, res.data)
  } catch (e) {
    console.error(e)
    ElMessage.error(e?.response?.data?.message || '报告查询失败')
  }
}

onMounted(loadReport)
</script>

<style scoped>
.report-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.report-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 22px;
  border-radius: 14px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
}

.report-toolbar h2 {
  margin: 0;
}

.report-toolbar p {
  margin: 8px 0 0;
  color: #667085;
}

.report-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.report-input {
  width: 260px;
}

@media (max-width: 920px) {
  .report-toolbar {
    flex-direction: column;
  }

  .report-input {
    width: min(100%, 320px);
  }
}
</style>
