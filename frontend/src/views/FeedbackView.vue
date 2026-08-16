<template>
  <div class="feedback-page">
    <section class="hero-card">
      <div>
        <h2>测评与反馈</h2>
        <p>学习完一次生成任务后，先完成该任务的统一测评，再补充你的主观反馈。系统会根据整次任务的完成情况调整后续资源建议。</p>
      </div>
      <el-tag effect="plain" type="info">{{ currentLearnerLabel }}</el-tag>
    </section>

    <el-card class="selector-card">
      <template #header>
        <div class="card-head">
          <span>选择生成任务</span>
          <el-button text @click="loadResources">刷新任务</el-button>
        </div>
      </template>

      <div class="selector-row">
        <el-select
          v-model="selectedRunId"
          filterable
          placeholder="选择要测评的生成任务"
          class="task-select"
          @change="loadEvaluationSession"
        >
          <el-option
            v-for="task in taskGroups"
            :key="task.runId"
            :label="task.label"
            :value="task.runId"
          />
        </el-select>
        <el-button type="primary" plain @click="loadEvaluationSession" :disabled="!selectedRunId">
          加载测评题
        </el-button>
      </div>
      <p v-if="activeTask" class="selector-tip">
        当前任务共 {{ activeTask.resources.length }} 份资源，方向：{{ currentDirectionName }}
      </p>
    </el-card>

    <el-card class="evaluation-card">
      <template #header>
        <div class="card-head">
          <div>
            <span>任务测评</span>
            <p class="muted">{{ currentDirectionName }}</p>
          </div>
          <el-tag effect="plain">{{ evaluation.questions.length }} 题</el-tag>
        </div>
      </template>

      <el-empty
        v-if="!evaluation.questions.length"
        description="先选择生成任务并加载测评题。系统会优先聚合本任务资源中的练习题，没有的话会回退到该学习方向的相关题目。"
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

      <el-form label-width="110px">
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
            placeholder="可以补充你希望系统如何改进这一整次任务的资源，例如更想要补充讲义、更多练习题或更高难度任务。"
          />
        </el-form-item>
      </el-form>

      <div class="actions">
        <el-button type="primary" @click="submitEvaluation" :loading="submitting" :disabled="!canSubmit">
          提交任务测评与反馈
        </el-button>
        <el-button @click="loadHistory">刷新反馈历史</el-button>
        <el-button @click="$router.push('/report')">查看学习报告</el-button>
      </div>
    </el-card>

    <el-card v-if="result" class="result-card">
      <template #header>
        <div class="card-head">
          <span>本次反馈结果</span>
          <el-tag type="success" effect="plain">{{ Math.round(result.attempt.overall_score * 100) }}%</el-tag>
        </div>
      </template>

      <div class="result-grid">
        <div>
          <span>答对题数</span>
          <strong>{{ attemptCorrectSummary }}</strong>
        </div>
        <div>
          <span>系统决策</span>
          <strong>{{ feedbackActionLabel(result.decision.action) }}</strong>
        </div>
        <div>
          <span>下一步</span>
          <strong>{{ followupStatusLabel(result.followup_generation_status) }}</strong>
        </div>
        <div>
          <span>建议主题</span>
          <strong>{{ result.profile_version ? `画像 v${result.profile_version}` : '-' }}</strong>
        </div>
      </div>

      <p class="result-reason">{{ result.decision.decision_reason }}</p>

      <p v-if="weakKnowledgePoints.length" class="result-wrong">
        重点薄弱知识点：{{ weakKnowledgePoints.join('、') }}
      </p>
    </el-card>

    <el-card class="history-card">
      <template #header>反馈历史</template>
      <el-empty v-if="!history.length" description="暂时还没有反馈记录" />
      <el-table v-else :data="history" style="width: 100%;">
        <el-table-column label="选择" width="80">
          <template #default="{ row }">
            <el-radio :model-value="selectedFeedbackId" :label="row.attempt_id" @change="selectFeedback(row.attempt_id)">
              &nbsp;
            </el-radio>
          </template>
        </el-table-column>
        <el-table-column label="任务/资源" min-width="220">
          <template #default="{ row }">
            {{ historyResourceLabel(row) }}
          </template>
        </el-table-column>
        <el-table-column prop="overall_score" label="正确率" width="110">
          <template #default="{ row }">{{ Math.round(row.overall_score * 100) }}%</template>
        </el-table-column>
        <el-table-column prop="source_run_id" label="系统决策" width="140" />
        <el-table-column prop="created_at" label="时间" min-width="180" />
      </el-table>

      <div class="history-actions">
        <span class="history-selection-tip">
          {{ selectedFeedbackSummary }}
        </span>
        <el-button type="success" plain @click="goToFollowupRun" :disabled="!result?.followup_run_id">
          查看后续生成任务
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { feedbackApi, resourceApi } from '../api'
import { useAppStore } from '../stores/app'
import { formatDateTime, formatResourceLabel } from '../utils/generationDisplay'

const router = useRouter()
const store = useAppStore()

const form = reactive({
  learner_id: store.currentLearnerId || localStorage.getItem('last_learner_id') || '',
  completed: true,
  time_spent_seconds: 1800,
  self_rating: 4,
  difficulty_feeling: '',
  helpful_part: '',
  confusing_part: '',
  comment: '',
})

const resources = ref([])
const selectedRunId = ref(localStorage.getItem('current_generation_run_id') || '')
const history = ref([])
const selectedFeedbackId = ref('')
const submitting = ref(false)
const result = ref(null)
const evaluation = reactive({
  topic: '',
  questions: [],
  resourceIds: [],
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

const currentDirectionName = computed(
  () => store.currentLearningDirectionName || localStorage.getItem('learning_direction_name') || '未选择方向'
)

const taskGroups = computed(() => {
  const groups = new Map()
  for (const resource of resources.value) {
    const runId = resource.run_id || `resource:${resource.resource_id}`
    if (!groups.has(runId)) {
      groups.set(runId, {
        runId,
        shortRunId: runId.startsWith('resource:') ? '未关联任务' : runId.slice(0, 8).toUpperCase(),
        finishedAt: resource.created_at || '',
        resources: [],
      })
    }
    groups.get(runId).resources.push(resource)
    if (resource.created_at && (!groups.get(runId).finishedAt || resource.created_at > groups.get(runId).finishedAt)) {
      groups.get(runId).finishedAt = resource.created_at
    }
  }
  return Array.from(groups.values()).map((task) => ({
    ...task,
    label: `${task.shortRunId} / ${currentDirectionName.value} / ${formatTaskTime(task.finishedAt)}`,
  }))
})

const activeTask = computed(() => {
  if (!taskGroups.value.length) return null
  return taskGroups.value.find((item) => item.runId === selectedRunId.value) || taskGroups.value[0]
})

const canSubmit = computed(() => Boolean(selectedRunId.value && evaluation.questions.length))
const selectedFeedbackRecord = computed(
  () => history.value.find((item) => item.attempt_id === selectedFeedbackId.value) || null
)
const selectedFeedbackSummary = computed(() => {
  if (!selectedFeedbackRecord.value) {
    return '请选择一条反馈记录查看详情'
  }
  return `当前选择 ${historyResourceLabel(selectedFeedbackRecord.value)} / ${formatTaskTime(selectedFeedbackRecord.value.created_at)}`
})
const weakKnowledgePoints = computed(() =>
  (result.value?.knowledge_state_updates || [])
    .filter((item) => item.after?.status === 'weak')
    .map((item) => item.knowledge_point_id)
)
const attemptCorrectSummary = computed(() => {
  if (!result.value?.attempt?.knowledge_point_results?.length) return '-'
  const total = result.value.attempt.knowledge_point_results.reduce((sum, item) => sum + item.total_count, 0)
  const correct = result.value.attempt.knowledge_point_results.reduce((sum, item) => sum + item.correct_count, 0)
  return `${correct} / ${total}`
})

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

function historyResourceLabel(row) {
  const matched = resources.value.find((item) => item.resource_id === row.source_resource_id)
  if (!matched) {
    return row.source_resource_id ? `资源 ${row.source_resource_id.slice(0, 8)}` : '未命名资源'
  }
  const runId = matched.run_id
  const task = runId ? `任务 ${runId.slice(0, 8).toUpperCase()}` : matched.resource_type
  return `${task} / ${formatResourceLabel(matched, currentDirectionName.value)}`
}

function selectFeedback(feedbackId) {
  selectedFeedbackId.value = feedbackId || ''
}

function formatTaskTime(value) {
  return formatDateTime(value)
}

async function loadResources() {
  if (!form.learner_id) return
  try {
    const res = await resourceApi.listByLearner(form.learner_id)
    resources.value = res.data.resources || []
    syncSelectedRun()
  } catch (error) {
    console.error(error)
    ElMessage.warning('资源加载失败，请先完成资源生成。')
  }
}

async function loadEvaluationSession() {
  if (!form.learner_id || !selectedRunId.value || selectedRunId.value.startsWith('resource:')) return
  try {
    const res = await feedbackApi.getRunEvaluationSession(form.learner_id, selectedRunId.value)
    evaluation.topic = res.data.topic || ''
    evaluation.questions = res.data.questions || []
    evaluation.resourceIds = res.data.resource_ids || []
    resetEvaluationAnswers()
    for (const question of evaluation.questions) {
      evaluationAnswers[question.question_id] =
        question.question_type === 'multiple_choice' ? [] : ''
    }
    localStorage.setItem('current_generation_run_id', selectedRunId.value)
  } catch (error) {
    console.error(error)
    evaluation.topic = ''
    evaluation.questions = []
    evaluation.resourceIds = []
    resetEvaluationAnswers()
    ElMessage.error(error?.response?.data?.message || '测评题加载失败')
  }
}

async function loadHistory() {
  if (!form.learner_id) return
  try {
    const res = await feedbackApi.listAttempts(form.learner_id)
    history.value = res.data || []
    if (!history.value.length) {
      selectedFeedbackId.value = ''
    } else if (!history.value.some((item) => item.attempt_id === selectedFeedbackId.value)) {
      selectedFeedbackId.value = history.value[0].attempt_id
    }
  } catch (error) {
    console.error(error)
    history.value = []
    selectedFeedbackId.value = ''
  }
}

async function submitEvaluation() {
  if (!canSubmit.value) {
    ElMessage.warning('请先选择任务并完成测评题。')
    return
  }

  submitting.value = true
  try {
    const submittedAt = new Date()
    const payload = {
      learner_id: form.learner_id,
      run_id: selectedRunId.value,
      source_resource_id: evaluation.resourceIds[0] || activeTask.value?.resources?.[0]?.resource_id,
      idempotency_key: buildIdempotencyKey(selectedRunId.value, submittedAt),
      expected_profile_version: store.currentProfile?.profile_version || 1,
      submitted_at: submittedAt.toISOString(),
      duration_ms: (form.time_spent_seconds || 0) * 1000,
      hint_count: 0,
      answers: evaluation.questions.map((question) => ({
        question_id: question.question_id,
        answer: evaluationAnswers[question.question_id],
      })),
      metadata: {
        source: 'feedback_view',
        client_version: 'web',
        session_id: selectedRunId.value,
      },
    }

    const res = await feedbackApi.submitRunAttempt(payload)
    result.value = res.data

    if (store.currentProfile) {
      store.setCurrentProfile({ ...store.currentProfile, profile_version: res.data.profile_version })
    }

    ElMessage.success('任务测评与反馈已提交')
    await loadHistory()
    selectedFeedbackId.value = res.data.attempt.attempt_id
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '提交失败，请稍后再试')
  } finally {
    submitting.value = false
  }
}

function feedbackActionLabel(action) {
  return {
    remediate: '补救学习',
    practice: '强化练习',
    advance: '继续进阶',
    hold: '保持路径',
    human_review: '人工复核',
  }[action] || action || '-'
}

function followupStatusLabel(status) {
  return {
    not_requested: '未触发',
    queued: '已排队',
    failed: '触发失败',
  }[status] || status || '-'
}

function buildIdempotencyKey(runId, submittedAt) {
  const stamp = submittedAt.toISOString().replace(/[^0-9]/g, '')
  return `web-${runId.slice(0, 24)}-${stamp}`.slice(0, 128)
}

function goToFollowupRun() {
  if (!result.value?.followup_run_id) return
  localStorage.setItem('current_generation_run_id', result.value.followup_run_id)
  router.push({
    path: '/generate',
    query: {
      runId: result.value.followup_run_id,
      learnerId: form.learner_id,
    },
  })
}

onMounted(async () => {
  await loadResources()
  await loadHistory()
  if (selectedRunId.value && !selectedRunId.value.startsWith('resource:')) {
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

.muted,
.selector-tip {
  margin: 6px 0 0;
  color: #667085;
  font-size: 13px;
}

.selector-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.task-select {
  width: min(520px, 100%);
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

.history-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 16px;
}

.history-selection-tip {
  color: #667085;
  font-size: 13px;
  margin-right: auto;
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
