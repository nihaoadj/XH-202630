<template>
  <div class="onboarding-page">
    <section class="user-bar">
      <div>
        <span class="page-kicker">LEARNING SETUP</span>
        <h2>创建学习方向</h2>
        <p>先确认当前用户，再按 5 步完成问卷、诊断和资源选择。</p>
      </div>

      <div class="user-actions">
        <el-tag effect="plain">{{ currentUser?.username || currentUser?.display_name }}</el-tag>
        <el-button @click="$router.push('/user/profile')">维护用户资料</el-button>
      </div>
    </section>

    <section class="wizard-layout" :class="{ compactWizard: stepStage === 'domain' || stepStage === 'track' }">
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
        <el-card v-if="stepStage === 'domain'" class="work-card domain-stage-card">
          <template #header>
            <div class="card-head">
              <div>
                <span class="card-kicker">STEP 01 · EXPLORE</span>
                <div class="card-title">选择培训领域</div>
                <div class="card-subtitle">先选择大领域，再细化到具体学习方向。</div>
              </div>
            </div>
          </template>

          <div class="overview-strip">
            <div class="overview-chip">
              <span>培训领域</span>
              <strong>{{ domains.length }}</strong>
            </div>
            <div class="overview-chip">
              <span>学习方向</span>
              <strong>{{ totalTrackCount }}</strong>
            </div>
            <div class="overview-chip">
              <span>当前用户</span>
              <strong>{{ currentUser?.display_name || currentUser?.username || '未设置' }}</strong>
            </div>
            <div class="overview-chip">
              <span>当前进度</span>
              <strong>第 1 / 5 步</strong>
            </div>
          </div>

          <div class="card-grid domain-grid">
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

          <div class="domain-footprint compact-domain-footprint">
            <section class="insight-card secondary">
              <span class="insight-kicker">操作提示</span>
              <ul class="insight-list">
                <li>优先选择你最想落地实践的业务方向，而不是最宽泛的技术标签。</li>
                <li>如果你已经有明确主题，后续可以在资源选择时补充个性化要求。</li>
                <li>方向选定后会生成独立学习历史，方便后续持续跟踪。</li>
              </ul>
            </section>
          </div>

          <div class="action-row">
            <el-button type="primary" :disabled="!selectedDomainId" @click="goStep('track')">下一步</el-button>
          </div>
        </el-card>

        <el-card v-else-if="stepStage === 'track'" class="work-card track-stage-card">
          <template #header>
            <div class="card-head">
              <div>
                <span class="card-kicker">STEP 02 · FOCUS</span>
                <div class="card-title">选择学习方向</div>
                <div class="card-subtitle">当前领域：{{ selectedDomain?.name }}</div>
              </div>
            </div>
          </template>

          <div class="overview-strip">
            <div class="overview-chip">
              <span>当前领域</span>
              <strong>{{ selectedDomain?.name || '-' }}</strong>
            </div>
            <div class="overview-chip">
              <span>可选方向</span>
              <strong>{{ tracks.length }}</strong>
            </div>
            <div class="overview-chip">
              <span>资料总量</span>
              <strong>{{ selectedDomainDocumentCount }}</strong>
            </div>
            <div class="overview-chip">
              <span>当前进度</span>
              <strong>第 2 / 5 步</strong>
            </div>
          </div>

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

          <div class="domain-footprint compact-domain-footprint">
            <section class="insight-card secondary">
              <span class="insight-kicker">选择建议</span>
              <ul class="insight-list">
                <li>优先选择你接下来最想训练和落地的具体方向。</li>
                <li>资料数和能力节点越多，后续诊断与资源生成会更完整。</li>
                <li>方向选定后，系统会围绕该方向生成独立学习画像。</li>
              </ul>
            </section>
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
                <span class="card-kicker">STEP 03 · PROFILE</span>
                <div class="card-title">填写方向问卷</div>
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
                <span class="card-kicker">STEP 04 · ASSESS</span>
                <div class="card-title">完成能力诊断</div>
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
                <span class="card-kicker">STEP 05 · CREATE</span>
                <div class="card-title">确认诊断并选择资源</div>
                <div class="card-subtitle">资源类型不再从问卷选择，而是在诊断结果出来后单独确认。</div>
              </div>
            </div>
          </template>

          <el-card v-if="diagnosisResult" class="result-card">
            <template #header>
              <div class="card-head compact">
                <div>
                  <span class="card-kicker">ASSESSMENT RESULT</span>
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

            <el-form-item label="补充要求">
              <el-input
                v-model="supplementalRequirements"
                type="textarea"
                :rows="3"
                placeholder="可选。比如：更想看案例拆解、希望增加练习题、优先覆盖 Embedding 和 Rerank。"
              />
              <div class="field-hint">系统会自动根据学习方向、诊断结果和资源类型组织本次生成任务，你可以在这里补充个性化要求。</div>
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
import { diagnosisApi, generateApi, knowledgeApi, onboardingApi } from '../api'
import { useAuthStore } from '../stores/auth'
import { useAppStore } from '../stores/app'

const router = useRouter()
const auth = useAuthStore()
const store = useAppStore()

const domains = ref([])
const questions = ref([])
const selectedDomainId = ref('')
const selectedDirectionId = ref('')
const stepStage = ref('domain')
const submittingProfile = ref(false)
const submittingDiagnosis = ref(false)
const submittingGeneration = ref(false)
const selectedResourceTypes = ref(['讲义', '实操指南', '分阶测试题'])
const supplementalRequirements = ref('')

const form = reactive({})
const diagnosticAnswers = reactive({})

const currentUser = computed(() => auth.currentUser || store.currentUserProfile || null)
const selectedDomain = computed(() => domains.value.find((item) => item.domain_id === selectedDomainId.value))
const tracks = computed(() => selectedDomain.value?.tracks || [])
const selectedDirection = computed(() => tracks.value.find((item) => item.track_id === selectedDirectionId.value))
const totalTrackCount = computed(() => domains.value.reduce((sum, item) => sum + (item.tracks?.length || 0), 0))
const selectedDomainDocumentCount = computed(() =>
  tracks.value.reduce((sum, item) => sum + (item.metadata?.document_count || 0), 0)
)
const currentProfile = computed(() => store.currentProfile)
const diagnosticQuestions = computed(() => store.pendingDiagnosticQuestions || [])
const diagnosisResult = computed(() => store.diagnosisResult)
const questionnaireCompleted = computed(() => Boolean(currentProfile.value && selectedDirectionId.value))
const learnerId = computed(() => {
  if (!currentUser.value?.user_id || !selectedDirectionId.value) return ''
  return `${currentUser.value.user_id}__${selectedDirectionId.value}`
})
const activeLearnerId = computed(() => currentProfile.value?.learner_id || store.currentLearnerId || '')
const learnerLabel = computed(() => {
  const userName = currentUser.value?.display_name || '当前用户'
  const directionName = selectedDirection.value?.name || '未选择方向'
  return `${userName} / ${directionName}`
})
const generatedTopic = computed(() => {
  const directionName = selectedDirection.value?.name || '当前学习方向'
  const abilityLevel = diagnosisResult.value?.ability_level || currentProfile.value?.skill_level || ''
  const weakPoints = (
    diagnosisResult.value?.weak_points ||
    currentProfile.value?.weak_points ||
    []
  )
    .filter(Boolean)
    .slice(0, 3)
  const resourceSummary = selectedResourceTypes.value.filter(Boolean).join('、')
  const focusSummary = weakPoints.length ? `，重点覆盖 ${weakPoints.join('、')}` : ''
  const levelSummary = abilityLevel ? `${abilityLevel}阶段` : '当前阶段'
  const typeSummary = resourceSummary ? `，输出 ${resourceSummary}` : ''
  return `${directionName}${levelSummary}学习资源${focusSummary}${typeSummary}`
})

const resourceTypeOptions = ['讲义', '实操指南', '分阶测试题']

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
    ElMessage.warning('请先选择学习方向')
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
      learning_direction_id: selectedDirectionId.value,
      answers,
    })

    store.setLearnerId(res.data.learner_id)
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
  if (!activeLearnerId.value) {
    ElMessage.warning('当前学习画像不存在，请重新提交方向问卷')
    return
  }
  submittingGeneration.value = true
  try {
    const payload = {
      learner_id: activeLearnerId.value,
      knowledge_base_id: selectedDirectionId.value,
      topic: generatedTopic.value,
      diagnostic_result_id: diagnosisResult.value?.diagnostic_result_id,
      resource_types: selectedResourceTypes.value,
      constraints: {
        supplemental_requirements: supplementalRequirements.value.trim(),
      },
    }
    localStorage.setItem('last_generation_request', JSON.stringify(payload))
    const res = await generateApi.createJob(payload)
    router.push({
      path: '/generate',
      query: {
        runId: res.data.run_id,
        learnerId: activeLearnerId.value,
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
    await loadDomains()
  } catch (error) {
    console.error(error)
    ElMessage.error('初始化学习方向页面失败')
  }
})
</script>

<style scoped>
.onboarding-page {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 18px;
  overflow: hidden;
}

.user-bar {
  flex-shrink: 0;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  padding: 22px;
  background: #fff;
  border: 1px solid rgba(148, 163, 184, 0.16);
  border-radius: 14px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
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
  flex: 1;
  min-height: 0;
  display: grid;
    grid-template-columns: 220px minmax(0, 1fr);
  align-items: stretch;
    gap: 18px;
  overflow-y: auto;
  padding: 0 4px 4px 0;
  scrollbar-width: thin;
}

.wizard-layout.compactWizard {
  overflow: hidden;
}

.progress-panel {
  position: sticky;
  top: 0;
  align-self: stretch;
  height: 100%;
  max-height: none;
  display: flex;
  flex-direction: column;
  gap: 0;
  overflow: hidden;
  padding: 0;
  border: 1px solid #dde4ee;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
  scrollbar-width: thin;
}

.progress-card {
  display: grid;
    grid-template-columns: 30px minmax(0, 1fr);
    gap: 9px;
  align-items: center;
  flex: 1;
  min-height: 96px;
    padding: 14px 12px;
  border: 0;
  border-bottom: 1px solid #e6edf5;
  border-radius: 0;
  background: transparent;
  color: #172033;
  text-align: left;
  cursor: pointer;
}

.progress-card:last-child {
  border-bottom: 0;
}

.progress-card.active {
  border-color: #e6edf5;
  box-shadow: inset 4px 0 0 #2563eb;
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
    width: 30px;
    height: 30px;
  border-radius: 999px;
  background: #edf3ff;
  color: #3156a6;
  font-weight: 700;
}

.progress-title {
  font-weight: 700;
    font-size: 14px;
}

.progress-desc {
  margin-top: 4px;
  color: #5f6b7a;
  line-height: 1.5;
    font-size: 12px;
}

.work-card,
.result-card {
  border-radius: 8px;
}

.work-card {
  height: 100%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
}

.work-card :deep(.el-card__header) {
  flex-shrink: 0;
}

.work-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
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

.step-panel {
  align-self: stretch;
  min-width: 0;
  min-height: 0;
}

.overview-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.overview-chip {
  padding: 12px 14px;
  border-radius: 12px;
  background: linear-gradient(180deg, #f8fbff, #f2f7ff);
  border: 1px solid #dde7f5;
}

.overview-chip span {
  display: block;
  color: #667085;
  font-size: 12px;
}

.overview-chip strong {
  display: block;
  margin-top: 6px;
  color: #172033;
  font-size: 16px;
}

.choice-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 138px;
  padding: 16px;
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
  font-size: 16px;
  font-weight: 650;
}

.compactWizard .choice-card {
  min-height: 118px;
  gap: 8px;
  padding: 14px;
}

.compactWizard .overview-strip {
  margin-bottom: 12px;
}

.compactWizard .overview-chip {
  padding: 10px 12px;
}

.compactWizard .card-grid {
  gap: 12px;
}

.compactWizard .domain-footprint {
  margin-top: 12px;
}

.compactWizard .insight-card {
  padding: 14px;
}

.compactWizard .insight-list {
  line-height: 1.5;
}

.compactWizard .action-row {
  padding-top: 14px;
}

.choice-description {
  flex: 1;
  color: #4b5563;
  line-height: 1.55;
}

.choice-meta {
  color: #667085;
  font-size: 13px;
}

.domain-footprint {
  display: grid;
  grid-template-columns: 1fr;
  gap: 14px;
  margin-top: 14px;
}

.insight-card {
  padding: 16px;
  border-radius: 14px;
  border: 1px solid #dde4ee;
  background: #ffffff;
}

.insight-card.secondary {
  background: linear-gradient(180deg, #fbfdff, #f8fbff);
}

.insight-kicker {
  display: inline-flex;
  margin-bottom: 10px;
  color: #3156a6;
  font-size: 12px;
  font-weight: 700;
}

.insight-list {
  margin: 0;
  padding-left: 18px;
  color: #4b5563;
  line-height: 1.65;
}

.domain-stage-card :deep(.el-card__body) {
  padding: 18px 22px 20px;
}

.domain-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
  align-items: stretch;
}

.compact-domain-footprint {
  align-items: start;
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

.field-hint {
  margin-top: 8px;
  color: #667085;
  font-size: 13px;
  line-height: 1.6;
}

.action-row {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: auto;
  padding-top: 22px;
  flex-wrap: wrap;
}

@media (max-width: 1024px) {
  .wizard-layout {
    grid-template-columns: 1fr;
  }

  .domain-grid,
  .overview-strip,
  .domain-footprint {
    grid-template-columns: 1fr 1fr;
  }

  .progress-panel {
    position: static;
    flex-direction: row;
    height: auto;
    max-height: none;
    overflow-x: auto;
    overflow-y: hidden;
    padding: 0 0 6px;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }

  .progress-card {
    flex: 0 0 260px;
    min-height: 92px;
    border: 1px solid #dde4ee;
    border-radius: 8px;
    background: #ffffff;
  }

  .progress-card.active {
    box-shadow: 0 0 0 2px rgba(74, 123, 246, 0.1);
  }

  .work-card {
    height: auto;
  }
}

@media (max-width: 720px) {
  .user-bar {
    flex-direction: column;
  }

  .domain-stage-card :deep(.el-card__body) {
    padding: 16px 16px 18px;
  }

  .overview-strip,
  .domain-grid,
  .domain-footprint {
    grid-template-columns: 1fr;
  }

  .user-select {
    width: 100%;
  }

  .user-actions {
    width: 100%;
  }

  .user-actions .el-button {
    width: 100%;
  }

  .progress-panel {
    top: 0;
  }

  .progress-card {
    flex-basis: 220px;
  }

  .action-row {
    position: sticky;
    bottom: 0;
    z-index: 8;
    margin: 22px -1px -1px;
    padding: 12px 0 0;
    background: linear-gradient(180deg, rgba(255, 255, 255, 0), #ffffff 30%);
  }
}

/* Learning setup visual system */
.onboarding-page {
  --setup-ink: #10233f;
  --setup-muted: #627692;
  --setup-line: #dbe6f2;
  gap: 16px;
}

.user-bar {
  position: relative;
  align-items: center;
  min-height: 132px;
  padding: 24px 28px;
  overflow: hidden;
  border-color: #d8e6f2;
  border-radius: 18px;
  background:
    radial-gradient(circle at 85% 12%, rgba(45, 212, 191, 0.18), transparent 30%),
    linear-gradient(112deg, #eff6ff 0%, #fcfdff 58%, #f0fbf8 100%);
  box-shadow: 0 14px 30px rgba(25, 61, 97, 0.06);
}

.user-bar::after {
  position: absolute;
  right: -48px;
  bottom: -72px;
  width: 220px;
  height: 170px;
  border: 1px solid rgba(72, 173, 151, 0.14);
  border-radius: 50%;
  content: '';
}

.page-kicker,
.card-kicker {
  display: block;
  color: #176f61;
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.09em;
  line-height: 1;
}

.user-bar h2 {
  position: relative;
  z-index: 1;
  margin: 8px 0 0;
  color: var(--setup-ink);
  font-size: clamp(28px, 2.2vw, 38px);
  font-weight: 800;
  letter-spacing: -0.045em;
  line-height: 1.08;
}

.user-bar p {
  position: relative;
  z-index: 1;
  margin-top: 9px;
  color: #526c8c;
  font-size: 15px;
}

.user-actions {
  position: relative;
  z-index: 1;
  align-items: center;
}

.user-actions :deep(.el-tag) {
  padding: 7px 11px;
  border-color: #bdd5fa;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.7);
  color: #2563b5;
  font-weight: 700;
}

.wizard-layout {
  grid-template-columns: 236px minmax(0, 1fr);
  gap: 16px;
  padding-right: 2px;
}

.progress-panel {
  border: 1px solid #c9dced;
  border-radius: 18px;
  background: linear-gradient(165deg, #f5faff 0%, #eaf7f3 100%);
  box-shadow: 0 14px 28px rgba(37, 78, 118, 0.08);
}

.progress-card {
  grid-template-columns: 38px minmax(0, 1fr);
  gap: 11px;
  min-height: 0;
  padding: 15px 16px;
  border-bottom-color: #d8e6f0;
  color: #183553;
}

.progress-card:hover:not(:disabled) {
  background: rgba(76, 147, 211, 0.1);
}

.progress-card.active {
  box-shadow: inset 4px 0 0 #36ad8b;
  background: linear-gradient(90deg, #eaf5ff, #e7f8f1);
}

.progress-card.done {
  background: rgba(232, 245, 251, 0.72);
}

.progress-card.disabled {
  opacity: 0.58;
}

.progress-index {
  width: 38px;
  height: 38px;
  border: 1px solid #c7ddf0;
  background: #f0f6ff;
  color: #356ea8;
  font-size: 14px;
}

.progress-card.done .progress-index {
  border-color: #9ad9c8;
  background: #e6f8f1;
  color: #168369;
}

.progress-card.active .progress-index {
  border-color: #45b89b;
  background: #35ac90;
  color: #fff;
  box-shadow: 0 0 0 5px rgba(53, 172, 144, 0.12);
}

.progress-title { color: #183553; font-size: 15px; }
.progress-desc { color: #6b829b; font-size: 12px; line-height: 1.45; }

.compactWizard .work-card :deep(.el-card__body) {
  overflow: hidden;
}

.compactWizard .action-row {
  margin-top: 14px;
  padding-top: 0;
  flex-shrink: 0;
}

.domain-stage-card .domain-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.track-stage-card .card-grid {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.compactWizard .track-stage-card :deep(.el-card__body) {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto auto;
  gap: 10px;
}

.track-stage-card .overview-strip,
.track-stage-card .domain-footprint,
.track-stage-card .action-row {
  margin: 0;
}

.track-stage-card .card-grid {
  grid-template-rows: repeat(2, minmax(0, 1fr));
  min-height: 0;
  gap: 10px;
}

.compactWizard .track-stage-card .choice-card {
  min-height: 0;
  gap: 6px;
  padding: 13px 14px;
}

.track-stage-card .choice-title { font-size: 18px; }
.track-stage-card .choice-description { font-size: 13px; line-height: 1.45; }
.track-stage-card .choice-meta { font-size: 12px; }

.compactWizard .track-stage-card .insight-card { padding: 10px 14px; }
.track-stage-card .insight-kicker { margin-bottom: 5px; }
.track-stage-card .insight-list { font-size: 13px; line-height: 1.42; }
.compactWizard .track-stage-card .action-row { padding-top: 0; }

.work-card {
  overflow: hidden;
  border: 1px solid var(--setup-line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 14px 30px rgba(25, 61, 97, 0.07);
}

.work-card :deep(.el-card__header) {
  padding: 21px 26px 18px;
  border-bottom-color: #e2eaf2;
  background: linear-gradient(100deg, #ffffff, #fbfdff);
}

.work-card :deep(.el-card__body) {
  padding: 20px 26px 22px;
  overflow: auto;
}

.card-kicker { margin-bottom: 8px; font-size: 11px; }
.card-title { color: var(--setup-ink); font-size: 26px; font-weight: 800; letter-spacing: -0.04em; line-height: 1.12; }
.card-title.small { font-size: 21px; }
.card-subtitle { margin-top: 8px; color: var(--setup-muted); font-size: 14px; line-height: 1.5; }

.overview-strip { gap: 10px; margin-bottom: 18px; }
.overview-chip {
  padding: 12px 14px;
  border-color: #d7e5f3;
  border-radius: 12px;
  background: linear-gradient(145deg, #f8fbff, #f0f6ff);
}
.overview-chip:nth-child(2n) { background: linear-gradient(145deg, #f7fcfa, #edf9f5); border-color: #d2ebe2; }
.overview-chip span { color: #70829a; font-size: 12px; }
.overview-chip strong { margin-top: 6px; color: #1b3657; font-size: 18px; }

.choice-card {
  min-height: 148px;
  padding: 18px;
  border-color: #d9e4ef;
  border-radius: 14px;
  background: linear-gradient(150deg, #ffffff, #fbfdff);
  box-shadow: 0 5px 14px rgba(30, 65, 104, 0.025);
  transition: border-color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.choice-card:hover:not(:disabled) {
  border-color: #9cc6eb;
  box-shadow: 0 12px 22px rgba(43, 93, 145, 0.09);
  transform: translateY(-2px);
}

.choice-card.selected {
  border-color: #2b75dd;
  background: linear-gradient(145deg, #f6faff, #eff8f7);
  box-shadow: 0 0 0 3px rgba(53, 118, 219, 0.1), 0 12px 22px rgba(43, 93, 145, 0.08);
}

.choice-title { color: #163353; font-size: 20px; font-weight: 800; letter-spacing: -0.025em; }
.choice-description { color: #5d728d; font-size: 14px; line-height: 1.6; }
.choice-meta { color: #49708e; font-size: 13px; font-weight: 600; }

.selection-pill { border: 1px solid #d2e4f9; background: #f2f7ff; color: #3168ad; }
.questionnaire-form { max-width: 920px; }
.questionnaire-form :deep(.el-form-item__label), .question-title { color: #1c3859; font-size: 15px; font-weight: 750; }
.questionnaire-form :deep(.el-input__wrapper), .questionnaire-form :deep(.el-select__wrapper), .questionnaire-form :deep(.el-textarea__inner) { box-shadow: 0 0 0 1px #d6e2ef inset; }
.questionnaire-form :deep(.el-input__wrapper:hover), .questionnaire-form :deep(.el-select__wrapper:hover), .questionnaire-form :deep(.el-textarea__inner:hover) { box-shadow: 0 0 0 1px #8eb9e8 inset; }

.domain-footprint { margin-top: 16px; }
.insight-card { border-color: #d5e5f1; border-radius: 14px; background: linear-gradient(105deg, #f8fbff, #f1faf7); }
.insight-kicker { color: #187864; font-size: 12px; letter-spacing: 0.06em; text-transform: uppercase; }
.insight-list { color: #536c87; font-size: 14px; }

.result-card { overflow: hidden; border-color: #d6e7f1; border-radius: 14px; box-shadow: none; }
.result-card :deep(.el-card__header) { padding: 16px 18px; border-bottom-color: #e2ebf1; background: #f8fcfb; }
.result-card :deep(.el-card__body) { padding: 0; }
.result-card :deep(.el-descriptions__label) { background: #f7faff; color: #5d738e; }
.result-card :deep(.el-descriptions__content) { color: #1b385a; }

.action-row { padding-top: 20px; }
.action-row :deep(.el-button) { min-width: 96px; height: 38px; border-radius: 9px; font-weight: 700; }
.action-row :deep(.el-button--primary), .user-actions :deep(.el-button--primary) { border-color: #328de6; background: #328de6; }

@media (max-width: 1180px) {
  .wizard-layout { grid-template-columns: 210px minmax(0, 1fr); }
  .card-title { font-size: 23px; }
  .choice-title { font-size: 18px; }
  .track-stage-card .card-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}

@media (max-width: 1024px) {
  .wizard-layout { gap: 14px; }
  .progress-panel { border: 0; border-radius: 0; background: transparent; box-shadow: none; }
  .progress-card { border: 1px solid #d9e5f0; border-radius: 12px; background: #fff; color: #183553; }
  .progress-card:hover:not(:disabled), .progress-card.done { background: #f5f9ff; }
  .progress-card.active { box-shadow: inset 0 -3px 0 #3bb89c; background: #f1faf7; }
  .progress-index { border-color: #cddff2; background: #eff6ff; color: #356ea8; }
  .progress-title { color: #183553; }
  .progress-desc { color: #6b8099; }
  .domain-stage-card .domain-grid, .track-stage-card .card-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 720px) {
  .user-bar { min-height: 0; padding: 20px; }
  .user-bar h2 { font-size: 30px; }
  .work-card :deep(.el-card__header), .work-card :deep(.el-card__body) { padding-left: 18px; padding-right: 18px; }
  .card-title { font-size: 22px; }
  .overview-strip { gap: 8px; }
  .domain-stage-card .domain-grid, .track-stage-card .card-grid { grid-template-columns: 1fr; }
}
</style>
