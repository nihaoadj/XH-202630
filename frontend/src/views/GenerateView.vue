<template>
  <div>
    <h2>生成个性化学习资源</h2>
    <el-form :model="form" label-width="120px">
      <el-form-item label="学习者ID">
        <el-input v-model="form.learner_id" />
      </el-form-item>
      <el-form-item label="学历">
        <el-input v-model="profile.education" />
      </el-form-item>
      <el-form-item label="专业">
        <el-input v-model="profile.major" />
      </el-form-item>
      <el-form-item label="技能水平">
        <el-select v-model="profile.skill_level">
          <el-option label="初级" value="初级" />
          <el-option label="中级" value="中级" />
          <el-option label="高级" value="高级" />
        </el-select>
      </el-form-item>
      <el-form-item label="学习目标">
        <el-input v-model="profile.learning_goal" type="textarea" />
      </el-form-item>
      <el-form-item label="学习主题">
        <el-input v-model="form.topic" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" @click="onSubmit" :loading="loading">生成资源</el-button>
      </el-form-item>
    </el-form>

    <el-divider />

    <h3>生成结果</h3>
    <AgentVisualization :trace="result.trace" />
    <ResourceViewer :resources="result.resources" />
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { learnerApi, generateApi } from '../api'
import AgentVisualization from '../components/AgentVisualization.vue'
import ResourceViewer from '../components/ResourceViewer.vue'

const form = reactive({
  learner_id: 'stu_001',
  topic: '工业互联网边缘计算网关配置',
})

const profile = reactive({
  learner_id: 'stu_001',
  education: '本科',
  major: '计算机科学与技术',
  theory_scores: { '工业互联网架构': 65, 'MQTT': 70, 'OPC UA': 40 },
  skill_level: '初级',
  weak_points: ['OPC UA', '边缘计算网关配置'],
  strong_points: ['Python 编程'],
  learning_goal: '掌握工业互联网数据采集与边缘计算',
})

const loading = ref(false)
const result = reactive({ resources: [], trace: [] })

async function onSubmit() {
  loading.value = true
  try {
    await learnerApi.createProfile({ ...profile, learner_id: form.learner_id })
    const res = await generateApi.generate({
      learner_id: form.learner_id,
      topic: form.topic,
      resource_types: ['讲义', '实操指南', '分阶测试题'],
    })
    result.resources = res.data.resources
    result.trace = res.data.trace
  } catch (e) {
    console.error(e)
    alert('生成失败，请检查后端服务与 API Key')
  } finally {
    loading.value = false
  }
}
</script>
