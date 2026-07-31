<template>
  <div class="diagnosis-page">
    <el-alert
      v-if="!profile || !diagnosticQuestions.length"
      type="warning"
      :closable="false"
      title="当前没有待完成的诊断题，请先完成学习方向选择与问卷。"
    />

    <template v-else>
      <el-card class="summary-card">
        <template #header>
          <div class="summary-head">
            <span>诊断前画像摘要</span>
            <el-tag>{{ store.currentLearningDirectionName || store.currentLearningDirectionId }}</el-tag>
          </div>
        </template>
        <el-descriptions :column="2" border>
          <el-descriptions-item label="学习者">{{ profile.learner_id }}</el-descriptions-item>
          <el-descriptions-item label="当前层级">{{ profile.skill_level }}</el-descriptions-item>
          <el-descriptions-item label="当前方向">{{ store.currentLearningDirectionName || store.currentLearningDirectionId }}</el-descriptions-item>
          <el-descriptions-item label="学习目标">{{ profile.learning_goal }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-card class="question-card">
        <template #header>
          <div class="summary-head">
            <span>能力诊断题</span>
            <el-tag type="success">{{ diagnosticQuestions.length }} 题</el-tag>
          </div>
        </template>

        <div v-for="question in diagnosticQuestions" :key="question.question_id" class="diagnostic-item">
          <p class="question-title">{{ question.question }}</p>
          <el-radio-group
            v-if="question.question_type === 'single_choice'"
            v-model="diagnosticAnswers[question.question_id]"
          >
            <el-radio
              v-for="option in question.options || []"
              :key="option"
              :label="option"
              :value="option"
            />
          </el-radio-group>
          <el-checkbox-group
            v-else-if="question.question_type === 'multiple_choice'"
            v-model="diagnosticAnswers[question.question_id]"
          >
            <el-checkbox
              v-for="option in question.options || []"
              :key="option"
              :label="option"
              :value="option"
            />
          </el-checkbox-group>
          <el-input v-else v-model="diagnosticAnswers[question.question_id]" type="textarea" />
        </div>

        <div class="action-row">
          <el-button @click="$router.push('/learning/new')">返回修改问卷</el-button>
          <el-button type="primary" @click="submitDiagnosis" :loading="submittingDiagnosis">
            提交诊断
          </el-button>
        </div>
      </el-card>

      <el-card v-if="result" class="result-card">
        <template #header>
          <div class="summary-head">
            <span>诊断结果</span>
            <el-tag type="success">{{ result.ability_level }}</el-tag>
          </div>
        </template>

        <el-descriptions :column="2" border>
          <el-descriptions-item label="能力层级">{{ result.ability_level }}</el-descriptions-item>
          <el-descriptions-item label="知识库">{{ result.knowledge_base_id }}</el-descriptions-item>
          <el-descriptions-item label="薄弱点" :span="2">{{ (result.weak_points || []).join('、') || '-' }}</el-descriptions-item>
          <el-descriptions-item label="强项" :span="2">{{ (result.strong_points || []).join('、') || '-' }}</el-descriptions-item>
        </el-descriptions>

        <div class="action-row">
          <el-button type="primary" @click="$router.push('/generate')">进入资源生成</el-button>
          <el-button @click="$router.push('/resources')">查看资源页</el-button>
          <el-button @click="$router.push('/report')">查看报告</el-button>
        </div>
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { diagnosisApi } from '../api'
import { useAppStore } from '../stores/app'

const store = useAppStore()
const profile = computed(() => store.currentProfile)
const diagnosticQuestions = computed(() => store.pendingDiagnosticQuestions || [])
const result = computed(() => store.diagnosisResult)
const submittingDiagnosis = ref(false)
const diagnosticAnswers = reactive({})

for (const question of diagnosticQuestions.value) {
  diagnosticAnswers[question.question_id] = question.question_type === 'multiple_choice' ? [] : ''
}

async function submitDiagnosis() {
  submittingDiagnosis.value = true
  try {
    const answers = diagnosticQuestions.value.map((question) => ({
      question_id: question.question_id,
      answer: diagnosticAnswers[question.question_id],
    }))
    const res = await diagnosisApi.submit({
      learner_id: profile.value.learner_id,
      learning_direction_id: store.currentLearningDirectionId,
      answers,
    })
    store.setDiagnosisResult(res.data)
    store.setCurrentProfile({
      ...profile.value,
      skill_level: res.data.ability_level,
      weak_points: res.data.weak_points,
      strong_points: res.data.strong_points,
      knowledge_states: {
        ...(profile.value.knowledge_states || {}),
        ...(res.data.knowledge_states || {}),
      },
    })
    store.clearPendingDiagnosis()
    ElMessage.success('诊断已完成')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '诊断提交失败')
  } finally {
    submittingDiagnosis.value = false
  }
}
</script>

<style scoped>
.diagnosis-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.summary-card,
.question-card,
.result-card {
  border-radius: 10px;
}

.summary-head,
.action-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.action-row {
  justify-content: flex-end;
  margin-top: 18px;
  flex-wrap: wrap;
}

.diagnostic-item {
  padding: 16px 0;
  border-bottom: 1px solid #edf1f7;
}

.diagnostic-item:last-of-type {
  border-bottom: 0;
}

.question-title {
  margin: 0 0 12px;
  font-weight: 600;
}
</style>
