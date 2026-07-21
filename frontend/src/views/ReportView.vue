<template>
  <div>
    <h2>学情报告</h2>
    <el-input v-model="learnerId" placeholder="输入学习者ID" style="width: 200px; margin-right: 10px;" />
    <el-button type="primary" @click="loadReport">查询</el-button>

    <el-divider />

    <ReportChart :data="report" />
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { reportApi } from '../api'
import ReportChart from '../components/ReportChart.vue'

const learnerId = ref('stu_001')
const report = reactive({})

async function loadReport() {
  const res = await reportApi.get(learnerId.value)
  Object.assign(report, res.data)
}
</script>
