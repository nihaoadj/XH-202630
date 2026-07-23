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
      <el-form-item label="学习者类型">
        <el-select v-model="profile.learner_type" filterable allow-create default-first-option>
          <el-option label="初学者" value="初学者" />
          <el-option label="有基础学习者" value="有基础学习者" />
          <el-option label="进阶学习者" value="进阶学习者" />
        </el-select>
      </el-form-item>
      <el-form-item label="专业">
        <el-input v-model="profile.major" />
      </el-form-item>
      <el-form-item label="技能水平">
        <el-select v-model="profile.skill_level" filterable allow-create default-first-option>
          <el-option label="初级" value="初级" />
          <el-option label="中级" value="中级" />
          <el-option label="高级" value="高级" />
          <el-option label="零基础" value="零基础" />
          <el-option label="Python 基础" value="Python 基础" />
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
        <el-button @click="$router.push('/feedback')" :disabled="!result.resources.length">去提交反馈</el-button>
        <el-button @click="$router.push('/report')">查看报告</el-button>
      </el-form-item>
    </el-form>

    <el-divider />

    <h3>生成结果</h3>
    <el-alert
      v-if="lastResourceId"
      type="success"
      :closable="false"
      style="margin-bottom: 16px;"
      :title="`已生成 ${result.resources.length} 个资源，最近资源ID：${lastResourceId}`"
    />
    <el-card v-if="result.report && Object.keys(result.report).length" style="margin-bottom: 20px;">
      <template #header>生成报告摘要</template>
      <p><strong>推荐难度：</strong>{{ result.report.recommended_difficulty || '-' }}</p>
      <p><strong>覆盖率：</strong>{{ percent(result.report.coverage_rate) }}</p>
      <p><strong>幻觉风险：</strong>{{ percent(result.report.hallucination_rate ?? result.report.hallucination_score) }}</p>
      <p><strong>难度匹配：</strong>{{ result.report.difficulty_match ? '匹配' : '需关注' }}</p>
      <div v-if="learningPath.length">
        <strong>学习路径：</strong>
        <el-steps direction="vertical" :active="learningPath.length" style="margin-top: 12px;">
          <el-step
            v-for="item in learningPath"
            :key="item.order || item.topic"
            :title="item.topic"
            :description="item.reason"
          />
        </el-steps>
      </div>
    </el-card>
    <AgentVisualization :trace="result.trace" />
    <ResourceViewer :resources="result.resources" />
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { learnerApi, generateApi } from '../api'
import AgentVisualization from '../components/AgentVisualization.vue'
import ResourceViewer from '../components/ResourceViewer.vue'

const form = reactive({
  learner_id: 'stu_001',
  topic: '根据当前知识库主题生成一套入门到实操的学习资源',
})

const profile = reactive({
  learner_id: 'stu_001',
  learner_type: '有基础学习者',
  education: '本科',
  major: '计算机科学与技术',
  theory_scores: { '基础概念': 70, '核心流程': 45, '工具使用': 65, '实操应用': 50 },
  skill_level: '中级',
  weak_points: ['核心流程', '实操应用'],
  strong_points: ['基础概念', '工具使用'],
  learning_goal: '掌握当前知识库主题的核心概念、实操步骤和常见问题处理',
})

const loading = ref(false)
const lastResourceId = ref(localStorage.getItem('last_resource_id') || '')
const result = reactive({ resources: [], trace: [], report: {} })

const learningPath = computed(() => result.report?.learning_plan?.learning_path || [])

function percent(value) {
  if (value === undefined || value === null) return '-'
  return `${Math.round(Number(value) * 100)}%`
}

async function onSubmit() {
  loading.value = true
  try {
    await learnerApi.createProfile({ ...profile, learner_id: form.learner_id })
    localStorage.setItem('last_learner_id', form.learner_id)
    const res = await generateApi.generate({
      learner_id: form.learner_id,
      topic: form.topic,
      resource_types: ['定制讲义', '实操指南', '分阶测试题'],
    })
    result.resources = res.data.resources
    result.trace = res.data.trace
    result.report = res.data.report || {}
    if (result.resources.length) {
      lastResourceId.value = result.resources[0].resource_id
      localStorage.setItem('last_resource_id', lastResourceId.value)
    }
    ElMessage.success('资源生成完成')
  } catch (e) {
    console.error(e)
    ElMessage.error(e?.response?.data?.message || '生成失败，请检查后端服务与 API Key')
  } finally {
    loading.value = false
  }
}
</script>
