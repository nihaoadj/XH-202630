<template>
  <div class="onboarding-page">
    <section class="user-bar">
      <div>
        <h2>新建学习方向</h2>
        <p>先确认当前用户，再按 5 步完成问卷、诊断和资源选择。</p>
      </div>

      <div class="user-actions">
        <el-select v-model="selectedUserId" placeholder="请选择当前用户" class="user-select" @change="applySelectedUser">
          <el-option
            v-for="user in users"
            :key="user.user_id"
            :label="`${user.display_name} / ${user.identity}`"
            :value="user.user_id"
          />
        </el-select>
        <el-button @click="$router.push('/user/profile')">维护用户资料</el-button>
      </div>
    </section>

    <el-empty
      v-if="!users.length"
      description="请先创建用户资料，再开始新建学习方向。"
    >
      <el-button type="primary" @click="$router.push('/user/profile')">去创建用户资料</el-button>
    </el-empty>

    <section v-else class="wizard-layout">
      <aside class="progress-panel">
        <button
          v-for="step in steps"
          :key="step.stage"
          type="button"
          class="progress-card"
          :class="{ active: stepStage === step.stage, done: completedStepCount >= step.index, disabled: !canEnter(step.stage) }"
          :disabled="!canEnter(step.stage)"
          @click="goStep(step.stage)"
        >
          <span class="progress-index">{{ completedStepCount >= step.index ? '✓' : step.index }}</span>
          <div>
            <div class="progress-title">{{ step.title }}</div>
            <div class="progress-desc">{{ step.description() }}</div>
          </div>
        </button>
      </aside>

      <div class="step-panel">
        <el-card v-if="stepStage === 'domain'" class="work-card">
          <template #header>
            <div class="card-head">
              <div>
                <div class="card-title">第 1 步：选择培训领域</div>
                <div class="card-subtitle">先选择大领域，再细化到具体学习方向。</div>
              </div>
            </div>
          </template>

          <div class="card-grid">
            <button
              v-for="item in domains"
              :key="item.domain_id"
              type="button"
              class="choice-card"
              :class="{ selected: selectedDomainId === item.domain_id }"
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
                <div class="card-title">第 2 步：选择学习方向</div>
                <div class="card-subtitle">当前领域：{{ selectedDomain?.name }}</div>
              </div>
            </div>
          </template>

          <div class="card-grid">
            <button
              v-for="item in tracks"
              :key="item.track_id"
              type="button"
              class="choice-card"
              :class="{ selected: selectedDirectionId === item.track_id, unavailable: !isTrackAvailable(item) }"
              :disabled="!isTrackAvailable(item)"
              @click="selectDirection(item)"
            >
              <span class="choice-title">{{ item.name }}</span>
              <span class="choice-description">{{ item.description || '暂无描述' }}</span>
              <span class="choice-meta">
                {{ item.metadata?.document_count || 0 }} 份资料 / {{ item.metadata?.skill_node_count || 0 }} 个能力节点
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
                <div class="card-title">第 3 步：填写方向问卷</div>
                <div class="card-subtitle">这里只填写当前学习方向相关的动态信息。</div>
              </div>
            </div>
          </template>

          <div class="selection-pill-row">
            <span class="selection-pill">用户：{{ currentUser?.display_name }}</span>
            <span class="selection-pill">方向：{{ selectedDirection?.name }}</span>
            <span class="selection-pill">学习档案：{{ learnerLabel }}</span>
          </div>

          <el-form label-position="top" class="questionnaire-form">
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
              <el-button type="primary" :loading="submittingProfile" @click="submitQuestionnaire">提交问卷</el-button>
            </div>
          </el-form>
        </el-card>

        <el-card v-else-if="stepStage === 'diagnosis'" class="work-card">
          <template #header>
            <div class="card-head">
              <div>
                <div class="card-title">第 4 步：完成能力诊断</div>
                <div class="card-subtitle">根据问卷结果补齐真实掌握情况。</div>
              </div>
            </div>
          </template>

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
              <el-button type="primary" :loading="submittingDiagnosis" @click="submitDiagnosis">提交诊断</el-button>
            </div>
          </template>

          <el-empty v-else description="当前没有需要作答的诊断题，提交问卷后系统会自动判断是否需要诊断。" />
        </el-card>

        <el-card v-else class="work-card">
          <template #header>
            <div class="card-head">
              <div>
                <div class="card-title">第 5 步：确认诊断结果并选择资源</div>
                <div class="card-subtitle">资源类型不再从问卷选择，而是在诊断结果出来后单独确认。</div>
              </div>
            </div>
          </template>

          <el-card v-if="diagnosisResult" class="result-card">
            <template #header>
              <div class="card-head compact">
                <div>
                  <div class="card-title small">诊断结果</div>
                  <div class="card-subtitle">{{ selectedDirection?.name }}</div>
                </div>
                <el-tag type="success">{{ diagnosisResult.ability_level }}</el-tag>
              </div>
            </template>

            <el-descriptions :column="2" border>
              <el-descriptions-item label="用户">{{ currentUser?.display_name }}</el-descriptions-item>
              <el-descriptions-item label="学习方向">{{ selectedDirection?.name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="薄弱点" :span="2">{{ (diagnosisResult.weak_points || []).join('、') || '-' }}</el-descriptions-item>
              <el-descriptions-item label="优势点" :span="2">{{ (diagnosisResult.strong_points || []).join('、') || '-' }}</el-descriptions-item>
            </el-descriptions>
          </el-card>

          <el-form label-position="top" class="questionnaire-form">
            <el-form-item label="本次要生成的资源类型" required>
              <el-checkbox-group v-model="selectedResourceTypes">
                <el-checkbox v-for="item in resourceTypeOptions" :key="item" :label="item" :value="item" />
              </el-checkbox-group>
            </el-form-item>

            <el-form-item label="生成主题">
              <el-input v-model="generationTopic" type="textarea" :rows="3" />
            </el-form-item>

            <div class="action-row">
              <el-button @click="goStep('diagnosis')">上一步</el-button>
              <el-button type="primary" :loading="submittingGeneration" @click="submitGeneration">
                生成并进入状态页
              </el-button>
            </div>
          </el-form>
        </el-card>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { diagnosisApi, generateApi, knowledgeApi, onboardingApi, userApi } from '../api'
import { useAppStore } from '../stores/app'

const router = useRouter()
const store = useAppStore()

const users = ref([])
const domains = ref([])
const questions = ref([])
const selectedUserId = ref(store.currentUserId || '')
const selectedDomainId = ref('')
const selectedDirectionId = ref('')
const stepStage = ref('domain')
const submittingProfile = ref(false)
const submittingDiagnosis = ref(false)
const submittingGeneration = ref(false)
const selectedResourceTypes = ref(['讲义', '实操指南', '分阶段测试题'])
const generationTopic = ref('基于当前诊断结果生成一组从入门到实操的学习资源')

const form = reactive({})
const diagnosticAnswers = reactive({})

const currentUser = computed(() => users.value.find((item) => item.user_id === selectedUserId.value) || store.currentUserProfile || null)
const selectedDomain = computed(() => domains.value.find((item) => item.domain_id === selectedDomainId.value))
const tracks = computed(() => selectedDomain.value?.tracks || [])
const selectedDirection = computed(() => tracks.value.find((item) => item.track_id === selectedDirectionId.value))
const currentProfile = computed(() => store.currentProfile)
const diagnosticQuestions = computed(() => store.pendingDiagnosticQuestions || [])
const diagnosisResult = computed(() => store.diagnosisResult)
const questionnaireCompleted = computed(() => Boolean(currentProfile.value && selectedDirectionId.value))
const learnerId = computed(() => {
  if (!selectedUserId.value || !selectedDirectionId.value) return ''
  return `${selectedUserId.value}__${selectedDirectionId.value}`
})
const learnerLabel = computed(() => {
  const userName = currentUser.value?.display_name || '当前用户'
  const directionName = selectedDirection.value?.name || '未选择方向'
  return `${userName} / ${directionName}`
})

const resourceTypeOptions = ['讲义', '实操指南', '分阶段测试题', '复习清单', '学习路径建议']

const steps = [
  {
    index: 1,
    stage: 'domain',
    title: '领域',
    description: () => selectedDomain.value?.name || '选择一级培训领域',
  },
  {
    index: 2,
    stage: 'track',
    title: '方向',
    description: () => selectedDirection.value?.name || '选择具体学习方向',
  },
  {
    index: 3,
    stage: 'questionnaire',
    title: '问卷',
    description: () => (questionnaireCompleted.value ? '已完成方向问卷' : '填写方向相关动态信息'),
  },
  {
    index: 4,
    stage: 'diagnosis',
    title: '诊断',
    description: () => (diagnosisResult.value ? '已完成能力诊断' : '补齐真实掌握情况'),
  },
  {
    index: 5,
    stage: 'review',
    title: '资源选择',
    description: () => (diagnosisResult.value ? '确认资源类型并生成' : '查看诊断结果后选择资源'),
  },
]

const completedStepCount = computed(() => {
  let count = 0
  if (selectedDomainId.value) count = 1
  if (selectedDirectionId.value) count = 2
  if (questionnaireCompleted.value) count = 3
  if (diagnosisResult.value) count = 4
  if (diagnosisResult.value && selectedResourceTypes.value.length) count = 5
  return count
})

function canEnter(stage) {
  if (!currentUser.value) return stage === 'domain'
  if (stage === 'domain') return true
  if (stage === 'track') return Boolean(selectedDomainId.value)
  if (stage === 'questionnaire') return Boolean(selectedDirectionId.value)
  if (stage === 'diagnosis') return questionnaireCompleted.value
  if (stage === 'review') return Boolean(diagnosisResult.value)
  return false
}

function goStep(target) {
  if (canEnter(target)) {
    stepStage.value = target
  }
}

function applySelectedUser() {
  const user = users.value.find((item) => item.user_id === selectedUserId.value)
  if (!user) return
  store.setCurrentUserProfile(user)
}

function initDiagnosticAnswers() {
  Object.keys(diagnosticAnswers).forEach((key) => {
    delete diagnosticAnswers[key]
  })
  for (const question of diagnosticQuestions.value) {
    diagnosticAnswers[question.question_id] = question.question_type === 'multiple_choice' ? [] : ''
  }
}

function resetFormValues() {
  Object.keys(form).forEach((key) => {
    delete form[key]
  })
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

async function loadUsers() {
  const res = await userApi.list()
  users.value = res.data.items || []
  if (!selectedUserId.value && users.value.length) {
    selectedUserId.value = store.currentUserId || users.value[0].user_id
    applySelectedUser()
  }
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

async function prepareQuestionnaire() {
  if (!selectedDirectionId.value) return
  await loadQuestions()
  stepStage.value = 'questionnaire'
}

async function submitQuestionnaire() {
  if (!currentUser.value || !learnerId.value) {
    ElMessage.warning('请先选择用户和学习方向')
    return
  }

  submittingProfile.value = true
  try {
    const answers = questions.value.reduce((acc, question) => {
      acc[question.question_id] = form[question.question_id]
      return acc
    }, {})

    const res = await onboardingApi.createInitialProfile({
      learner_id: learnerId.value,
      user_id: currentUser.value.user_id,
      learning_direction_id: selectedDirectionId.value,
      answers,
    })

    store.setLearnerId(learnerId.value)
    store.setCurrentProfile(res.data.profile)
    store.setPendingDiagnosis(res.data.diagnostic_questions || [])
    store.setDiagnosisResult(null)
    initDiagnosticAnswers()
    stepStage.value = diagnosticQuestions.value.length ? 'diagnosis' : 'review'
    if (!diagnosticQuestions.value.length) {
      store.setDiagnosisResult({
        ability_level: res.data.profile.skill_level,
        weak_points: res.data.profile.weak_points || [],
        strong_points: res.data.profile.strong_points || [],
        knowledge_states: res.data.profile.knowledge_states || {},
        diagnostic_result_id: '',
      })
    }
    ElMessage.success('问卷已提交')
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
    stepStage.value = 'review'
    ElMessage.success('诊断已完成')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '诊断提交失败')
  } finally {
    submittingDiagnosis.value = false
  }
}

async function submitGeneration() {
  if (!selectedResourceTypes.value.length) {
    ElMessage.warning('请至少选择一种资源类型')
    return
  }
  submittingGeneration.value = true
  try {
    const res = await generateApi.createJob({
      learner_id: learnerId.value,
      knowledge_base_id: selectedDirectionId.value,
      topic: generationTopic.value,
      diagnostic_result_id: diagnosisResult.value?.diagnostic_result_id,
      resource_types: selectedResourceTypes.value,
    })
    router.push({
      path: '/generate',
      query: {
        runId: res.data.run_id,
        learnerId: learnerId.value,
      },
    })
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || '生成任务提交失败')
  } finally {
    submittingGeneration.value = false
  }
}

watch(diagnosticQuestions, initDiagnosticAnswers)

onMounted(async () => {
  try {
    store.setCurrentProfile(null)
    store.setPendingDiagnosis([])
    store.setDiagnosisResult(null)
    await Promise.all([loadUsers(), loadDomains()])
  } catch (error) {
    console.error(error)
    ElMessage.error('初始化学习方向页面失败')
  }
})
</script>

<style scoped>
.onboarding-page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.user-bar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 22px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 14px;
}

.user-bar h2 {
  margin: 0;
}

.user-bar p {
  margin: 8px 0 0;
  color: #667085;
}

.user-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.user-select {
  width: 280px;
}

.wizard-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 20px;
}

.progress-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.progress-card {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 12px;
  align-items: center;
  min-height: 104px;
  padding: 18px 16px;
  border: 1px solid #dde4ee;
  border-radius: 8px;
  background: #ffffff;
  color: #172033;
  text-align: left;
  cursor: pointer;
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
}

.progress-desc {
  margin-top: 4px;
  color: #5f6b7a;
  line-height: 1.5;
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

.selection-pill-row {
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

.choice-title {
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
}

@media (max-width: 720px) {
  .user-bar {
    flex-direction: column;
  }

  .user-select {
    width: 100%;
  }
}
</style>
