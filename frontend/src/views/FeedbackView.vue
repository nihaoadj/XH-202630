<template>
  <div class="feedback-page">
    <section class="hero-card">
      <div>
        <h2>测评与反馈</h2>
        <p>学习完资源后，先完成系统测评，再补充你的主观反馈。系统会根据测评正确率和反馈意见一起调整后续资源建议。</p>
      </div>
      <el-tag effect="plain" type="info">{{ currentLearnerLabel }}</el-tag>
    </section>

    <el-card class="selector-card">
      <template #header>
        <div class="card-head">
          <span>选择学习资源</span>
          <el-button text @click="loadResources">刷新资源</el-button>
        </div>
      </template>

      <div class="selector-row">
        <el-select
          v-model="form.resource_id"
          filterable
          placeholder="选择要测评的资源"
          class="resource-select"
          @change="loadEvaluationSession"
        >
          <el-option
            v-for="item in resources"
            :key="item.resource_id"
            :label="resourceLabel(item)"
            :value="item.resource_id"
          />
        </el-select>
        <el-button type="primary" plain @click="loadEvaluationSession" :disabled="!form.resource_id">
          加载测评题
        </el-button>
      </div>
    </el-card>

    <el-card class="evaluation-card">
      <template #header>
        <div class="card-head">
          <div>
            <span>资源测评</span>
            <p class="muted" v-if="evaluation.topic">{{ evaluation.topic }}</p>
          </div>
          <el-tag effect="plain">{{ evaluation.questions.length }} 题</el-tag>
        </div>
      </template>

      <el-empty
        v-if="!evaluation.questions.length"
        description="先选择资源并加载测评题。系统会优先使用资源自带练习题，没有的话会自动抽取该学习方向的相关题目。"
      />

      <div v-else class="question-list">
        <article
          v-for="(question, index) in evaluation.questions"
          :key="question.question_id"
          class="question-item"
        >
          <div class="question-head">
            <strong>{{ index + 1 }}. {{ question.question }}</strong>
            <el-tag size="small" effect="plain">{{ question.knowledge_point || '综合题' }}</el-tag>
          </div>

          <el-radio-group
            v-if="question.question_type === 'single_choice' && question.options?.length"
            v-model="evaluationAnswers[question.question_id]"
          >
            <el-radio
              v-for="option in question.options"
              :key="option"
              :label="option"
              :value="option"
            />
          </el-radio-group>

          <el-checkbox-group
            v-else-if="question.question_type === 'multiple_choice' && question.options?.length"
            v-model="evaluationAnswers[question.question_id]"
          >
            <el-checkbox
              v-for="option in question.options"
              :key="option"
              :label="option"
              :value="option"
            />
          </el-checkbox-group>

          <el-input
            v-else
            v-model="evaluationAnswers[question.question_id]"
            type="textarea"
            :rows="3"
            placeholder="请输入你的答案"
          />
        </article>
      </div>
    </el-card>

    <el-card class="subjective-card">
      <template #header>
        <span>主观反馈</span>
      </template>

      <el-form :model="form" label-width="110px">
        <el-form-item label="是否完成">
          <el-switch v-model="form.completed" />
        </el-form-item>
        <el-form-item label="学习耗时">
          <el-input-number v-model="form.time_spent_seconds" :min="0" :step="300" />
          <span class="field-tip">单位：秒</span>
        </el-form-item>
        <el-form-item label="学习自评">
          <el-rate v-model="form.self_rating" :max="5" />
        </el-form-item>
        <el-form-item label="难度感受">
          <el-select v-model="form.difficulty_feeling" placeholder="选择你的感受" style="width: 220px;">
            <el-option label="偏简单" value="too_easy" />
            <el-option label="刚刚好" value="fit" />
            <el-option label="偏难" value="too_hard" />
          </el-select>
        </el-form-item>
        <el-form-item label="最有帮助">
          <el-input v-model="form.helpful_part" placeholder="例如：例子、结构、总结部分" />
        </el-form-item>
        <el-form-item label="最困惑点">
          <el-input v-model="form.confusing_part" placeholder="例如：术语解释、步骤理解、案例迁移" />
        </el-form-item>
        <el-form-item label="反馈意见">
          <el-input
            v-model="form.comment"
            type="textarea"
            :rows="4"
            placeholder="可以补充你希望系统如何改进资源，例如更想要补充讲义、更多练习题或更高难度任务。"
          />
        </el-form-item>
      </el-form>

      <div class="actions">
        <el-button type="primary" @click="submitEvaluation" :loading="submitting" :disabled="!canSubmit">
          提交测评与反馈
        </el-button>
        <el-button @click="loadHistory">刷新反馈历史</el-button>
        <el-button @click="$router.push('/report')">查看学习报告</el-button>
      </div>
    </el-card>

    <el-card v-if="result" class="result-card">
      <template #header>
        <div class="card-head">
          <span>本次反馈结果</span>
          <el-tag type="success" effect="plain">{{ Math.round(result.correct_rate * 100) }}%</el-tag>
        </div>
      </template>

      <div class="result-grid">
        <div>
          <span>答对题数</span>
          <strong>{{ result.correct_count }} / {{ result.total_questions }}</strong>
        </div>
        <div>
          <span>系统决策</span>
          <strong>{{ result.feedback.decision }}</strong>
        </div>
        <div>
          <span>下一步</span>
          <strong>{{ result.feedback.next_action || '-' }}</strong>
        </div>
        <div>
          <span>建议主题</span>
          <strong>{{ (result.feedback.recommended_topics || []).join('、') || '-' }}</strong>
        </div>
      </div>

      <p class="result-reason">{{ result.feedback.decision_reason || result.feedback.message }}</p>

      <p v-if="result.wrong_knowledge_points?.length" class="result-wrong">
        重点薄弱知识点：{{ result.wrong_knowledge_points.join('、') }}
      </p>
    </el-card>

    <el-card class="history-card">
      <template #header>反馈历史</template>
      <el-empty v-if="!history.length" description="暂时还没有反馈记录" />
      <el-table v-else :data="history" style="width: 100%;">
        <el-table-column label="资源" min-width="220">
          <template #default="{ row }">
            {{ historyResourceLabel(row) }}
          </template>
        </el-table-column>
        <el-table-column prop="correct_rate" label="正确率" width="110">
          <template #default="{ row }">{{ Math.round(row.correct_rate * 100) }}%</template>
        </el-table-column>
        <el-table-column prop="decision" label="系统决策" width="140" />
        <el-table-column prop="created_at" label="时间" min-width="180" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { feedbackApi, resourceApi } from '../api'
import { useAppStore } from '../stores/app'

const store = useAppStore()

const form = reactive({
  learner_id: store.currentLearnerId || localStorage.getItem('last_learner_id') || '',
  resource_id: '',
  completed: true,
  time_spent_seconds: 1800,
  self_rating: 4,
  difficulty_feeling: '',
  helpful_part: '',
  confusing_part: '',
  comment: '',
})

const resources = ref([])
const history = ref([])
const submitting = ref(false)
const result = ref(null)
const evaluation = reactive({
  topic: '',
  questions: [],
})
const evaluationAnswers = reactive({})

const currentLearnerLabel = computed(() => {
  const name =
    store.currentUserProfile?.display_name ||
    store.currentProfile?.learning_preferences?.metadata?.user_profile_snapshot?.display_name ||
    '当前用户'
  const direction =
    store.currentLearningDirectionName ||
    localStorage.getItem('learning_direction_name') ||
    '未选择方向'
  return `${name} / ${direction}`
})

const canSubmit = computed(() => form.resource_id && evaluation.questions.length)

watch(
  () => store.currentLearnerId,
  (value) => {
    if (value) {
      form.learner_id = value
    }
  }
)

function resetEvaluationAnswers() {
  for (const key of Object.keys(evaluationAnswers)) {
    delete evaluationAnswers[key]
  }
}

function resourceLabel(item) {
  return `${item.resource_type} / ${item.difficulty} / ${item.topic || '未命名主题'}`
}

function historyResourceLabel(row) {
  const matched = resources.value.find((item) => item.resource_id === row.resource_id)
  if (matched) {
    return resourceLabel(matched)
  }
  return row.resource_id ? `资源 ${row.resource_id.slice(0, 8)}` : '未命名资源'
}

async function loadResources() {
  if (!form.learner_id) return
  try {
    const res = await resourceApi.listByLearner(form.learner_id)
    resources.value = res.data.resources || []
    if (!form.resource_id && resources.value.length) {
      form.resource_id = resources.value[0].resource_id
    }
  } catch (error) {
    console.error(error)
    ElMessage.warning('资源加载失败，请先完成资源生成。')
  }
}

async function loadEvaluationSession() {
  if (!form.learner_id || !form.resource_id) return
  try {
    const res = await feedbackApi.getEvaluationSession(form.learner_id, form.resource_id)
    evaluation.topic = res.data.topic || ''
    evaluation.questions = res.data.questions || []
    resetEvaluationAnswers()
    for (const question of evaluation.questions) {
      evaluationAnswers[question.question_id] =
        question.question_type === 'multiple_choice' ? [] : ''
    }
  } catch (error) {
    console.error(error)
    evaluation.topic = ''
    evaluation.questions = []
    resetEvaluationAnswers()
    ElMessage.error(error?.response?.data?.message || '测评题加载失败')
  }
}

async function loadHistory() {
  if (!form.learner_id) return
  try {
    const res = await feedbackApi.history(form.learner_id)
    history.value = res.data.items || []
  } catch (error) {
    console.error(error)
    history.value = []
  }
}

async function submitEvaluation() {
  if (!canSubmit.value) {
    ElMessage.warning('请先选择资源并完成测评题。')
    return
  }

  submitting.value = true
  try {
    const payload = {
      learner_id: form.learner_id,
      resource_id: form.resource_id,
      answers: evaluation.questions.map((question) => ({
        question_id: question.question_id,
        answer: evaluationAnswers[question.question_id],
      })),
      completed: form.completed,
      time_spent_seconds: form.time_spent_seconds,
      self_rating: form.self_rating,
      practice_result: {
        difficulty_feeling: form.difficulty_feeling,
        helpful_part: form.helpful_part,
        confusing_part: form.confusing_part,
        comment: form.comment,
      },
    }

    const res = await feedbackApi.submitEvaluation(payload)
    result.value = res.data

    if (res.data.feedback?.updated_profile) {
      store.setCurrentProfile(res.data.feedback.updated_profile)
    }

    ElMessage.success('测评与反馈已提交')
    await loadHistory()
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '提交失败，请稍后再试')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await loadResources()
  await loadHistory()
  if (form.resource_id) {
    await loadEvaluationSession()
  }
})
</script>

<style scoped>
.feedback-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.hero-card,
.selector-card,
.evaluation-card,
.subjective-card,
.result-card,
.history-card {
  padding: 22px;
  border-radius: 16px;
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
  font-size: 28px;
}

.hero-card p {
  margin: 10px 0 0;
  color: #667085;
  line-height: 1.7;
  max-width: 760px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.muted {
  margin: 6px 0 0;
  color: #667085;
  font-size: 13px;
}

.selector-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.resource-select {
  width: min(460px, 100%);
}

.question-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.question-item {
  padding-bottom: 18px;
  border-bottom: 1px solid #edf2f7;
}

.question-item:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.question-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 12px;
}

.field-tip {
  margin-left: 10px;
  color: #667085;
  font-size: 13px;
}

.actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.result-grid span {
  display: block;
  margin-bottom: 6px;
  color: #667085;
  font-size: 12px;
}

.result-grid strong {
  color: #172033;
}

.result-reason,
.result-wrong {
  margin: 0;
  color: #475467;
  line-height: 1.7;
}

@media (max-width: 920px) {
  .hero-card,
  .question-head {
    flex-direction: column;
  }

  .result-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 640px) {
  .result-grid {
    grid-template-columns: 1fr;
  }
}
</style>
