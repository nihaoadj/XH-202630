<template>
  <div class="feedback-page" :class="{ 'has-feedback-result': (!activeRoundId && result) || roundHasResult }">
    <section class="feedback-hero workspace-filter-surface">
      <div class="task-selection task-selection-inline">
        <label class="task-filter-field">
          <span class="task-selection-label">学习画像<small aria-hidden="true">PROFILE</small></span>
          <el-select v-model="selectedLearnerId" filterable aria-label="学习画像" placeholder="选择学习画像" class="profile-select workspace-glass-select" popper-class="refined-select-dropdown" @change="handleProfileChange">
            <el-option v-for="profile in profileOptions" :key="profile.learner_id" :label="profile.label" :value="profile.learner_id" />
          </el-select>
        </label>
        <label class="task-filter-field">
          <span class="task-selection-label">本轮资源批次<small aria-hidden="true">BATCH</small></span>
          <el-select v-model="selectedRunId" filterable aria-label="本轮资源批次" placeholder="选择要反馈的学习资源批次" class="task-select workspace-glass-select" popper-class="refined-select-dropdown" @change="selectBatch(true)">
            <template #label="{ label }">
              <span class="batch-selected-label" :title="label">
                <span class="batch-label-text"><strong v-if="activeTask?.nodeTitle" class="batch-node-name">{{ activeTask.nodeTitle }}</strong>{{ activeTask?.nodeTitle ? ' ｜ ' : '' }}{{ activeTask?.batchMeta || label }}</span>
                <span v-if="activeTask" class="batch-status">{{ activeTask.status }}</span>
              </span>
            </template>
            <el-option v-for="task in taskGroups" :key="task.runId" :label="task.label" :value="task.runId">
              <span class="batch-option-label">
                <span><strong v-if="task.nodeTitle" class="batch-node-name">{{ task.nodeTitle }}</strong>{{ task.nodeTitle ? ' ｜ ' : '' }}{{ task.batchMeta }}</span>
                <span class="batch-status">{{ task.status }}</span>
              </span>
            </el-option>
          </el-select>
        </label>
        <el-button v-if="activeRoundId && (!roundHasResult || roundCanRetake)" class="start-evaluation-button" type="primary" :icon="VideoPlay" :disabled="roundBusy" @click="roundHasResult ? roundWorkspaceRef?.startRetake() : roundWorkspaceRef?.startEvaluation()">
          {{ roundHasResult ? '再次测评' : '开始测评' }}
        </el-button>
        <el-button v-if="!activeRoundId" class="start-evaluation-button" type="primary" :icon="VideoPlay" @click="startEvaluation" :disabled="!selectedRunId">{{ selectedBatchHasFeedback ? '再次测评' : '开始测评' }}</el-button>
      </div>

      <p v-if="!activeTask" class="task-empty-tip">暂时没有可用于反馈的资源任务，请先完成一轮学习资源生成。</p>
    </section>

    <RoundFeedbackWorkspace ref="roundWorkspaceRef" v-if="activeRoundId" :key="`${form.learner_id}:${activeRoundId}:${activeRoundStageId}`" :round-id="activeRoundId" :learner-id="form.learner_id" :initial-stage-id="activeRoundStageId" :reflection="roundReflection" @result-state="roundResult = $event" />

    <section v-if="!activeRoundId && !result" ref="workspaceRef" class="feedback-workspace" :class="{ 'has-empty-evaluation': !evaluation.questions.length }" v-module-motion="evaluation.questions.length ? selectedRunId : 'preparation'">
      <article class="evaluation-panel" :class="{ 'is-empty-evaluation': !evaluation.questions.length }">
        <div class="section-heading">
          <div>
            <span class="page-kicker">01 / PRACTICE CHECK</span>
            <h2>完成知识测评</h2>
            <p>题目会优先覆盖本轮资源涉及的知识点。</p>
          </div>
          <span v-if="evaluation.questions.length" class="progress-pill assessment-progress" :class="{ ready: allQuestionsAnswered }">
            <span class="progress-count"><strong>{{ answeredCount }}</strong><span class="progress-total">/ {{ evaluation.questions.length }}</span></span>
            <span class="progress-caption">已作答</span>
          </span>
          <span v-else class="progress-pill preparation-status">测评待开始</span>
        </div>

        <PreparationPanel
          v-if="!evaluation.questions.length"
          class="evaluation-preparation"
          compact
          eyebrow="KNOW WHAT YOU KNOW"
          :title="activeTask ? '用一次测评，看清你的掌握程度。' : '从一轮学习，开始你的能力复盘。'"
          :description="activeTask ? '本轮材料已就绪。点击上方开始测评，题目将围绕这些资源展开。' : '先生成并学习一批资源，再选择对应批次，检验理解与实际应用。'"
          :steps="[
            { title: '回忆与判断', description: '回顾本轮知识，检验概念理解与关键判断。' },
            { title: '应用与表达', description: '结合实际情境独立作答，检验真实掌握程度。' },
            { title: '结果与下一步', description: '了解掌握情况，选择继续探索或巩固薄弱点。' },
          ]"
        >
          <template #footer><el-icon aria-hidden="true"><CircleCheck /></el-icon><span>用作答结果，了解真实掌握情况。</span></template>
        </PreparationPanel>

        <FeedbackQuestions v-else :questions="evaluation.questions" :answers="evaluationAnswers" :locked="submitting" :question-type-label="questionTypeLabel" @answer="evaluationAnswers[$event.id] = $event.value" />
      </article>

      <FeedbackReflection :model-value="form" :active="Boolean(evaluation.questions.length)" :locked="submitting" @update:model-value="Object.assign(form, $event)">
        <div v-if="evaluation.questions.length" class="submit-box">
          <div class="submit-summary">
            <strong>{{ allQuestionsAnswered ? '可以提交本轮反馈' : '请先完成全部测评题' }}</strong>
            <span v-if="allQuestionsAnswered">提交后查看学习建议。</span>
          </div>
          <el-button class="submit-feedback-button" type="primary" :icon="CircleCheck" :loading="submitting" :disabled="!canSubmit || submitting" @click="submitEvaluation">提交反馈</el-button>
          <p v-if="feedbackStatus" class="feedback-generation-status" role="status">{{ feedbackStatus }}</p>
        </div>
      </FeedbackReflection>
    </section>

    <section v-if="!activeRoundId && result" id="feedback-report" ref="resultPanelRef" class="result-panel" v-module-motion="{ key: selectedRunId, appear: true }">
      <FeedbackReviewPanels :result="result" :feedback-report="feedbackReport" :weak-knowledge-points="weakKnowledgePoints" :friendly-text="friendlyText" :question-type-label="questionTypeLabel" />
      <section class="next-step-panel" :class="{ 'has-route-picker': !result.followup_run_id }" aria-labelledby="feedback-next-step">
        <header class="next-step-copy">
          <div class="next-step-heading">
            <el-icon class="review-section-symbol" aria-hidden="true"><Compass /></el-icon>
            <div>
              <h2 id="feedback-next-step">{{ result.followup_run_id ? '下一步学习' : '选择下一步学习方案' }}</h2>
              <p v-if="!result.followup_run_id" class="choice-guidance">按你的学习目标选择。</p>
            </div>
          </div>
          <div class="next-step-verdict">
            <span v-if="!result.followup_run_id" class="verdict-recommendation">{{ routeRecommendationLabel }}</span>
            <span class="result-action-label" :class="{ 'is-warning': result.decision.action === 'practice' }">{{ feedbackActionLabel(result.decision.action) }}</span>
            <p>{{ friendlyText(result.decision.decision_reason) }}</p>
          </div>
          <el-radio-group v-if="!result.followup_run_id && correctionPackageOption?.eligible" v-model="selectedNextRoute" class="route-switch" aria-label="下一步学习路线" :disabled="nextRoundBusy || Boolean(selectingOption)">
            <el-radio-button label="learning">下一轮学习</el-radio-button>
            <el-radio-button label="correction">纠错巩固</el-radio-button>
          </el-radio-group>
        </header>
        <div class="plan-options">
          <section v-if="!result.followup_run_id && correctionPackageOption?.eligible" v-show="selectedNextRoute === 'correction'" class="correction-package-card followup-choice correction-choice" :class="{ 'is-recommended': correctionRecommended }">
            <header class="plan-card-heading">
              <span class="plan-card-icon"><el-icon aria-hidden="true"><Aim /></el-icon></span>
              <div class="plan-card-summary">
                <div class="plan-card-title">
                  <h4>纠错包巩固 + 新测评</h4>
                  <span v-if="correctionRecommended" class="recommendation-badge">系统推荐</span>
                </div>
                <p>{{ correctionRecommended && nextStepRecommendation.description ? nextStepRecommendation.description : '围绕本次测评的薄弱点，完成一轮针对性练习。' }}</p>
              </div>
            </header>
            <div class="plan-card-actions">
              <div class="fixed-correction-targets">
                <span v-for="node in correctionPackageOption.selectable_targets" :key="node.skill_node_id" class="correction-target">{{ node.name || node.skill_node_id }}</span>
                <span v-if="correctionPackageOption.recommended_difficulty">{{ correctionPackageOption.recommended_difficulty }}难度</span>
              </div>
              <el-button type="primary" :loading="selectingOption === correctionPackageOption.option_id" :disabled="nextRoundBusy || !correctionPackageOption.eligible || Boolean(selectingOption && selectingOption !== correctionPackageOption.option_id)" @click="selectCorrectionPackage">生成纠错包与新测评<el-icon class="el-icon--right" aria-hidden="true"><ArrowRight /></el-icon></el-button>
            </div>
          </section>
          <section v-else-if="result.followup_run_id" class="selected-followup-card">
            <div class="selected-followup-main">
              <span class="selected-followup-status"><CircleCheck aria-hidden="true" />已确认下一步</span>
              <h4>{{ followupSelectionLabel }}</h4>
              <p>已为你选择的学习方案创建资源任务<span v-if="result.followup_run_ids?.length > 1">，共 {{ result.followup_run_ids.length }} 个</span>。</p>
              <div v-if="followupSelection.node_names?.length" class="selected-followup-goals">
                <span class="selected-goals-label">学习目标</span>
                <div class="selected-followup-targets"><span v-for="nodeName in followupSelection.node_names" :key="nodeName" class="selected-target-chip">{{ nodeName }}</span></div>
              </div>
            </div>
            <div class="selected-followup-action">
              <strong>继续你的学习</strong>
              <p>前往任务页查看资源与生成进度。</p>
              <el-button class="selected-resource-button" type="primary" @click="goToFollowupRun">查看已选资源<el-icon class="el-icon--right" aria-hidden="true"><ArrowRight /></el-icon></el-button>
            </div>
          </section>
          <section v-if="!result.followup_run_id" v-show="selectedNextRoute === 'learning'" class="tier-learning-choice followup-choice" :class="{ 'is-recommended': learningRecommended }">
            <NextRoundChoice
              compact
              :key="`${form.learner_id}:${result.attempt.attempt_id}`"
              :learner-id="form.learner_id"
              :source-attempt-id="result.attempt.attempt_id"
              :recommended-intent="recommendedIntent"
              :assessment-action="result.decision?.action"
              :blocked="Boolean(selectingOption)"
              :claim-options="claimOptions"
              @busy="nextRoundBusy = $event"
            >
              <template #heading>
                <header class="plan-card-heading">
                  <span class="plan-card-icon"><el-icon aria-hidden="true"><SetUp /></el-icon></span>
                  <div class="plan-card-summary">
                    <div class="plan-card-title">
                      <h4>下一轮学习</h4>
                      <span v-if="learningRecommended" class="recommendation-badge">系统推荐</span>
                    </div>
                  </div>
                </header>
              </template>
              <div class="next-round-claim">
                <el-checkbox v-model="includeClaimCheck" :disabled="nextRoundBusy || Boolean(selectingOption)">启用 Claim 审核</el-checkbox>
                <el-checkbox v-model="includeClaimEvidenceRetrieval" :disabled="nextRoundBusy || Boolean(selectingOption) || !includeClaimCheck">证据不足时补检知识库</el-checkbox>
              </div>
            </NextRoundChoice>
          </section>
        </div>
      </section>
    </section>

  </div>
</template>

<script setup>
import { currentProfileRating } from '../../utils/profileRating.js'
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Aim, ArrowRight, ChatDotRound, CircleCheck, Compass, SetUp, VideoPlay } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { feedbackApi } from './api.js'
import NextRoundChoice from './NextRoundChoice.vue'
import { generateApi } from '../generation/api.js'
import { knowledgeApi } from '../knowledge/api.js'
import { profileApi } from '../learners/api.js'
import { resourceApi } from '../learning-documents/api.js'
import { useAppStore } from '../../stores/app'
import PreparationPanel from '../../components/PreparationPanel.vue'
import { useFeedbackEvaluation } from './useFeedbackEvaluation.js'
import RoundFeedbackWorkspace from './RoundFeedbackWorkspace.vue'
import FeedbackQuestions from './FeedbackQuestions.vue'
import FeedbackReflection from './FeedbackReflection.vue'
import FeedbackReviewPanels from './FeedbackReviewPanels.vue'
import { useFeedbackFollowup } from './useFeedbackFollowup.js'
import { createRequestGuard } from '../../utils/requestContext.js'
import { buildFeedbackBatchPresentation } from './batchPresentation.js'
import { resolveResourceFeedbackBinding } from '../../utils/resourceStudyContext.js'

const router = useRouter()
const route = useRoute()
const store = useAppStore()
const workspaceRef = ref(null)
const resultPanelRef = ref(null)
const selectedLearnerId = ref(route.query.learnerId || store.currentLearnerId || localStorage.getItem('last_learner_id') || '')
const form = reactive({
  learner_id: selectedLearnerId.value,
  completed: true,
  time_spent_seconds: 1800,
  self_rating: 4,
  difficulty_feeling: '',
  confusing_part: '',
  comment: ''
})
const resources = ref([])
const generationJobs = ref([])
const feedbackResults = ref([])
const profiles = ref([])
const tracks = ref([])
const nodeNames = ref(new Map())
const selectedRunId = ref(route.query.batchId || route.query.runId || localStorage.getItem('current_generation_run_id') || '')
const roundWorkspaceRef = ref(null)
const roundCanRetake = computed(() => Boolean(roundWorkspaceRef.value?.canRetake))
const roundBusy = computed(() => Boolean(roundWorkspaceRef.value?.roundBusy))
const roundResult = ref(null)
const routeRoundId = ref(String(route.query.roundId || ''))
const feedbackSourceRunId = ref(String(route.query.runId || ''))
const activeRoundBinding = computed(() => resolveResourceFeedbackBinding(generationJobs.value, selectedRunId.value, feedbackSourceRunId.value))
const activeRoundId = computed(() => routeRoundId.value || activeRoundBinding.value?.round_id || '')
const activeRoundStageId = computed(() => String(routeRoundId.value ? route.query.stageId || '' : activeRoundBinding.value?.stage_id || ''))
const roundHasResult = computed(() => roundResult.value?.round_id === activeRoundId.value)
const roundReflection = computed(() => ({ completed: form.completed, time_spent_seconds: form.time_spent_seconds,
  self_rating: form.self_rating, difficulty_feeling: form.difficulty_feeling,
  confusing_part: form.confusing_part, comment: form.comment }))

const submitting = ref(false)
const feedbackStatus = ref('')
const selectingOption = ref('')
const result = ref(null)
const feedbackContextVersion = ref(0)
const nextRoundBusy = ref(false)
const includeClaimCheck = ref(false)
const includeClaimEvidenceRetrieval = ref(false)
const claimPostRetrievalMaxIterations = ref(0)
const evaluation = reactive({ topic: '', questions: [], resourceIds: [] })
const evaluationAnswers = reactive({})
const tutorHelpCount = ref(0)
const resourceRequests = createRequestGuard(() => ({
  learnerId: selectedLearnerId.value,
  formLearnerId: form.learner_id,
  contextVersion: feedbackContextVersion.value,
}))
const profileRequests = createRequestGuard(() => ({ contextVersion: feedbackContextVersion.value }))

const profileOptions = computed(() => profiles.value.map((profile) => ({
  ...profile,
  label: `${resolveTrackName(profile.knowledge_base_id)} / ${formatSkillLevel(currentProfileRating(profile))}`,
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
  const jobsByRunId = new Map(generationJobs.value.map(job => [job.run_id, job]))
  const completedStages = new Set(feedbackResults.value.map(item => item.attempt?.metadata?.round_context?.stage_id).filter(Boolean))
  if (roundHasResult.value) completedStages.add(roundResult.value.stage_id)
  const effectiveBatchByRunId = new Map()
  for (const job of generationJobs.value) {
    const correctionSourceRunId = job.request_payload?.constraints?.correction_focus_snapshot?.source_run_id
    if (!correctionSourceRunId) continue
    const sourceJob = generationJobs.value.find((candidate) => candidate.run_id === correctionSourceRunId)
    effectiveBatchByRunId.set(job.run_id, sourceJob?.batch_id || sourceJob?.run_id || correctionSourceRunId)
  }
  const groups = new Map()
  for (const resource of visibleResources.value) {
    const batchId = effectiveBatchByRunId.get(resource.run_id) || resource.batch_id || resource.run_id || `resource:${resource.resource_id}`
    if (!groups.has(batchId)) groups.set(batchId, {
      runId: batchId,
      batchId,
      shortRunId: batchId.startsWith('resource:') ? '独立资源' : batchId.slice(0, 8).toUpperCase(),
      finishedAt: resource.created_at || '',
      resources: []
    })
    const task = groups.get(batchId)
    task.resources.push(resource)
    if (resource.created_at && (!task.finishedAt || resource.created_at > task.finishedAt)) task.finishedAt = resource.created_at
  }
  return Array.from(groups.values())
    .sort((left, right) => String(left.finishedAt).localeCompare(String(right.finishedAt)))
    .map((task, taskIndex) => {
      const batchLabel = `资源批次 ${String(taskIndex + 1).padStart(2, '0')}`
      const correctionRuns = generationJobs.value
        .filter((job) => (
          (job.batch_id || job.run_id) === task.batchId
          && job.request_payload?.constraints?.selection_type === 'correction_package'
        ))
        .sort((left, right) => String(right.created_at || '').localeCompare(String(left.created_at || '')))
      const isCompletedStage = runId => completedStages.has(jobsByRunId.get(runId)?.round_binding?.stage_id)
      const pendingCorrectionRun = correctionRuns.find(job => !completedRunIds.value.has(job.run_id) && !isCompletedStage(job.run_id))
      const completed = task.resources.some((resource) => (
        completedRunIds.value.has(resource.run_id) || completedRunIds.value.has(resource.batch_id) || isCompletedStage(resource.run_id)
      )) && !pendingCorrectionRun
      return {
        ...task,
        completed,
        pendingCorrectionRunId: pendingCorrectionRun?.run_id || '',
        batchLabel,
        ...buildFeedbackBatchPresentation({
          resources: task.resources, jobsByRunId, nodeNames: nodeNames.value, batchLabel,
          finishedAt: task.finishedAt,
          status: pendingCorrectionRun ? '待纠错测评' : completed ? '已反馈' : '待反馈',
        }),
      }
    }).reverse()
})
const activeTask = computed(() => taskGroups.value.find((item) => item.runId === selectedRunId.value) || taskGroups.value[0] || null)
const selectedBatchHasFeedback = computed(() => Boolean(taskGroups.value.find((item) => item.runId === selectedRunId.value)?.completed))
const pendingCorrectionRunId = computed(() => activeTask.value?.pendingCorrectionRunId || '')
const answeredCount = computed(() => evaluation.questions.reduce((count, question) => count + (hasAnswer(evaluationAnswers[question.question_id]) ? 1 : 0), 0))
const allQuestionsAnswered = computed(() => Boolean(evaluation.questions.length && answeredCount.value === evaluation.questions.length))
const canSubmit = computed(() => Boolean(selectedRunId.value && allQuestionsAnswered.value))
const weakKnowledgePoints = computed(() => {
  const questionNames = new Map((feedbackReport.value.question_results || [])
    .filter((item) => item.knowledge_point)
    .map((item) => [item.skill_node_id, item.knowledge_point]))
  const candidateNames = new Map((correctionPackageOption.value?.selectable_targets || [])
    .filter((item) => item.name)
    .map((item) => [item.skill_node_id, item.name]))
  return (result.value?.knowledge_state_updates || [])
    .filter((item) => item.after?.status === 'weak')
    .map(({ knowledge_point_id: id }) => ({ id, label: candidateNames.get(id) || questionNames.get(id) || id }))
})
const studyTimeLabel = computed(() => `${Math.floor((form.time_spent_seconds || 0) / 60)} 分钟`)
const generationOptions = computed(() => result.value?.generation_options || null)
const correctionPackageOption = computed(() => result.value?.correction_package_option || null)
const feedbackReport = computed(() => result.value?.feedback_report || {})
const nextStepRecommendation = computed(() => feedbackReport.value?.next_step_recommendation || {})
const correctionRecommended = computed(() => correctionPackageOption.value?.eligible
  && nextStepRecommendation.value.recommended_action === 'correction_package')
const selectedNextRoute = ref('learning')
watch([() => result.value?.attempt?.attempt_id, correctionRecommended], () => {
  selectedNextRoute.value = correctionRecommended.value ? 'correction' : 'learning'
}, { immediate: true })
const recommendedIntent = computed(() => [
  nextStepRecommendation.value.learning_intent,
  nextStepRecommendation.value.alternative_learning_intent,
].find(intent => ['learn_new_knowledge', 'downgrade_learning', 'upgrade_learning', 'reinforce_weakness'].includes(intent)) || '')
const learningRecommended = computed(() => Boolean(recommendedIntent.value)
  && nextStepRecommendation.value.recommended_action !== 'correction_package')
const routeRecommendationLabel = computed(() => {
  if (correctionRecommended.value) return '系统推荐 · 纠错巩固'
  if (learningRecommended.value || result.value?.decision?.action === 'advance') return '系统推荐 · 下一轮学习'
  return '系统建议'
})
const claimOptions = computed(() => ({
  include_claim_check: includeClaimCheck.value,
  include_claim_evidence_retrieval: includeClaimCheck.value && includeClaimEvidenceRetrieval.value,
  claim_post_retrieval_max_iterations: includeClaimCheck.value && includeClaimEvidenceRetrieval.value ? claimPostRetrievalMaxIterations.value : 0,
}))
const followupSelection = computed(() => feedbackReport.value?.followup_selection || {})
const followupSelectionLabel = computed(() => ({
  correction_package: '纠错包巩固',
  lower_tier_selection: '降阶学习（低阶前置）',
  same_tier_prerequisite: '降阶学习（同阶前置）',
  cross_tier_prerequisite_review: '前置复习与进阶学习',
  same_tier: '当前阶学习',
}[followupSelection.value?.selection_type] || '已选学习方案'))
watch(() => store.currentLearnerId, (value) => {
  if (value && value !== selectedLearnerId.value) {
    feedbackContextVersion.value += 1
    selectingOption.value = ''
    selectedLearnerId.value = value
    form.learner_id = value
  }
}, { flush: 'sync' })
function hasAnswer(value) { return Array.isArray(value) ? value.length > 0 : String(value || '').trim().length > 0 }
function resolveTrackName(trackId) {
  return tracks.value.find((track) => track.track_id === trackId || track.knowledge_base_id === trackId)?.name || trackId || '未选择学习方向'
}
function formatSkillLevel(level) { return ({ beginner: '初级', intermediate: '中级', advanced: '高级' })[level] || level || '未分级' }
function questionTypeLabel(type) {
  return ({
    single_choice: '单选题',
    multiple_choice: '多选题',
    short_answer: '问答题',
  })[type] || '问答题'
}

function feedbackActionLabel(action) {
  return { remediate: '补救学习', practice: '强化练习', advance: '继续进阶', hold: '保持路径', human_review: '人工复核' }[action] || action || '已记录'
}
function friendlyText(value) {
  return String(value || '')
    .replaceAll('学习者', '你')
    .replaceAll('系统建议', '建议')
    .replaceAll('系统', '本次结果')
    .replaceAll('画像', '学习情况')
    .replaceAll('客观成绩', '测评结果')
}

function feedbackScrollBehavior() { return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }
function scrollToWorkspace() { workspaceRef.value?.scrollIntoView({ behavior: feedbackScrollBehavior(), block: 'start' }) }
async function startEvaluation() {
  const learnerId = form.learner_id
  const batchId = selectedRunId.value
  const contextVersion = feedbackContextVersion.value
  selectingOption.value = ''
  await loadEvaluationSession({ forceNew: true })
  await nextTick()
  if (learnerId === form.learner_id && batchId === selectedRunId.value && contextVersion === feedbackContextVersion.value) {
    scrollToWorkspace()
  }
}
function selectBatch(fromUser = false) {
  if (fromUser) { routeRoundId.value = ''; feedbackSourceRunId.value = '' }
  feedbackContextVersion.value += 1
  selectingOption.value = ''
  const existing = feedbackResults.value.find((item) => (
    item.attempt?.source_run_id === selectedRunId.value
    || item.attempt?.metadata?.session_id === selectedRunId.value
  ))
  result.value = existing || null
  feedbackStatus.value = ''
  if (!existing) {
    evaluation.questions = []
    evaluation.resourceIds = []
    resetEvaluationAnswers()
  }
}
async function loadProfiles() {
  const request = profileRequests.capture()
  try {
    const [profileResponse, domainResponse] = await Promise.all([
      profileApi.list({ page: 1, page_size: 50 }),
      knowledgeApi.listDomains(),
    ])
    if (!request.isCurrent()) return
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
    if (!request.isCurrent()) return
    console.error(error)
    ElMessage.warning('学习画像加载失败')
  }
}
async function handleProfileChange() {
  routeRoundId.value = ''
  feedbackSourceRunId.value = ''
  feedbackContextVersion.value += 1
  resourceRequests.invalidate()
  nodeNames.value = new Map()
  form.learner_id = selectedLearnerId.value
  localStorage.setItem('last_learner_id', selectedLearnerId.value)
  result.value = null
  feedbackStatus.value = ''
  selectingOption.value = ''
  selectedRunId.value = ''
  evaluation.questions = []
  evaluation.resourceIds = []
  resetEvaluationAnswers()
  tutorHelpCount.value = 0
  await loadResources()
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
  const learnerId = form.learner_id
  const request = resourceRequests.capture()
  if (!request.isCurrent()) return
  if (!learnerId) return
  const knowledgeBaseId = profiles.value.find(profile => profile.learner_id === learnerId)?.knowledge_base_id
  try {
    const [res, jobsRes, resultsRes, nodesRes] = await Promise.all([
      resourceApi.listByLearner(learnerId),
      generateApi.listJobs(learnerId),
      feedbackApi.listResults(learnerId, { limit: 50 }),
      knowledgeBaseId ? knowledgeApi.listNodes(knowledgeBaseId).catch(() => null) : Promise.resolve(null),
    ])
    if (!request.isCurrent()) return
    resources.value = res.data.resources || []
    generationJobs.value = jobsRes.data.items || []
    feedbackResults.value = resultsRes.data || []
    const nodes = nodesRes?.data?.nodes || nodesRes?.data || []
    nodeNames.value = new Map(nodes.map(node => [node.node_id, node.name || node.node_id]))
    syncSelectedRun()
    selectBatch()
  }
  catch (error) {
    if (!request.isCurrent()) return
    console.error(error)
    ElMessage.warning('资源加载失败，请先完成资源生成。')
  }
}
const {
  resetEvaluationAnswers,
  loadEvaluationSession, submitEvaluation, dispose: disposeEvaluation,
} = useFeedbackEvaluation({
  feedbackApi,
  form, selectedRunId, pendingCorrectionRunId, feedbackResults, result, evaluation,
  evaluationAnswers, tutorHelpCount, canSubmit, submitting,
  feedbackStatus, activeTask, store, resultPanelRef, feedbackScrollBehavior, messages: ElMessage,
  contextVersion: feedbackContextVersion,
})


const {
  selectCorrectionPackage, goToFollowupRun, dispose: disposeFollowup,
} = useFeedbackFollowup({
  feedbackApi,
  form, result, selectingOption, includeClaimCheck, includeClaimEvidenceRetrieval, claimPostRetrievalMaxIterations, generationOptions, correctionPackageOption,
  router, messages: ElMessage, contextVersion: feedbackContextVersion,
})

onMounted(async () => { await loadProfiles(); await loadResources() })
onBeforeUnmount(() => {
  resourceRequests.dispose()
  profileRequests.dispose()
  disposeEvaluation()
  disposeFollowup()
})
</script>

<style src="./feedbackWorkspace.css"></style>
