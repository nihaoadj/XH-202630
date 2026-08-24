<template>
  <div class="feedback-page">
    <section class="feedback-hero">
      <div class="task-selection task-selection-inline">
        <label class="task-filter-field">
          <span class="task-selection-label">学习画像</span>
          <el-select v-model="selectedLearnerId" filterable placeholder="选择学习画像" class="profile-select" @change="handleProfileChange">
            <el-option v-for="profile in profileOptions" :key="profile.learner_id" :label="profile.label" :value="profile.learner_id" />
          </el-select>
        </label>
        <label class="task-filter-field">
          <span class="task-selection-label">本轮资源批次</span>
          <el-select v-model="selectedRunId" filterable placeholder="选择要反馈的学习资源批次" class="task-select" @change="selectBatch">
            <el-option v-for="task in taskGroups" :key="task.runId" :label="task.label" :value="task.runId" />
          </el-select>
        </label>
        <el-button class="start-evaluation-button" type="primary" :icon="VideoPlay" @click="startEvaluation" :disabled="!selectedRunId">{{ selectedBatchHasFeedback ? '再次测评' : '开始测评' }}</el-button>
      </div>

      <div v-if="activeTask" class="task-stats hero-task-stats">
        <div><span>学习方向</span><strong>{{ currentDirectionName }}</strong></div>
        <div><span>本轮资源</span><strong>{{ activeTask.resources.length }} 份</strong></div>
        <div><span>测评题目</span><strong>{{ evaluation.questions.length }} 题</strong></div>
        <div><span>完成进度</span><strong>{{ answeredCount }} / {{ evaluation.questions.length || 0 }}</strong></div>
      </div>
      <p v-else class="task-empty-tip">暂时没有可用于反馈的资源任务，请先完成一轮学习资源生成。</p>
    </section>

    <section v-if="!result" ref="workspaceRef" class="feedback-workspace" :class="{ 'has-empty-evaluation': !evaluation.questions.length }">
      <article class="evaluation-panel" :class="{ 'is-empty-evaluation': !evaluation.questions.length }">
        <div class="section-heading">
          <div>
            <span class="page-kicker">STEP 01 · PRACTICE CHECK</span>
            <h3>完成知识测评</h3>
            <p>题目会优先覆盖本轮资源涉及的知识点。</p>
          </div>
          <span class="progress-pill" :class="{ ready: allQuestionsAnswered }">{{ answeredCount }} / {{ evaluation.questions.length }} 已作答</span>
        </div>

        <el-empty v-if="!evaluation.questions.length" description="选择任务后即可加载本轮测评题。" :image-size="76" />

        <div v-else class="question-list">
          <article v-for="(question, index) in evaluation.questions" :key="question.question_id" class="question-card">
            <div class="question-topline">
              <span class="question-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <div class="question-tools">
                <el-tag size="small" effect="plain">{{ question.knowledge_point || '综合能力' }}</el-tag>
                <el-button type="primary" text size="small" @click="requestTutorHint(question)">需要提示</el-button>
              </div>
            </div>
            <strong>{{ question.question }}</strong>

            <el-radio-group v-if="question.question_type === 'single_choice' && question.options?.length" v-model="evaluationAnswers[question.question_id]" class="answer-options">
              <el-radio v-for="option in question.options" :key="option" :label="option" :value="option">{{ option }}</el-radio>
            </el-radio-group>
            <el-checkbox-group v-else-if="question.question_type === 'multiple_choice' && question.options?.length" v-model="evaluationAnswers[question.question_id]" class="answer-options">
              <el-checkbox v-for="option in question.options" :key="option" :label="option">{{ option }}</el-checkbox>
            </el-checkbox-group>
            <el-input v-else v-model="evaluationAnswers[question.question_id]" type="textarea" :rows="3" placeholder="写下你的答案或思路" />
          </article>
        </div>
      </article>

      <aside class="reflection-panel">
        <div class="section-heading compact-heading">
          <div>
            <span class="page-kicker">STEP 02 · REFLECT</span>
            <h3>记录学习感受</h3>
            <p>这些反馈会跟随本次练习保存，为后续推荐提供依据。</p>
          </div>
        </div>

        <div class="reflection-fields">
          <div class="completion-row">
            <div><strong>本轮学习已完成</strong><span>完成后，系统会更新学习路径</span></div>
            <el-switch v-model="form.completed" />
          </div>
          <div class="tutor-usage-row"><span>Tutor 求助</span><strong>{{ tutorHelpCount }} 次</strong></div>
          <div class="field-grid">
            <label><span>学习耗时 <small>{{ studyTimeLabel }}</small></span><el-input-number v-model="form.time_spent_seconds" :min="0" :step="300" controls-position="right" /></label>
            <label><span>难度感受</span><el-select v-model="form.difficulty_feeling" placeholder="选择感受"><el-option label="偏简单" value="too_easy" /><el-option label="刚刚好" value="fit" /><el-option label="偏难" value="too_hard" /></el-select></label>
          </div>
          <label class="rating-field"><span>掌握自评</span><el-rate v-model="form.self_rating" :max="5" show-score /></label>
          <label><span>最有帮助的内容</span><el-input v-model="form.helpful_part" placeholder="例如：案例、步骤拆解、总结" /></label>
          <label><span>仍然困惑的地方</span><el-input v-model="form.confusing_part" placeholder="例如：术语、关键步骤或实际迁移" /></label>
          <label><span>补充反馈</span><el-input v-model="form.comment" type="textarea" :rows="4" placeholder="可以说明你期待下一轮更强化哪些内容，例如增加案例、练习或提高难度。" /></label>
        </div>

        <div class="submit-box">
          <div>
            <strong>{{ allQuestionsAnswered ? '可以提交本轮反馈' : '请先完成全部测评题' }}</strong>
            <span>{{ allQuestionsAnswered ? '系统会根据结果为下一轮学习调整资源与重点。' : `还差 ${Math.max(evaluation.questions.length - answeredCount, 0)} 题未作答` }}</span>
          </div>
          <el-button class="submit-feedback-button" type="primary" :icon="CircleCheck" :loading="submitting" :disabled="!canSubmit" @click="submitEvaluation">提交反馈</el-button>
        </div>
      </aside>
    </section>

    <section v-if="result" class="result-panel">
      <header class="result-header">
        <div class="result-summary">
        <span class="page-kicker">LEARNING RESULT</span>
        <h3>这次学习的回顾</h3>
        <p>{{ friendlyText(result.decision.decision_reason) }}</p>
        <div v-if="weakKnowledgePoints.length" class="weak-points"><span>优先巩固</span><b v-for="item in weakKnowledgePoints" :key="item">{{ item }}</b></div>
        </div>
        <div class="result-metrics">
        <div><span>测评正确率</span><strong>{{ Math.round(result.attempt.overall_score * 100) }}%</strong></div>
        <div><span>答对题数</span><strong>{{ attemptCorrectSummary }}</strong></div>
        <div><span>当前建议</span><strong>{{ feedbackActionLabel(result.decision.action) }}</strong></div>
        <div><span>下一步资源</span><strong>{{ result.followup_run_id ? '已确认' : '由你决定' }}</strong></div>
        </div>
      </header>
      <article v-if="result.analysis" class="analysis-summary">
        <div class="analysis-heading"><strong>学习小结</strong><span>根据你的作答和学习感受整理</span></div>
        <p>{{ friendlyText(result.analysis.summary) }}</p>
        <p v-if="result.analysis.reflection_insight" class="reflection-insight">{{ friendlyText(result.analysis.reflection_insight) }}</p>
        <ul v-if="result.analysis.learner_suggestions?.length"><li v-for="item in result.analysis.learner_suggestions" :key="item">{{ friendlyText(item) }}</li></ul>
      </article>
      <article v-if="feedbackReport.capability_results?.length" class="capability-result-panel">
        <div class="analysis-heading"><strong>能力节点结果</strong><span>仅基于服务端正式判分</span></div>
        <div class="capability-result-list">
          <div v-for="item in feedbackReport.capability_results" :key="item.skill_node_id">
            <strong>{{ item.skill_node_id }}</strong><span>{{ Math.round((item.score || 0) * 100) }}% · {{ item.mastery_status }}</span>
          </div>
        </div>
      </article>
      <section class="next-step-panel">
        <div class="next-step-copy"><span class="page-kicker">NEXT STEP</span><h4>接下来怎么学，由你决定</h4><p>可先针对本次已确认的薄弱点生成强化包，或继续学习新的能力节点。</p><small v-if="tierProgress">当前学习阶：{{ tierProgress.active_tier }} · 已解锁至第 {{ tierProgress.highest_unlocked_tier }} 阶<span v-if="tierProgress.remediation_return_tier"> · 补救后返回第 {{ tierProgress.remediation_return_tier }} 阶</span></small></div>
        <div class="next-step-actions">
          <template v-if="!result.followup_run_id">
            <section v-if="correctionPackageOption" class="correction-package-card" :class="{ 'is-disabled': !correctionPackageOption.eligible }">
              <div><strong>强化薄弱点</strong><p>生成一份包含概念补救、对照辨析与递进练习的薄弱点强化包。</p></div>
              <el-checkbox-group v-if="correctionPackageOption.eligible" v-model="selectedCorrectionNodes" class="resource-type-choice">
                <el-checkbox v-for="node in correctionPackageOption.selectable_targets" :key="node.skill_node_id" :label="node.skill_node_id">{{ node.name }}</el-checkbox>
              </el-checkbox-group>
              <small v-if="correctionPackageOption.eligible">系统锁定难度：{{ correctionPackageOption.recommended_difficulty }}；请选择 1–3 个目标。</small>
              <small v-else>{{ correctionPackageOption.disabled_reason_code === 'NO_LEARNED_NOT_MASTERED_TARGET' ? '本次没有已学习但未掌握的能力节点，请选择学习新知识。' : '当前不能创建强化包。' }}</small>
              <el-button type="primary" :loading="selectingOption === correctionPackageOption.option_id" :disabled="!correctionPackageOption.eligible || !selectedCorrectionNodes.length" @click="selectCorrectionPackage">生成薄弱点强化包</el-button>
            </section>
            <div v-if="curriculumProgress" class="curriculum-progress-row">
              <strong>13 节点进度：{{ curriculumProgress.completed_count }}/{{ curriculumProgress.total_count }} 已完成</strong>
              <span>待学习 {{ curriculumProgress.unplanned_count }} · 待验证 {{ curriculumProgress.exposed_count + curriculumProgress.verification_pending_count }} · 需巩固 {{ curriculumProgress.reinforcement_due_count }}</span>
            </div>
            <div v-if="generationOptions" class="intent-selection-row">
              <span>学习新知识：</span>
              <small>仅显示当前学习阶的节点；节点不足 3 个时不会跨阶补位。</small>
            </div>
            <div v-if="generationOptions" class="intent-node-row">
              <span>选择能力节点（最多 3 个）：</span>
              <el-checkbox-group v-model="selectedIntentNodes" class="resource-type-choice" :max="3">
                <el-checkbox v-for="node in intentCandidates" :key="node.skill_node_id" :label="node.skill_node_id" :disabled="node.blocked_by_node_ids?.length > 0">
                  {{ node.name }} · 第 {{ node.tier }} 阶<small v-if="node.blocked_by_node_ids?.length">（需先学习前置能力）</small>
                </el-checkbox>
              </el-checkbox-group>
              <em v-if="!intentCandidates.length">当前没有此类可选能力节点。</em>
            </div>
            <div class="resource-selection-row"><span>生成资源：</span>
          <el-checkbox-group v-model="selectedResourceTypes" class="resource-type-choice">
            <el-checkbox label="讲义">讲义</el-checkbox>
            <el-checkbox label="实操指南">实操指南</el-checkbox>
            <el-checkbox label="分阶测试题">分阶测试题</el-checkbox>
            <el-checkbox label="复习清单">复习清单</el-checkbox>
            <el-checkbox label="案例分析">案例分析</el-checkbox>
          </el-checkbox-group>
          <el-select v-model="selectedDifficulty" class="difficulty-choice" aria-label="资源难度" :disabled="Boolean(generationOptions)">
            <el-option label="初级" value="初级" />
            <el-option label="中级" value="中级" />
            <el-option label="高级" value="高级" />
          </el-select>
          <el-button
            class="custom-generation-button"
            type="primary"
            :loading="selectingOption === 'custom-selection'"
            :disabled="!selectedResourceTypes.length || (generationOptions && !selectedIntentNodes.length)"
            @click="selectFeedbackOption('custom-selection')"
          >
            生成已选资源
          </el-button>
            </div>
          </template>
        </div>
      </section>
      <div class="result-actions"><el-button plain @click="router.push('/report')">查看学习报告</el-button><el-button type="primary" plain :disabled="!result.followup_run_id" @click="goToFollowupRun">查看已选资源</el-button></div>
    </section>

    <TutorDrawer
      v-model="tutorOpen"
      :learner-id="form.learner_id"
      :resource="tutorResource"
      :batch-id="selectedRunId"
      :run-id="tutorResource?.run_id || ''"
      context-type="question_help"
      :question-id="tutorQuestion?.question_id || ''"
      :title="tutorQuestion ? `第 ${evaluation.questions.findIndex((item) => item.question_id === tutorQuestion.question_id) + 1} 题提示` : '题目提示'"
      @turn-saved="recordTutorHelp"
      @session-loaded="restoreTutorHelp"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, VideoPlay } from '@element-plus/icons-vue'
import { useRouter } from 'vue-router'
import { feedbackApi, generateApi, knowledgeApi, profileApi, resourceApi } from '../../api'
import { useAppStore } from '../../stores/app'
import { formatDateTime } from '../../utils/generationDisplay'
import TutorDrawer from '../tutor/TutorDrawer.vue'
import { countTutorTurns } from '../../utils/tutorState'

const router = useRouter()
const store = useAppStore()
const workspaceRef = ref(null)
const selectedLearnerId = ref(store.currentLearnerId || localStorage.getItem('last_learner_id') || '')
const form = reactive({ learner_id: selectedLearnerId.value, completed: true, time_spent_seconds: 1800, self_rating: 4, difficulty_feeling: '', helpful_part: '', confusing_part: '', comment: '' })
const resources = ref([])
const generationJobs = ref([])
const feedbackResults = ref([])
const profiles = ref([])
const tracks = ref([])
const selectedRunId = ref(localStorage.getItem('current_generation_run_id') || '')
const submitting = ref(false)
const selectingOption = ref('')
const result = ref(null)
const selectedResourceTypes = ref([])
const selectedDifficulty = ref('中级')
const learningIntent = ref('reinforce_weakness')
const selectedIntentNodes = ref([])
const evaluation = reactive({ topic: '', questions: [], resourceIds: [] })
const evaluationAnswers = reactive({})
const tutorOpen = ref(false)
const tutorQuestion = ref(null)
const tutorHelpCount = ref(0)

const currentDirectionName = computed(() => store.currentLearningDirectionName || localStorage.getItem('learning_direction_name') || '未选择学习方向')
const profileOptions = computed(() => profiles.value.map((profile) => ({
  ...profile,
  label: `${resolveTrackName(profile.knowledge_base_id)} / ${formatSkillLevel(profile.skill_level)}`,
})))
const completedRunIds = computed(() => new Set(feedbackResults.value.flatMap((item) => [
  item.attempt?.source_run_id,
  item.attempt?.metadata?.session_id,
]).filter(Boolean)))
const visibleResources = computed(() => {
  const supersededRunIds = new Set(
    generationJobs.value.filter((job) => job.superseded_by_run_id).map((job) => job.run_id),
  )
  const publishedTypesByRun = new Map()
  for (const resource of resources.value) {
    if (!publishedTypesByRun.has(resource.run_id)) publishedTypesByRun.set(resource.run_id, new Set())
    publishedTypesByRun.get(resource.run_id).add(resource.resource_type)
  }
  const latestReplacementRunByType = new Map()
  for (const job of generationJobs.value) {
    if (job.superseded_by_run_id) continue
    const batchId = job.batch_id || job.run_id
    const requestedTypes = new Set(job.request_payload?.resource_types || [])
    const types = (job.request_payload?.constraints?.replacement_resource_types || [])
      .filter((type) => (
        requestedTypes.has(type)
        && publishedTypesByRun.get(job.run_id)?.has(type)
      ))
    for (const type of types) {
      const key = `${batchId}:${type}`
      const current = latestReplacementRunByType.get(key)
      if (!current || String(current.created_at || '') < String(job.created_at || '')) {
        latestReplacementRunByType.set(key, job)
      }
    }
  }
  return resources.value.filter((resource) => {
    if (supersededRunIds.has(resource.run_id)) return false
    const batchId = resource.batch_id || resource.run_id
    const replacement = latestReplacementRunByType.get(`${batchId}:${resource.resource_type}`)
    return !replacement || resource.run_id === replacement.run_id
  })
})
const taskGroups = computed(() => {
  const groups = new Map()
  for (const resource of visibleResources.value) {
    const batchId = resource.batch_id || resource.run_id || `resource:${resource.resource_id}`
    if (!groups.has(batchId)) groups.set(batchId, { runId: batchId, batchId, shortRunId: batchId.startsWith('resource:') ? '独立资源' : batchId.slice(0, 8).toUpperCase(), finishedAt: resource.created_at || '', resources: [] })
    const task = groups.get(batchId)
    task.resources.push(resource)
    if (resource.created_at && (!task.finishedAt || resource.created_at > task.finishedAt)) task.finishedAt = resource.created_at
  }
  const jobsByBatch = new Map()
  for (const job of generationJobs.value) {
    const batchId = job.batch_id || job.run_id
    if (!jobsByBatch.has(batchId)) jobsByBatch.set(batchId, [])
    jobsByBatch.get(batchId).push(job)
  }
  let initialIndex = 0
  let feedbackIndex = 0
  return Array.from(groups.values())
    .sort((left, right) => String(left.finishedAt).localeCompare(String(right.finishedAt)))
    .map((task) => {
      const isFeedbackBatch = (jobsByBatch.get(task.batchId) || []).some(
        (job) => Boolean(job.request_payload?.constraints?.feedback_attempt_id),
      )
      const batchLabel = isFeedbackBatch
        ? `反馈批次 ${String(++feedbackIndex).padStart(2, '0')}`
        : `初始资源批次 ${String(++initialIndex).padStart(2, '0')}`
      const completed = completedRunIds.value.has(task.runId)
      return {
        ...task,
        completed,
        batchLabel,
        label: `${batchLabel} / ${task.resources.length} 份资源 / ${formatTaskTime(task.finishedAt)} / ${completed ? '已反馈' : '待反馈'}`,
      }
    })
})
const activeTask = computed(() => taskGroups.value.find((item) => item.runId === selectedRunId.value) || taskGroups.value[0] || null)
const selectedBatchHasFeedback = computed(() => Boolean(taskGroups.value.find((item) => item.runId === selectedRunId.value)?.completed))
const tutorResource = computed(() => {
  const questionResourceId = String(tutorQuestion.value?.question_id || '').split(':', 1)[0]
  return activeTask.value?.resources?.find((item) => item.resource_id === questionResourceId)
    || activeTask.value?.resources?.[0]
    || null
})
const answeredCount = computed(() => evaluation.questions.reduce((count, question) => count + (hasAnswer(evaluationAnswers[question.question_id]) ? 1 : 0), 0))
const allQuestionsAnswered = computed(() => Boolean(evaluation.questions.length && answeredCount.value === evaluation.questions.length))
const canSubmit = computed(() => Boolean(selectedRunId.value && allQuestionsAnswered.value))
const weakKnowledgePoints = computed(() => (result.value?.knowledge_state_updates || []).filter((item) => item.after?.status === 'weak').map((item) => item.knowledge_point_id))
const attemptCorrectSummary = computed(() => {
  const points = result.value?.attempt?.knowledge_point_results || []
  if (!points.length) return '-'
  return `${points.reduce((sum, item) => sum + item.correct_count, 0)} / ${points.reduce((sum, item) => sum + item.total_count, 0)}`
})
const studyTimeLabel = computed(() => `${Math.floor((form.time_spent_seconds || 0) / 60)} 分钟`)
const generationOptions = computed(() => result.value?.generation_options || null)
const tierProgress = computed(() => generationOptions.value?.tier_progress || null)
const correctionPackageOption = computed(() => result.value?.correction_package_option || null)
const curriculumProgress = computed(() => generationOptions.value?.curriculum_progress || null)
const intentCandidates = computed(() => generationOptions.value?.[learningIntent.value] || [])
const feedbackReport = computed(() => result.value?.feedback_report || {})
const selectedCorrectionNodes = ref([])

watch(() => store.currentLearnerId, (value) => {
  if (value && value !== selectedLearnerId.value) {
    selectedLearnerId.value = value
    form.learner_id = value
  }
})
watch(result, (value) => {
  const option = value?.resource_options?.[0]
  if (option) {
    selectedResourceTypes.value = [...option.resource_types]
    selectedDifficulty.value = option.difficulty
  }
  const options = value?.generation_options
  if (options) {
    learningIntent.value = 'learn_new_knowledge'
    const recommended = new Set(options.recommended_node_ids || [])
    const candidates = options[learningIntent.value] || []
    selectedIntentNodes.value = candidates
      .filter((item) => recommended.has(item.skill_node_id) && !(item.blocked_by_node_ids || []).length)
      .slice(0, 3)
      .map((item) => item.skill_node_id)
    if (!selectedIntentNodes.value.length) selectedIntentNodes.value = candidates
      .filter((item) => !(item.blocked_by_node_ids || []).length)
      .slice(0, 3)
      .map((item) => item.skill_node_id)
  } else selectedIntentNodes.value = []
  const correction = value?.correction_package_option
  selectedCorrectionNodes.value = correction?.eligible ? [...(correction.recommended_target_ids || [])].slice(0, 3) : []
})

function hasAnswer(value) { return Array.isArray(value) ? value.length > 0 : String(value || '').trim().length > 0 }
function resolveTrackName(trackId) {
  return tracks.value.find((track) => track.track_id === trackId || track.knowledge_base_id === trackId)?.name || trackId || '未选择学习方向'
}
function formatSkillLevel(level) { return ({ beginner: '初级', intermediate: '中级', advanced: '高级' })[level] || level || '未分级' }
function resetEvaluationAnswers() { Object.keys(evaluationAnswers).forEach((key) => delete evaluationAnswers[key]) }
function formatTaskTime(value) { return formatDateTime(value) }
function feedbackActionLabel(action) { return { remediate: '补救学习', practice: '强化练习', advance: '继续进阶', hold: '保持路径', human_review: '人工复核' }[action] || action || '已记录' }
function friendlyText(value) {
  return String(value || '')
    .replaceAll('学习者', '你')
    .replaceAll('系统建议', '建议')
    .replaceAll('系统', '本次结果')
    .replaceAll('画像', '学习情况')
    .replaceAll('客观成绩', '测评结果')
}
function buildIdempotencyKey(runId, submittedAt) { return `web-${runId.slice(0, 24)}-${submittedAt.toISOString().replace(/[^0-9]/g, '')}`.slice(0, 128) }
function resetIntentNodes() {
  selectedIntentNodes.value = intentCandidates.value
    .filter((item) => !(item.blocked_by_node_ids || []).length)
    .slice(0, 3)
    .map((item) => item.skill_node_id)
}
function scrollToWorkspace() { workspaceRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
async function startEvaluation() { await loadEvaluationSession({ forceNew: true }); scrollToWorkspace() }
function selectBatch() {
  const existing = feedbackResults.value.find((item) => (
    item.attempt?.source_run_id === selectedRunId.value
    || item.attempt?.metadata?.session_id === selectedRunId.value
  ))
  result.value = existing || null
  if (!existing) {
    evaluation.questions = []
    evaluation.resourceIds = []
    resetEvaluationAnswers()
  }
}
async function loadProfiles() {
  try {
    const [profileResponse, domainResponse] = await Promise.all([
      profileApi.list({ page: 1, page_size: 50 }),
      knowledgeApi.listDomains(),
    ])
    profiles.value = profileResponse.data.items || profileResponse.data.profiles || []
    tracks.value = (domainResponse.data.domains || []).flatMap((domain) => domain.tracks || [])
    if (!profiles.value.length) {
      selectedLearnerId.value = ''
      form.learner_id = ''
      return
    }
    if (!profiles.value.some((profile) => profile.learner_id === selectedLearnerId.value)) {
      selectedLearnerId.value = profiles.value[0].learner_id
      form.learner_id = selectedLearnerId.value
    }
  } catch (error) {
    console.error(error)
    ElMessage.warning('学习画像加载失败')
  }
}
async function handleProfileChange() {
  form.learner_id = selectedLearnerId.value
  localStorage.setItem('last_learner_id', selectedLearnerId.value)
  result.value = null
  selectedRunId.value = ''
  evaluation.questions = []
  evaluation.resourceIds = []
  resetEvaluationAnswers()
  tutorHelpCount.value = 0
  await loadResources()
}
function tutorCountKey(batchId = selectedRunId.value) { return `tutor_help_count:${form.learner_id}:${batchId}` }
function requestTutorHint(question) { tutorQuestion.value = question; tutorOpen.value = true }
function recordTutorHelp() {
  tutorHelpCount.value += 1
  localStorage.setItem(tutorCountKey(), String(tutorHelpCount.value))
}
function restoreTutorHelp({ turns }) {
  const persisted = Number(localStorage.getItem(tutorCountKey()) || 0)
  tutorHelpCount.value = Math.max(tutorHelpCount.value, persisted, countTutorTurns(turns))
  localStorage.setItem(tutorCountKey(), String(tutorHelpCount.value))
}
function syncSelectedRun() {
  if (!taskGroups.value.length) { selectedRunId.value = ''; return }
  const storedId = localStorage.getItem('current_generation_run_id') || ''
  if (taskGroups.value.some((item) => item.runId === selectedRunId.value)) return
  const storedResource = visibleResources.value.find((item) => item.run_id === storedId)
  const storedBatchId = storedResource?.batch_id || storedResource?.run_id || storedId
  selectedRunId.value = taskGroups.value.some((item) => item.runId === storedBatchId) ? storedBatchId : taskGroups.value[0].runId
}
async function loadResources() {
  if (!form.learner_id) return
  try {
    const [res, jobsRes, resultsRes] = await Promise.all([
      resourceApi.listByLearner(form.learner_id),
      generateApi.listJobs(form.learner_id),
      feedbackApi.listResults(form.learner_id, { limit: 50 }),
    ])
    resources.value = res.data.resources || []
    generationJobs.value = jobsRes.data.items || []
    feedbackResults.value = resultsRes.data || []
    syncSelectedRun()
    selectBatch()
  }
  catch (error) { console.error(error); ElMessage.warning('资源加载失败，请先完成资源生成。') }
}
async function loadEvaluationSession({ forceNew = false } = {}) {
  const existing = feedbackResults.value.find((item) => (
    item.attempt?.source_run_id === selectedRunId.value
    || item.attempt?.metadata?.session_id === selectedRunId.value
  ))
  if (existing && !forceNew) { result.value = existing; return }
  result.value = null
  if (!form.learner_id || !selectedRunId.value) return
  try {
    const res = await feedbackApi.getBatchEvaluationSession(form.learner_id, selectedRunId.value)
    evaluation.topic = res.data.topic || ''
    evaluation.questions = res.data.questions || []
    evaluation.resourceIds = res.data.resource_ids || []
    resetEvaluationAnswers()
    evaluation.questions.forEach((question) => { evaluationAnswers[question.question_id] = question.question_type === 'multiple_choice' ? [] : '' })
    localStorage.setItem('current_generation_run_id', selectedRunId.value)
    tutorQuestion.value = null
    tutorHelpCount.value = Number(localStorage.getItem(tutorCountKey()) || 0)
  } catch (error) {
    console.error(error); evaluation.topic = ''; evaluation.questions = []; evaluation.resourceIds = []; resetEvaluationAnswers()
    ElMessage.error(error?.response?.data?.message || '测评题加载失败')
  }
}
async function submitEvaluation() {
  if (!canSubmit.value) { ElMessage.warning('请先完成全部测评题。'); return }
  submitting.value = true
  try {
    const submittedAt = new Date()
    const payload = {
      learner_id: form.learner_id, batch_id: selectedRunId.value, source_resource_id: evaluation.resourceIds[0] || activeTask.value?.resources?.[0]?.resource_id,
      idempotency_key: buildIdempotencyKey(selectedRunId.value, submittedAt), expected_profile_version: store.currentProfile?.profile_version || 1,
      submitted_at: submittedAt.toISOString(), duration_ms: (form.time_spent_seconds || 0) * 1000, hint_count: tutorHelpCount.value,
      answers: evaluation.questions.map((question) => ({ question_id: question.question_id, answer: evaluationAnswers[question.question_id] })),
      metadata: { source: 'feedback_view', client_version: 'web', session_id: selectedRunId.value, learning_reflection: { completed: form.completed, time_spent_seconds: form.time_spent_seconds, self_rating: form.self_rating, difficulty_feeling: form.difficulty_feeling, helpful_part: form.helpful_part.trim(), confusing_part: form.confusing_part.trim(), comment: form.comment.trim() } },
    }
    const res = await feedbackApi.submitBatchAttempt(payload)
    result.value = res.data
    feedbackResults.value = [res.data, ...feedbackResults.value.filter((item) => item.attempt?.attempt_id !== res.data.attempt?.attempt_id)]
    if (store.currentProfile) store.setCurrentProfile({ ...store.currentProfile, profile_version: res.data.profile_version })
    ElMessage.success('本轮练习反馈已提交')
  } catch (error) { console.error(error); ElMessage.error(error?.response?.data?.message || '提交失败，请稍后再试') }
  finally { submitting.value = false }
}
async function selectFeedbackOption(optionId) {
  if (!result.value?.attempt?.attempt_id) return
  selectingOption.value = optionId
  try {
    const res = await feedbackApi.selectFollowup({
      learner_id: form.learner_id,
      attempt_id: result.value.attempt.attempt_id,
      option_id: optionId,
      resource_types: selectedResourceTypes.value,
      ...(!generationOptions.value ? { difficulty: selectedDifficulty.value } : {}),
      ...(generationOptions.value ? {
        learning_intent: learningIntent.value,
        selected_skill_node_ids: selectedIntentNodes.value,
        next_generation_snapshot_hash: generationOptions.value.snapshot_hash,
      } : {}),
    })
    result.value = res.data
    ElMessage.success('已确认下一步资源方案，正在创建生成任务')
  } catch (error) {
    console.error(error); ElMessage.error(error?.response?.data?.detail || '资源方案确认失败')
  } finally { selectingOption.value = '' }
}
async function selectCorrectionPackage() {
  const option = correctionPackageOption.value
  if (!option?.eligible || !result.value?.attempt?.attempt_id || !generationOptions.value) return
  selectingOption.value = option.option_id
  try {
    const res = await feedbackApi.selectFollowup({
      learner_id: form.learner_id, attempt_id: result.value.attempt.attempt_id,
      option_id: option.option_id, learning_intent: 'reinforce_weakness',
      selected_skill_node_ids: selectedCorrectionNodes.value,
      next_generation_snapshot_hash: option.snapshot_hash,
    })
    result.value = res.data
    ElMessage.success('薄弱点强化包正在创建')
  } catch (error) {
    console.error(error); ElMessage.error(error?.response?.data?.detail || '强化包创建失败')
  } finally { selectingOption.value = '' }
}
function goToFollowupRun() {
  if (!result.value?.followup_run_id) return
  localStorage.setItem('current_generation_run_id', result.value.followup_run_id)
  router.push({ path: '/generate', query: { runId: result.value.followup_run_id, learnerId: form.learner_id } })
}
onMounted(async () => { await loadProfiles(); await loadResources() })
</script>

<style scoped>
.feedback-page { --ink:#10233f; --muted:#617691; --line:#dce6f1; display:flex; flex-direction:column; gap:16px; color:var(--ink); }
.feedback-hero,.task-panel,.evaluation-panel,.reflection-panel,.result-panel,.history-panel { border:1px solid var(--line); border-radius:18px; background:rgba(255,255,255,.96); box-shadow:0 12px 28px rgba(24,60,96,.055); }
.feedback-hero { position:relative; display:grid; grid-template-columns:minmax(0,1fr) minmax(290px,.55fr); gap:28px; align-items:center; min-height:164px; padding:25px 28px; overflow:hidden; background:radial-gradient(circle at 87% 15%,rgba(50,206,176,.2),transparent 29%),linear-gradient(118deg,#eff6ff,#fbfdff 58%,#edf4ff); }
.feedback-hero::after { position:absolute; right:24%; bottom:-80px; width:210px; height:150px; border:1px solid rgba(71,170,148,.16); border-radius:50%; content:''; }.hero-copy,.hero-focus { position:relative; z-index:1; }.page-kicker { display:block; color:#2058a7; font-size:12px; font-weight:800; letter-spacing:.09em; line-height:1; }.hero-copy h2 { margin:8px 0 0; font-size:clamp(30px,2.4vw,40px); font-weight:800; letter-spacing:-.045em; line-height:1.08; }.hero-copy p { max-width:720px; margin:10px 0 0; color:#536d8d; font-size:15px; line-height:1.6; }.hero-actions { display:flex; gap:10px; margin-top:15px; }.hero-actions :deep(.el-button) { height:36px; font-weight:700; }
.hero-focus { padding:18px 20px; border:1px solid rgba(255,255,255,.86); border-radius:14px; background:rgba(255,255,255,.76); backdrop-filter:blur(8px); }.focus-state { display:flex; align-items:center; gap:8px; color:#607891; font-size:12px; }.focus-state i { width:8px; height:8px; border-radius:50%; background:#4a90ff; box-shadow:0 0 0 5px rgba(25,175,140,.12); }.hero-focus strong { display:block; margin-top:11px; overflow:hidden; font-size:21px; text-overflow:ellipsis; white-space:nowrap; }.focus-divider { height:1px; margin:14px 0 10px; background:#d9e6ee; }.focus-details { display:grid; grid-template-columns:1fr 1fr; gap:14px; }.focus-details span { color:#6b829a; font-size:12px; }.focus-details b { display:block; margin-top:4px; color:#203b5b; font-size:16px; }
.task-panel,.evaluation-panel,.reflection-panel,.history-panel { padding:20px; }.section-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }.section-heading h3 { margin:7px 0 0; color:var(--ink); font-size:23px; font-weight:800; letter-spacing:-.035em; line-height:1.1; }.section-heading p { margin:7px 0 0; color:#627691; font-size:13px; line-height:1.5; }.section-heading :deep(.el-button) { font-weight:700; }.task-selection { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; max-width:830px; margin-top:18px; }.task-select { width:100%; }.task-selection :deep(.el-button) { height:34px; font-weight:700; }.task-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:15px; }.task-stats div { min-width:0; padding:12px 14px; border:1px solid #dce7f2; border-radius:11px; background:#fbfdff; }.task-stats div:nth-child(2n) { border-color:#cfe2ff; background:#f5f9ff; }.task-stats span,.task-stats strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.task-stats span { color:#71859d; font-size:12px; }.task-stats strong { margin-top:6px; color:#1d3958; font-size:17px; }
.feedback-workspace { display:grid; grid-template-columns:minmax(0,1.42fr) minmax(330px,.58fr); gap:16px; align-items:start; }.progress-pill { padding:7px 10px; border-radius:999px; background:#f1f5f9; color:#667b93; font-size:12px; font-weight:700; white-space:nowrap; }.progress-pill.ready { background:#eaf8f1; color:#168468; }.question-list { display:grid; gap:12px; margin-top:19px; }.question-card { padding:16px; border:1px solid #e0e8f1; border-radius:13px; background:#fbfdff; }.question-topline { display:flex; align-items:center; justify-content:space-between; gap:12px; }.question-index { color:#2e73cb; font-size:12px; font-weight:800; letter-spacing:.06em; }.question-card > strong { display:block; margin-top:10px; color:#1b3554; font-size:16px; line-height:1.6; }.answer-options { display:flex; flex-direction:column; gap:8px; margin-top:13px; }.answer-options :deep(.el-radio),.answer-options :deep(.el-checkbox) { height:auto; min-height:25px; margin-right:0; white-space:normal; }.question-card :deep(.el-textarea) { margin-top:13px; }
.reflection-panel { position:sticky; top:0; }.compact-heading { padding-bottom:15px; border-bottom:1px solid #e5edf5; }.reflection-fields { display:grid; gap:13px; margin-top:16px; }.reflection-fields label { display:grid; gap:7px; color:#3d5874; font-size:13px; font-weight:700; }.reflection-fields label > span { color:#526b86; }.completion-row { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:13px; border:1px solid #d9e9e3; border-radius:11px; background:#f5fcf8; }.completion-row strong,.completion-row span { display:block; }.completion-row strong { color:#1f5f50; font-size:14px; }.completion-row span { margin-top:3px; color:#668377; font-size:11px; }.field-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }.field-grid :deep(.el-input-number),.field-grid :deep(.el-select) { width:100%; }.reflection-fields small { color:#8391a4; font-size:11px; font-weight:500; }.rating-field { padding:12px; border-radius:10px; background:#f7faff; }.submit-box { display:flex; align-items:center; justify-content:space-between; gap:13px; margin-top:17px; padding:14px; border-radius:12px; background:linear-gradient(135deg,#eef6ff,#f0fbf7); }.submit-box strong,.submit-box span { display:block; }.submit-box strong { color:#1b3857; font-size:14px; }.submit-box span { max-width:210px; margin-top:4px; color:#678099; font-size:11px; line-height:1.45; }.submit-box :deep(.el-button) { flex:0 0 auto; height:36px; font-weight:700; }
.result-panel { display:grid; grid-template-columns:minmax(260px,.7fr) minmax(0,1.3fr); gap:16px; padding:20px; background:linear-gradient(112deg,#ffffff,#effaf6); }.result-summary h3 { margin:7px 0 0; font-size:23px; letter-spacing:-.035em; }.result-summary p { margin:10px 0 0; color:#567089; font-size:14px; line-height:1.55; }.weak-points { display:flex; flex-wrap:wrap; gap:7px; margin-top:13px; }.weak-points span,.weak-points b { padding:6px 8px; border-radius:999px; font-size:11px; }.weak-points span { background:#e8f6ef; color:#247a64; }.weak-points b { background:#fff; color:#b26327; }.result-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; align-content:start; }.result-metrics div { min-width:0; padding:13px; border:1px solid #d8e9e3; border-radius:11px; background:rgba(255,255,255,.78); }.result-metrics span,.result-metrics strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.result-metrics span { color:#70859c; font-size:12px; }.result-metrics strong { margin-top:7px; color:#183856; font-size:18px; }.result-actions { grid-column:2; display:flex; justify-content:flex-end; gap:10px; }.result-actions :deep(.el-button) { font-weight:700; }
.history-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:17px; }.history-item { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:11px; min-width:0; padding:12px; border:1px solid #e0e8f1; border-radius:11px; background:#fbfdff; color:inherit; text-align:left; cursor:pointer; transition:border-color .2s ease,box-shadow .2s ease,transform .2s ease; }.history-item:hover,.history-item.selected { border-color:#91b9ee; box-shadow:0 6px 14px rgba(31,78,130,.08); transform:translateY(-1px); }.history-score { display:grid; width:45px; height:36px; place-items:center; border-radius:9px; background:#eaf2ff; color:#286bd0; font-size:13px; font-weight:800; }.history-copy { min-width:0; }.history-copy strong,.history-copy small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.history-copy strong { color:#203b59; font-size:13px; }.history-copy small { margin-top:4px; color:#74869c; font-size:11px; }.history-decision { color:#258069; font-size:12px; font-weight:700; white-space:nowrap; }.history-selection-tip { margin:13px 0 0; color:#667b93; font-size:12px; }
@media (max-width:1180px) { .feedback-workspace,.result-panel { grid-template-columns:1fr; }.reflection-panel { position:static; }.result-actions { grid-column:auto; }.result-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:820px) { .feedback-hero { grid-template-columns:1fr; }.task-stats { grid-template-columns:repeat(2,minmax(0,1fr)); }.history-list { grid-template-columns:1fr; } }
@media (max-width:560px) { .feedback-hero,.task-panel,.evaluation-panel,.reflection-panel,.history-panel,.result-panel { padding:18px; }.hero-copy h2 { font-size:30px; }.hero-actions { flex-direction:column; }.hero-actions :deep(.el-button),.task-selection :deep(.el-button) { width:100%; }.task-selection,.field-grid,.result-metrics { grid-template-columns:1fr; }.submit-box { align-items:stretch; flex-direction:column; }.submit-box :deep(.el-button) { width:100%; }.history-item { grid-template-columns:auto minmax(0,1fr); }.history-decision { grid-column:2; }.section-heading { flex-direction:column; } }

/* Keep selection context available without competing with the practice workspace. */
.feedback-page { gap: 12px; }
.feedback-hero { grid-template-columns:minmax(0,1fr); min-height:0; gap:12px; padding:18px 22px 16px; border-radius:10px; }
.feedback-hero::after { right: 12%; bottom: -98px; width: 170px; height: 132px; }
.task-panel { padding: 13px 18px; border-radius: 10px; }
.task-panel .section-heading h3 { margin: 4px 0 0; font-size: 18px; }
.task-panel .page-kicker { font-size: 10px; }
.task-selection { max-width:none; margin-top:0; }
.task-selection-inline { grid-column:1 / -1; grid-template-columns:minmax(0,1fr) minmax(0,1fr) auto; align-items:end; gap:16px; }
.task-filter-field { display:grid; gap:8px; min-width:0; }
.task-selection-label { color:#47637e; font-size:13px; font-weight:800; white-space:nowrap; }
.profile-select { width:100%; }
.task-selection :deep(.el-select__wrapper) { min-height:46px; }
.task-selection :deep(.el-button) { height:46px; }
.hero-task-stats { grid-column: 1 / -1; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 0; }
.task-stats div { padding: 8px 11px; border-radius: 8px; }
.task-stats strong { margin-top: 3px; font-size: 14px; }
.task-stats span { font-size: 11px; }
.task-empty-tip { grid-column: 1 / -1; margin: 0; color: #6e8198; font-size: 12px; }
.feedback-workspace { grid-template-columns: minmax(0, 1.55fr) minmax(360px, .65fr); gap: 12px; align-items: start; }
.evaluation-panel, .reflection-panel { padding: 16px; border-radius: 10px; }
.is-empty-evaluation { display:flex; min-height:calc(100vh - 190px); flex-direction:column; }
.is-empty-evaluation :deep(.el-empty) { flex:1; }
.has-empty-evaluation .reflection-panel { min-height:calc(100vh - 190px); }
.evaluation-panel .section-heading h3, .reflection-panel .section-heading h3 { margin-top: 5px; font-size: 20px; letter-spacing: 0; }
.evaluation-panel .section-heading p, .reflection-panel .section-heading p { display: none; }
.progress-pill { align-self: center; padding: 6px 9px; }
.question-list { gap: 10px; margin-top: 13px; }
.question-card { display: grid; grid-template-columns: 42px minmax(0, 1fr) auto; column-gap: 12px; padding: 13px 14px; border-radius: 9px; }
.question-topline { display: contents; }
.question-index { grid-column: 1; align-self: start; padding-top: 2px; text-align: center; }
.question-tools { grid-column: 3; align-self: start; }
.question-tools :deep(.el-tag) { max-width: 180px; height: auto; padding: 4px 7px; white-space: normal; text-align: center; line-height: 1.25; }
.question-card > strong { grid-column: 2; margin: 0; font-size: 16px; line-height: 1.55; }
.answer-options, .question-card :deep(.el-textarea) { grid-column: 2 / -1; }
.answer-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px 12px; margin-top: 9px; }
.answer-options :deep(.el-radio), .answer-options :deep(.el-checkbox) { min-width: 0; padding: 5px 0; }
.reflection-panel { position: sticky; top: 12px; align-self: start; }
.compact-heading { padding-bottom: 10px; }
.reflection-fields { gap: 10px; margin-top: 11px; }
.reflection-fields label { gap: 5px; font-size: 12px; }
.completion-row { padding: 10px; border-radius: 8px; }
.completion-row span { display: none; }
.field-grid { gap: 8px; }
.rating-field { padding: 9px; }
.submit-box { gap: 10px; margin-top: 12px; padding: 11px; border-radius: 9px; }
.submit-box span { display: none; }
.submit-box :deep(.el-button) { height: 34px; }
.result-panel, .history-panel { padding: 16px 18px; border-radius: 10px; }

@media (max-width: 1180px) {
  .feedback-workspace { grid-template-columns: minmax(0, 1.45fr) minmax(285px, .55fr); }
}

@media (max-width: 820px) {
  .feedback-hero { grid-template-columns: 1fr; }
  .task-selection-inline { grid-template-columns:minmax(200px,.75fr) minmax(240px,1fr) auto; gap:12px; }
  .feedback-workspace { grid-template-columns: 1fr; }
  .reflection-panel { position: static; }
  .question-card { grid-template-columns: 34px minmax(0, 1fr) auto; gap: 9px; }
}

@media (max-width: 560px) {
  .feedback-hero { min-height: 0; }
  .task-selection-inline { grid-template-columns:1fr; }
  .task-selection-inline :deep(.el-button) { width:100%; }
  .hero-task-stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .question-card { display: block; }
  .question-topline { display: flex; align-items: center; justify-content: space-between; }
  .question-index { padding-top: 0; }
  .question-tools { max-width: 78%; }
  .question-tools :deep(.el-tag) { max-width: 72%; text-align: right; }
  .question-card > strong { margin-top: 8px; }
  .answer-options { grid-template-columns: 1fr; }
}

/* Reflection is a focused form surface, with controls and actions sharing one visual language. */
.reflection-panel {
  border-color: #cddfd9;
  border-top: 3px solid #2058a7;
  background: #ffffff;
  box-shadow: 0 14px 32px rgb(25 65 74 / 9%);
}
.reflection-panel .compact-heading {
  display: flex;
  align-items: flex-end;
  min-height: 48px;
  padding-bottom: 12px;
  border-color: #d9e6f4;
}
.reflection-panel .page-kicker { color: #2058a7; letter-spacing: .12em; }
.reflection-panel .section-heading h3 { color: #18354d; }
.completion-row {
  padding: 13px 14px;
  border-color: #cfe2ff;
  border-radius: 9px;
  background: #f5f9ff;
}
.completion-row strong { color: #17447e; letter-spacing: .01em; }
.completion-row :deep(.el-switch) { --el-switch-on-color: #2058a7; --el-switch-off-color: #b8cde3; }
.reflection-fields label > span { color: #49667e; font-size: 12px; letter-spacing: .02em; }
.reflection-fields :deep(.el-input__wrapper),
.reflection-fields :deep(.el-select__wrapper),
.reflection-fields :deep(.el-textarea__inner) {
  border-color: #aebfcd;
  box-shadow: 0 0 0 1px #aebfcd inset;
  background: #fcfdfe;
}
.reflection-fields :deep(.el-textarea__inner) { border: 1px solid #aebfcd; }
.field-grid { align-items: start; }
.field-grid label > span { display: flex; align-items: baseline; justify-content: space-between; min-height: 18px; }
.field-grid label > span small { color: #71859b; font-size: 11px; font-weight: 650; }
.reflection-fields :deep(.el-input__wrapper:hover),
.reflection-fields :deep(.el-select__wrapper:hover),
.reflection-fields :deep(.el-textarea__inner:hover) { border-color: #9fc4ba; }
.reflection-fields :deep(.el-input__wrapper.is-focus),
.reflection-fields :deep(.el-select__wrapper.is-focused),
.reflection-fields :deep(.el-textarea__inner:focus) {
  border-color: #4a90ff;
  box-shadow: 0 0 0 3px rgb(57 139 125 / 12%);
}
.rating-field {
  display: flex !important;
  align-items: center;
  justify-content: space-between;
  min-height: 54px;
  padding: 10px 13px;
  border: 1px solid #dce8ef;
  border-radius: 9px;
  background: #f8fbfc;
}
.rating-field :deep(.el-rate) { height: 22px; }
.rating-field :deep(.el-rate__icon) { margin-right: 5px; }
.submit-box {
  align-items: center;
  min-height: 64px;
  margin-top: 14px;
  padding: 12px 13px;
  border: 1px solid #cfe2ff;
  border-radius: 10px;
  background: #f6f9ff;
}
.submit-box strong { color: #17447e; letter-spacing: .01em; }
.start-evaluation-button,
.submit-feedback-button {
  border-color: #2058a7 !important;
  color: #fff !important;
  background: #2058a7 !important;
  box-shadow: 0 7px 14px rgb(35 110 98 / 20%);
  font-weight: 750 !important;
}
.start-evaluation-button { min-width: 106px; }
.submit-feedback-button { min-width: 118px; }
.start-evaluation-button:hover,
.start-evaluation-button:focus-visible,
.submit-feedback-button:hover,
.submit-feedback-button:focus-visible {
  border-color: #17447e !important;
  background: #17447e !important;
  box-shadow: 0 8px 18px rgb(25 79 72 / 26%);
}
.start-evaluation-button.is-disabled,
.submit-feedback-button.is-disabled {
  border-color: #d7e3e6 !important;
  color: #8ca1ae !important;
  background: #e8f0f2 !important;
  box-shadow: none;
}

/* The result is read as a short report, then a deliberate next-step choice. */
.result-panel { display:grid; grid-template-columns:1fr; gap:16px; padding:24px 28px; }
.result-header { display:grid; grid-template-columns:minmax(300px,.72fr) minmax(500px,1.28fr); gap:24px; align-items:start; }
.result-summary { min-width:0; }
.result-summary h3 { margin:8px 0 0; font-size:27px; }
.result-summary > p { max-width:660px; margin-top:10px; }
.result-metrics { grid-template-columns:repeat(4,minmax(0,1fr)); }
.analysis-summary { margin:0; max-width:none; padding:18px 20px; border-color:#c9e6dc; }
.capability-result-panel { padding:16px 20px; border:1px solid #d8e6f2; border-radius:12px; background:#fbfdff; }
.capability-result-list { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; margin-top:12px; }
.capability-result-list div { display:grid; gap:4px; min-width:0; padding:10px 12px; border:1px solid #e1eaf2; border-radius:9px; background:#fff; }
.capability-result-list strong,.capability-result-list span { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.capability-result-list strong { color:#274864; font-size:13px; }.capability-result-list span { color:#6a8196; font-size:12px; }
.analysis-heading { display:flex; align-items:baseline; gap:10px; }
.analysis-heading strong { font-size:18px; }
.analysis-heading span { color:#6d8495; font-size:12px; }
.analysis-summary p { max-width:980px; }
.reflection-insight { padding:10px 12px; border-left:3px solid #56a995; background:#f1faf6; }
.next-step-panel { display:grid; grid-template-columns:minmax(260px,.55fr) minmax(0,1.45fr); gap:24px; padding:18px 20px; border:1px solid #d4e8e2; border-radius:12px; background:#f6fcfa; }
.next-step-copy h4 { margin:7px 0 0; color:#183b55; font-size:19px; }
.next-step-copy p { margin:8px 0 0; color:#607991; font-size:13px; line-height:1.55; }
.next-step-actions { display:flex; flex-wrap:wrap; align-content:center; gap:10px; }
.resource-selection-row,.recommendation-row { display:flex; flex-wrap:wrap; align-items:center; gap:9px; width:100%; color:#49687d; font-size:13px; font-weight:700; }
.intent-selection-row,.intent-node-row { display:flex; flex-wrap:wrap; align-items:center; gap:9px; width:100%; padding:11px 12px; border:1px solid #cfe2ff; border-radius:10px; background:#f7fbff; color:#355571; font-size:13px; font-weight:700; }
.curriculum-progress-row { display:flex; flex-wrap:wrap; gap:8px 14px; width:100%; padding:10px 12px; border:1px solid #d9e7f8; border-radius:10px; background:#f5f9fe; color:#45647f; font-size:13px; }
.correction-package-card { display:grid; grid-template-columns:minmax(180px,1fr) minmax(260px,1.4fr) auto; align-items:center; gap:12px; width:100%; padding:14px; border:1px solid #9bd8c7; border-radius:11px; background:linear-gradient(120deg,#effcf7,#f7fffc); color:#285b51; }.correction-package-card strong { color:#176958; font-size:15px; }.correction-package-card p { margin:5px 0 0; color:#5b7e77; font-size:12px; line-height:1.45; }.correction-package-card small { grid-column:2; color:#62837c; font-size:11px; }.correction-package-card.is-disabled { border-color:#d8e2e7; background:#fafcfd; color:#6c7d88; }.correction-package-card.is-disabled strong { color:#5e6d78; }.correction-package-card.is-disabled .el-button { opacity:.65; }
.curriculum-progress-row strong { color:#234f7d; }
.intent-selection-row small,.intent-node-row small,.intent-node-row em { color:#6d8297; font-size:11px; font-style:normal; font-weight:500; }
.intent-selection-row small { width:100%; }
.resource-type-choice { display:flex; flex-wrap:wrap; gap:5px 13px; }
.difficulty-choice { width:120px; }
.custom-generation-button { margin-left:auto; font-weight:750; }
.result-actions { display:flex; grid-column:auto; justify-content:flex-end; gap:10px; }

@media (max-width: 900px) {
  .result-header,.next-step-panel { grid-template-columns:1fr; }
  .result-metrics,.capability-result-list { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .correction-package-card { grid-template-columns:1fr; }.correction-package-card small { grid-column:auto; }
}
</style>
