<template>
  <div>
    <h2>学情报告</h2>
    <el-input v-model="learnerId" placeholder="输入学习者ID" style="width: 200px; margin-right: 10px;" />
    <el-button type="primary" @click="loadReport">查询</el-button>

    <el-divider />

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
              <p>{{ item.resource_id }}</p>
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
            <el-table-column prop="resource_id" label="资源ID" min-width="180" />
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
import { computed, onMounted, ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { reportApi } from '../api'
import ReportChart from '../components/ReportChart.vue'

const learnerId = ref(localStorage.getItem('last_learner_id') || 'stu_001')
const report = reactive({})
const recentResources = computed(() => report.recent_resources || [])
const recentFeedback = computed(() => report.recent_feedback || [])

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
