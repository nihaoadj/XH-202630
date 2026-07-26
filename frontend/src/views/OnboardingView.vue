<template>
  <div class="onboarding-page">
    <section class="wizard-layout">
      <aside class="progress-panel">
        <button
          type="button"
          class="progress-card"
          :class="{ active: activeStep === 1, done: completedStepCount >= 1 }"
          @click="goStep('domain')"
        >
          <span class="progress-index">{{ completedStepCount >= 1 ? '✓' : '1' }}</span>
          <div>
            <div class="progress-title">领域</div>
            <div class="progress-desc">{{ selectedDomain?.name || '选择一级培训领域' }}</div>
          </div>
        </button>

        <button
          type="button"
          class="progress-card"
          :class="{ active: activeStep === 2, done: completedStepCount >= 2, disabled: !selectedDomainId }"
          :disabled="!selectedDomainId"
          @click="goStep('track')"
        >
          <span class="progress-index">{{ completedStepCount >= 2 ? '✓' : '2' }}</span>
          <div>
            <div class="progress-title">方向</div>
            <div class="progress-desc">{{ selectedDirection?.name || '在已选领域下细化方向' }}</div>
          </div>
        </button>

        <button
          type="button"
          class="progress-card"
          :class="{ active: activeStep === 3, done: completedStepCount >= 3, disabled: !selectedDirectionId }"
          :disabled="!selectedDirectionId"
          @click="goStep('questionnaire')"
        >
          <span class="progress-index">{{ completedStepCount >= 3 ? '✓' : '3' }}</span>
          <div>
            <div class="progress-title">问卷</div>
            <div class="progress-desc">{{ questionnaireCompleted ? '初始画像问卷已完成' : '构建初始学习画像' }}</div>
          </div>
        </button>

        <button
          type="button"
          class="progress-card"
          :class="{ active: activeStep === 4, done: Boolean(diagnosisResult), disabled: !questionnaireCompleted }"
          :disabled="!questionnaireCompleted"
          @click="goStep('diagnosis')"
        >
          <span class="progress-index">{{ diagnosisResult ? '✓' : '4' }}</span>
          <div>
            <div class="progress-title">诊断</div>
            <div class="progress-desc">{{ diagnosisResult ? '能力诊断已完成' : '根据问卷进入能力诊断' }}</div>
          </div>
        </button>
      </aside>

      <div class="step-panel">
        <el-card v-if="stepStage === 'domain'" class="work-card">
          <template #header>
            <div class="card-head">
              <div>
                <div class="card-title">第一步：选择培训领域</div>
                <div class="card-subtitle">先确定培训领域，再继续细化学习方向。</div>
              </div>
            </div>
          </template>

          <div class="card-grid">
            <button
              v-for="item in domains"
              :key="item.domain_id"
              class="choice-card"
              :class="{ selected: selectedDomainId === item.domain_id }"
              type="button"
              @click="selectDomain(item)"
            >
              <span class="choice-title">{{ item.name }}</span>
              <span class="choice-description">{{ item.description || '暂无描述' }}</span>
              <span class="choice-meta">{{ item.tracks?.length || 0 }} 个学习方向</span>
            </button>
          </div>

          <div class="action-row">
            <el-button type="primary" :disabled="!selectedDomainId" @click="goStep('track')">下一步</el-button>
          </div>
        </el-card>

        <el-card v-else-if="stepStage === 'track'" class="work-card">
          <template #header>
            <div class="card-head">
              <div>
                <div class="card-title">第二步：选择学习方向</div>
                <div class="card-subtitle">当前领域：{{ selectedDomain?.name }}</div>
              </div>
              <el-button text @click="goStep('domain')">返回修改领域</el-button>
            </div>
          </template>

          <div class="selection-pill-row">
            <span class="selection-pill">领域：{{ selectedDomain?.name }}</span>
          </div>

          <div class="card-grid">
            <button
              v-for="item in tracks"
              :key="item.track_id"
              class="choice-card"
              :class="{ selected: selectedDirectionId === item.track_id, unavailable: !isTrackAvailable(item) }"
              type="button"
              :disabled="!isTrackAvailable(item)"
              @click="selectDirection(item)"
            >
              <span class="choice-title">
                {{ item.name }}
                <el-tag v-if="!isTrackAvailable(item)" size="small" type="info">待建设</el-tag>
              </span>
              <span class="choice-description">{{ item.description || '暂无描述' }}</span>
              <span class="choice-meta">
                {{ item.metadata?.document_count || 0 }} 份资料 · {{ item.metadata?.skill_node_count || 0 }} 个能力节点
              </span>
            </button>
          </div>

          <div class="action-row">
            <el-button @click="goStep('domain')">上一步</el-button>
            <el-button type="primary" :disabled="!selectedDirectionId" @click="prepareQuestionnaire">下一步</el-button>
          </div>
        </el-card>

        <el-card v-else-if="stepStage === 'questionnaire'" class="work-card">
          <template #header>
            <div class="card-head">
              <div>
                <div class="card-title">第三步：填写初始画像问卷</div>
                <div class="card-subtitle">已选方向：{{ selectedDirection?.name }}。提交后将在当前页面进入诊断。</div>
              </div>
              <el-button text @click="goStep('track')">返回修改方向</el-button>
            </div>
          </template>

          <div class="selection-pill-row">
            <span class="selection-pill">领域：{{ selectedDomain?.name }}</span>
            <span class="selection-pill">方向：{{ selectedDirection?.name }}</span>
          </div>

          <el-form :model="form" label-position="top" class="questionnaire-form">
            <el-form-item label="学习者 ID" required>
              <el-input v-model="form.learner_id" placeholder="例如：stu_001" />
            </el-form-item>

            <el-form-item
              v-for="question in questions"
              :key="question.question_id"
              v-show="shouldShow(question)"
              :label="question.title"
              :required="question.required"
            >
              <el-input
                v-if="question.type === 'text'"
                v-model="form[question.question_id]"
                :placeholder="question.hint || '请输入'"
              />

              <el-select
                v-else-if="question.type === 'single_choice' || question.type === 'single_choice_or_other'"
                v-model="form[question.question_id]"
                :allow-create="question.type === 'single_choice_or_other'"
                filterable
                default-first-option
                placeholder="请选择"
                class="full-control"
              >
                <el-option
                  v-for="option in normalizedOptions(question)"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>

              <el-checkbox-group v-else-if="question.type === 'multiple_choice'" v-model="form[question.question_id]">
                <el-checkbox
                  v-for="option in normalizedOptions(question)"
                  :key="option.value"
                  :label="option.value"
                  :value="option.value"
                />
              </el-checkbox-group>
            </el-form-item>

            <div class="action-row">
              <el-button @click="goStep('track')">上一步</el-button>
              <el-button type="primary" @click="submitQuestionnaire" :loading="submittingProfile">
                提交问卷并进入诊断
              </el-button>
            </div>
          </el-form>
        </el-card>

        <el-card v-else class="work-card">
          <template #header>
            <div class="card-head">
              <div>
                <div class="card-title">第四步：完成能力诊断</div>
                <div class="card-subtitle">诊断用于校准真实掌握情况、薄弱点与后续资源建议。</div>
              </div>
              <el-button text @click="goStep('questionnaire')">返回查看问卷</el-button>
            </div>
          </template>

          <div v-if="currentProfile" class="summary-strip">
            <span class="selection-pill">学习者：{{ currentProfile.learner_id }}</span>
            <span class="selection-pill">方向：{{ store.currentLearningDirectionName || selectedDirection?.name }}</span>
            <span class="selection-pill">当前层级：{{ currentProfile.skill_level || '待诊断' }}</span>
          </div>

          <template v-if="diagnosticQuestions.length">
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
              <el-button @click="goStep('questionnaire')">上一步</el-button>
              <el-button type="primary" @click="submitDiagnosis" :loading="submittingDiagnosis">
                提交诊断
              </el-button>
            </div>
          </template>

          <el-empty v-else-if="!diagnosisResult" description="请先完成问卷，系统会生成对应诊断题。" />

          <el-card v-if="diagnosisResult" class="result-card">
            <template #header>
              <div class="card-head compact">
                <div>
                  <div class="card-title small">诊断结果</div>
                  <div class="card-subtitle">当前学习方向下的能力评估结果</div>
                </div>
                <el-tag type="success">{{ diagnosisResult.ability_level }}</el-tag>
              </div>
            </template>

            <el-descriptions :column="2" border>
              <el-descriptions-item label="能力层级">{{ diagnosisResult.ability_level }}</el-descriptions-item>
              <el-descriptions-item label="学习方向">{{ store.currentLearningDirectionName || selectedDirection?.name }}</el-descriptions-item>
              <el-descriptions-item label="薄弱点" :span="2">
                {{ (diagnosisResult.weak_points || []).join('、') || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="优势项" :span="2">
                {{ (diagnosisResult.strong_points || []).join('、') || '-' }}
              </el-descriptions-item>
            </el-descriptions>
          </el-card>
        </el-card>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { diagnosisApi, knowledgeApi, onboardingApi } from '../api'
import { useAppStore } from '../stores/app'

const store = useAppStore()

const domains = ref([])
const questions = ref([])
const selectedDomainId = ref('')
const selectedDirectionId = ref('')
const stepStage = ref('domain')
const submittingProfile = ref(false)
const submittingDiagnosis = ref(false)

const form = reactive({
  learner_id: localStorage.getItem('last_learner_id') || store.currentLearnerId || 'stu_001',
})
const diagnosticAnswers = reactive({})

const selectedDomain = computed(() => domains.value.find((item) => item.domain_id === selectedDomainId.value))
const tracks = computed(() => selectedDomain.value?.tracks || [])
const selectedDirection = computed(() => tracks.value.find((item) => item.track_id === selectedDirectionId.value))
const currentProfile = computed(() => store.currentProfile)
const diagnosticQuestions = computed(() => store.pendingDiagnosticQuestions || [])
const diagnosisResult = computed(() => store.diagnosisResult)
const questionnaireCompleted = computed(() => Boolean(currentProfile.value && selectedDirectionId.value))

const completedStepCount = computed(() => {
  let count = 0
  if (selectedDomainId.value) count = 1
  if (selectedDirectionId.value) count = 2
  if (questionnaireCompleted.value) count = 3
  if (diagnosisResult.value) count = 4
  return count
})

const activeStep = computed(() => {
  if (stepStage.value === 'diagnosis') return 4
  if (stepStage.value === 'questionnaire') return 3
  if (stepStage.value === 'track') return 2
  return 1
})

function initDiagnosticAnswers() {
  Object.keys(diagnosticAnswers).forEach((key) => {
    delete diagnosticAnswers[key]
  })
  for (const question of diagnosticQuestions.value) {
    diagnosticAnswers[question.question_id] = question.question_type === 'multiple_choice' ? [] : ''
  }
}

function resetFormValues() {
  for (const question of questions.value) {
    form[question.question_id] = question.type === 'multiple_choice' ? [] : ''
  }
}

function normalizedOptions(question) {
  return (question.options || []).map((option) => {
    if (typeof option === 'object' && option !== null) {
      return {
        label: option.label ?? option.value ?? '',
        value: option.value ?? option.label ?? '',
      }
    }
    return { label: option, value: option }
  })
}

function matchesShowRule(answer, rule) {
  if (typeof rule !== 'object' || rule === null || Array.isArray(rule)) {
    return Array.isArray(answer) ? answer.includes(rule) : answer === rule
  }
  if (Object.prototype.hasOwnProperty.call(rule, 'equals')) return answer === rule.equals
  if (Object.prototype.hasOwnProperty.call(rule, 'not_equals')) return answer !== rule.not_equals
  if (Object.prototype.hasOwnProperty.call(rule, 'includes')) return Array.isArray(answer) && answer.includes(rule.includes)
  if (Array.isArray(rule.any_of)) return rule.any_of.includes(answer)
  if (Array.isArray(rule.all_of)) return Array.isArray(answer) && rule.all_of.every((item) => answer.includes(item))
  return true
}

function shouldShow(question) {
  const condition = question.show_when
  if (!condition || Object.keys(condition).length === 0) return true
  return Object.entries(condition).every(([field, rule]) => {
    if (field.endsWith('_contains')) {
      const actualField = field.slice(0, -'_contains'.length)
      return Array.isArray(form[actualField]) && form[actualField].includes(rule)
    }
    return matchesShowRule(form[field], rule)
  })
}

function isTrackAvailable(track) {
  return track.metadata?.available !== false
}

async function loadDomains() {
  const res = await knowledgeApi.listDomains()
  domains.value = res.data.domains || []
}

async function loadQuestions() {
  if (!selectedDirectionId.value) {
    questions.value = []
    return
  }
  const res = await onboardingApi.getQuestions(selectedDirectionId.value)
  questions.value = res.data.questions || []
  resetFormValues()
}

function selectDomain(item) {
  selectedDomainId.value = item.domain_id
  selectedDirectionId.value = ''
  questions.value = []
  stepStage.value = 'domain'
  store.setLearningDirectionId('')
  store.setLearningDirectionName('')
  store.setCurrentProfile(null)
  store.setPendingDiagnosis([])
  store.setDiagnosisResult(null)
}

function selectDirection(item) {
  selectedDirectionId.value = item.track_id
  store.setLearningDirectionId(item.track_id)
  store.setLearningDirectionName(item.name)
  store.setCurrentProfile(null)
  store.setPendingDiagnosis([])
  store.setDiagnosisResult(null)
}

async function prepareQuestionnaire() {
  if (!selectedDirectionId.value) return
  await loadQuestions()
  stepStage.value = 'questionnaire'
}

function goStep(target) {
  if (target === 'domain') {
    stepStage.value = 'domain'
    return
  }
  if (target === 'track' && selectedDomainId.value) {
    stepStage.value = 'track'
    return
  }
  if (target === 'questionnaire' && selectedDirectionId.value) {
    if (!questions.value.length) {
      prepareQuestionnaire()
      return
    }
    stepStage.value = 'questionnaire'
    return
  }
  if (target === 'diagnosis' && questionnaireCompleted.value) {
    stepStage.value = 'diagnosis'
  }
}

async function submitQuestionnaire() {
  submittingProfile.value = true
  try {
    const answers = questions.value.reduce((acc, question) => {
      acc[question.question_id] = form[question.question_id]
      return acc
    }, {})

    const res = await onboardingApi.createInitialProfile({
      learner_id: form.learner_id,
      learning_direction_id: selectedDirectionId.value,
      answers,
    })

    store.setLearnerId(form.learner_id)
    store.setCurrentProfile(res.data.profile)
    store.setPendingDiagnosis(res.data.diagnostic_questions || [])
    store.setDiagnosisResult(null)
    initDiagnosticAnswers()
    stepStage.value = 'diagnosis'
    ElMessage.success('问卷已完成，请继续完成诊断')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '问卷提交失败')
  } finally {
    submittingProfile.value = false
  }
}

async function submitDiagnosis() {
  if (!currentProfile.value) return
  submittingDiagnosis.value = true
  try {
    const answers = diagnosticQuestions.value.map((question) => ({
      question_id: question.question_id,
      answer: diagnosticAnswers[question.question_id],
    }))

    const res = await diagnosisApi.submit({
      learner_id: currentProfile.value.learner_id,
      learning_direction_id: selectedDirectionId.value,
      answers,
    })

    store.setDiagnosisResult(res.data)
    store.setCurrentProfile({
      ...currentProfile.value,
      skill_level: res.data.ability_level,
      weak_points: res.data.weak_points,
      strong_points: res.data.strong_points,
      knowledge_states: {
        ...(currentProfile.value.knowledge_states || {}),
        ...(res.data.knowledge_states || {}),
      },
    })
    store.setPendingDiagnosis([])
    ElMessage.success('诊断已完成')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '诊断提交失败')
  } finally {
    submittingDiagnosis.value = false
  }
}

watch(diagnosticQuestions, () => {
  initDiagnosticAnswers()
})

onMounted(async () => {
  try {
    selectedDomainId.value = ''
    selectedDirectionId.value = ''
    stepStage.value = 'domain'
    store.setCurrentProfile(null)
    store.setPendingDiagnosis([])
    store.setDiagnosisResult(null)
    await loadDomains()
  } catch (error) {
    console.error(error)
    ElMessage.error('学习方向加载失败')
  }
})
</script>

<style scoped>
.onboarding-page {
  display: flex;
  flex-direction: column;
}

.wizard-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 20px;
  align-items: stretch;
}

.progress-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 100%;
}

.progress-card {
  flex: 1;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  min-height: 116px;
  padding: 18px 16px;
  border: 1px solid #dde4ee;
  border-radius: 8px;
  background: #ffffff;
  color: #172033;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}

.progress-card.active {
  border-color: #8cb0ff;
  box-shadow: 0 0 0 2px rgba(74, 123, 246, 0.1);
  background: #f8fbff;
}

.progress-card.done {
  background: #f3f8ff;
}

.progress-card.disabled {
  cursor: not-allowed;
  opacity: 0.66;
}

.progress-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 999px;
  background: #edf3ff;
  color: #3156a6;
  font-weight: 700;
}

.progress-title {
  font-weight: 700;
  color: #172033;
}

.progress-desc {
  margin-top: 4px;
  color: #5f6b7a;
  line-height: 1.5;
}

.step-panel {
  min-width: 0;
}

.work-card,
.result-card {
  border-radius: 8px;
}

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.card-head.compact {
  align-items: center;
}

.card-title {
  font-size: 20px;
  font-weight: 700;
  color: #172033;
}

.card-title.small {
  font-size: 18px;
}

.card-subtitle {
  margin-top: 6px;
  color: #5f6b7a;
}

.selection-pill-row,
.summary-strip {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 18px;
}

.selection-pill {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 12px;
  border-radius: 999px;
  background: #eef4ff;
  color: #3156a6;
  font-size: 13px;
  font-weight: 600;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 14px;
}

.choice-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 168px;
  padding: 18px;
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: #fff;
  color: #1f2937;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.choice-card:hover {
  border-color: #9bb8ff;
  box-shadow: 0 8px 24px rgba(31, 41, 55, 0.08);
  transform: translateY(-1px);
}

.choice-card.selected {
  border-color: #2563eb;
  box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.14);
}

.choice-card.unavailable {
  cursor: not-allowed;
  background: #f7f8fa;
  color: #667085;
}

.choice-card.unavailable:hover {
  transform: none;
  box-shadow: none;
  border-color: #d8dee8;
}

.choice-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 18px;
  font-weight: 650;
}

.choice-description {
  flex: 1;
  color: #4b5563;
  line-height: 1.6;
}

.choice-meta {
  color: #667085;
  font-size: 13px;
}

.questionnaire-form {
  max-width: 860px;
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
  color: #172033;
}

.full-control {
  width: min(100%, 560px);
}

.action-row {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 22px;
  flex-wrap: wrap;
}

@media (max-width: 1024px) {
  .wizard-layout {
    grid-template-columns: 1fr;
  }

  .progress-card {
    min-height: 92px;
  }
}
</style>
