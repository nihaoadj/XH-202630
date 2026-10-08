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

      <p v-if="!activeTask" class="task-empty-tip">暂时没有可用于反馈的资源任务，请先完成一轮学习资源生成。</p>
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
                <el-tag class="question-type-tag" size="small" effect="plain">{{ questionTypeLabel(question.question_type) }}</el-tag>
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
          <el-button class="submit-feedback-button" type="primary" :icon="CircleCheck" :disabled="!canSubmit || submitting" @click="submitEvaluation">提交反馈</el-button>
          <p v-if="feedbackStatus" class="feedback-generation-status" role="status">{{ feedbackStatus }}</p>
        </div>
      </aside>
    </section>

    <section v-if="result" id="feedback-report" ref="resultPanelRef" class="result-panel">
      <header class="result-header">
        <div class="result-summary">
        <span class="page-kicker">LEARNING RESULT</span>
        <h3>这次学习的回顾</h3>
        <p>{{ friendlyText(result.decision.decision_reason) }}</p>
        <div v-if="weakKnowledgePoints.length" class="weak-points"><span>优先巩固</span><b v-for="item in weakKnowledgePoints" :key="item">{{ item }}</b></div>
        </div>
        <div class="result-metrics">
        <div><span>测评得分</span><strong>{{ Number(feedbackReport.total_score || 0).toFixed(1) }} / {{ Number(feedbackReport.max_score || 100).toFixed(1) }}</strong></div>
        <div><span>测评正确率</span><strong>{{ Math.round((feedbackReport.score_rate || 0) * 100) }}%</strong></div>
        <div><span>当前建议</span><strong>{{ feedbackActionLabel(result.decision.action) }}</strong></div>
        <div><span>下一步资源</span><strong>{{ nextStepResourceLabel }}</strong></div>
        </div>
      </header>
      <article v-if="result.analysis" class="analysis-summary">
        <div class="analysis-heading"><strong>学习小结</strong><span>根据你的作答和学习感受整理</span></div>
        <p>{{ friendlyText(result.analysis.summary) }}</p>
        <p v-if="result.analysis.reflection_insight" class="reflection-insight">{{ friendlyText(result.analysis.reflection_insight) }}</p>
        <ul v-if="result.analysis.learner_suggestions?.length"><li v-for="item in result.analysis.learner_suggestions" :key="item">{{ friendlyText(item) }}</li></ul>
      </article>
      <article v-if="feedbackReport.question_results?.length" class="capability-result-panel">
        <div class="analysis-heading"><strong>逐题结果</strong><span>单选题按匹配判分，多选题按正确选项得分并按错选扣分，问答题按参考答案评分</span></div>
        <div class="capability-result-list">
          <div v-for="item in feedbackReport.question_results" :key="item.question_id">
            <strong>{{ item.question_id }} · {{ item.correct ? '正确' : '待加强' }}</strong><span>{{ Number(item.score || 0).toFixed(1) }} / {{ Number(item.max_score || 0).toFixed(1) }} 分 · {{ item.knowledge_point || item.skill_node_id }}</span>
          </div>
        </div>
      </article>
      <section class="next-step-panel">
        <div class="next-step-copy">
          <el-alert v-if="feedbackReport.tier_unlock" type="success" :closable="false" show-icon :title="`已解锁第 ${feedbackReport.tier_unlock.to_tier} 阶学习，下一步可进行升阶学习`" />
          <div class="next-step-title"><span class="page-kicker">DEFAULT LEARNING PATH</span><h4>{{ nextStepRecommendation.title || '默认学习建议' }}</h4></div>
          <div class="next-step-reason"><b>推荐原因</b><p>{{ nextStepRecommendation.description || '可先学习推荐节点，也可以自主选择纠错包巩固。' }}</p></div>
          <small v-if="tierProgress">当前学习阶：{{ tierProgress.active_tier }} · 已解锁至第 {{ tierProgress.highest_unlocked_tier }} 阶<span v-if="tierProgress.remediation_return_tier"> · 补救后返回第 {{ tierProgress.remediation_return_tier }} 阶</span></small>
        </div>
        <div class="next-step-actions">
          <template v-if="!result.followup_run_id">
            <section v-if="correctionPackageOption" class="correction-package-card followup-choice correction-choice" :class="{ 'is-disabled': !correctionPackageOption.eligible }">
              <div><span class="choice-kicker">方案 {{ generationOptions ? '一' : '' }}</span><strong>纠错包巩固 + 新测评</strong><p>围绕本次测评覆盖的待巩固节点生成纠错包，并追加一份题干不同的新分阶段测评题，用于学习完成后的再次验证。</p></div>
              <div v-if="correctionPackageOption.eligible" class="fixed-correction-targets">
                <el-tag v-for="node in correctionPackageOption.selectable_targets" :key="node.skill_node_id" type="warning" effect="plain">{{ node.name || node.skill_node_id }}</el-tag>
              </div>
              <small v-if="correctionPackageOption.eligible">系统锁定难度：{{ correctionPackageOption.recommended_difficulty }}；目标已由本次反馈固定。</small>
              <small v-else>当前没有可用于纠错包的目标，请先完成有效测评。</small>
              <el-button type="primary" :loading="selectingOption === correctionPackageOption.option_id" :disabled="!correctionPackageOption.eligible" @click="selectCorrectionPackage">生成纠错包与新测评</el-button>
            </section>
            <section v-if="generationOptions" class="tier-learning-choice followup-choice" :class="isTierLearning ? `tier-${learningIntent}` : 'tier-default'">
            <div class="intent-selection-row">
              <span class="choice-kicker">方案 {{ correctionPackageOption ? '二' : '一' }}</span>
              <strong>{{ isDowngradeLearning ? (nextStepRecommendation.alternative_learning_title || learningModeLabel) : learningIntentTitle }}</strong>
              <el-radio-group v-if="!isDowngradeLearning" v-model="learningIntent" class="intent-mode-choice">
                <el-radio-button :label="isUpgradeLearning ? 'upgrade_learning' : 'learn_new_knowledge'">学习新节点</el-radio-button>
                <el-radio-button label="reinforce_weakness">复习旧节点</el-radio-button>
                <el-radio-button v-if="canUseMixedIntent" label="learn_new_and_reinforce">一新一旧</el-radio-button>
              </el-radio-group>
              <small v-if="isDowngradeLearning">{{ nextStepRecommendation.alternative_learning_description || nextStepRecommendation.description }}</small>
              <small v-else>仅显示当前学习阶的节点；每次最多选择 2 个，不跨阶补位。</small>
            </div>
            <div v-if="generationOptions && isDowngradeLearning" class="intent-node-row">
              <span>{{ learningModeLabel }}目标（最多 2 个；低一阶或同阶前置）：</span>
              <el-checkbox-group v-model="selectedIntentNodes" class="resource-type-choice" :max="2">
                <el-checkbox v-for="node in learningCandidates" :key="node.skill_node_id" :label="node.skill_node_id" :disabled="node.blocked_by_node_ids?.length > 0">
                  {{ node.name }} · 第 {{ node.tier }} 阶<span v-if="learningIntent === 'downgrade_learning'">（{{ downgradeCandidateLabel(node) }}）</span><span v-else-if="node.priority_group === 'learned'">（已学习）</span><small v-if="node.blocked_by_node_ids?.length">（需先学习前置能力）</small>
                </el-checkbox>
              </el-checkbox-group>
              <div v-if="isDowngradeLearning && preferredLearningNodes.length" class="preferred-learning-nodes"><b>优先选择</b><el-tag v-for="node in preferredLearningNodes" :key="node.skill_node_id" effect="plain">{{ node.name }} · {{ downgradeCandidateLabel(node) }}</el-tag><small>按前置链由近到远排序，优先补齐最接近本轮学习目标的未掌握节点。</small></div>
              <em v-if="!learningCandidates.length">当前没有可用于{{ learningModeLabel }}的节点。</em>
            </div>
            <div v-if="generationOptions && !isDowngradeLearning && learningIntent !== 'learn_new_and_reinforce'" class="intent-node-row">
              <span>选择能力节点（最多 2 个）：</span>
              <el-checkbox-group v-model="selectedIntentNodes" class="resource-type-choice" :max="2">
                <el-checkbox v-for="node in intentCandidates" :key="node.skill_node_id" :label="node.skill_node_id" :disabled="node.blocked_by_node_ids?.length > 0">
                  {{ node.name }} · 第 {{ node.tier }} 阶<small v-if="node.blocked_by_node_ids?.length">（需先学习前置能力）</small>
                </el-checkbox>
              </el-checkbox-group>
              <em v-if="!intentCandidates.length">当前没有此类可选能力节点。</em>
            </div>
            <div v-if="generationOptions && learningIntent === 'learn_new_and_reinforce'" class="intent-node-row mixed-intent-row">
              <span>一新一旧学习：</span>
              <div class="mixed-node-choice"><b>新节点（选 1）</b><el-checkbox-group v-model="selectedNewIntentNodes" class="resource-type-choice" :max="1"><el-checkbox v-for="node in newIntentCandidates" :key="node.skill_node_id" :label="node.skill_node_id" :disabled="node.blocked_by_node_ids?.length > 0">{{ node.name }} · 第 {{ node.tier }} 阶</el-checkbox></el-checkbox-group></div>
              <div class="mixed-node-choice"><b>旧节点（选 1）</b><el-checkbox-group v-model="selectedReviewIntentNodes" class="resource-type-choice" :max="1"><el-checkbox v-for="node in reviewIntentCandidates" :key="node.skill_node_id" :label="node.skill_node_id">{{ node.name }} · 第 {{ node.tier }} 阶</el-checkbox></el-checkbox-group></div>
            </div>
            <div class="resource-selection-row"><span>生成资源：</span>
          <el-checkbox-group v-model="selectedResourceTypes" class="resource-type-choice">
            <el-checkbox label="讲义">讲义</el-checkbox>
            <el-checkbox label="实操指南">实操指南</el-checkbox>
            <el-checkbox label="分阶测试题">分阶测试题</el-checkbox>
            <el-checkbox label="复习清单">复习清单</el-checkbox>
            <el-checkbox label="案例分析">案例分析</el-checkbox>
          </el-checkbox-group>
          <el-checkbox v-model="includeClaimCheck" class="claim-check-choice">启用 Claim 审核</el-checkbox>
          <el-select v-if="!generationOptions" v-model="selectedDifficulty" class="difficulty-choice" aria-label="资源难度">
            <el-option label="初级" value="初级" />
            <el-option label="中级" value="中级" />
            <el-option label="高级" value="高级" />
          </el-select>
          <el-tag v-else class="difficulty-choice locked-difficulty" effect="plain">当前学习阶锁定：{{ generationOptions.recommended_difficulty }}</el-tag>
          <el-button
            class="custom-generation-button"
            type="primary"
            :loading="selectingOption === 'custom-selection'"
            :disabled="!selectedResourceTypes.length || (generationOptions && !canGenerateSelectedIntent)"
            @click="selectFeedbackOption('custom-selection')"
          >
            生成已选资源
          </el-button>
            </div>
            </section>
          </template>
          <section v-else class="selected-followup-card">
            <div class="selected-followup-heading"><span class="choice-kicker">已确认下一步</span><strong>{{ followupSelectionLabel }}</strong><p>这是你本次确认的学习路径，已创建对应资源任务。</p></div>
            <div class="selected-followup-targets"><b>学习节点</b><el-tag v-for="nodeName in followupSelection.node_names" :key="nodeName" effect="plain">{{ nodeName }}</el-tag><span v-if="!followupSelection.node_names?.length">将按本次确认的资源范围继续学习</span></div>
            <div class="selected-followup-meta"><span>资源任务已创建</span><small v-if="result.followup_run_ids?.length > 1">共 {{ result.followup_run_ids.length }} 个独立任务</small></div>
            <el-button type="primary" @click="goToFollowupRun">查看已选资源</el-button>
          </section>
        </div>
      </section>
      <div class="result-actions"><span v-if="(result.followup_run_ids?.length || 0) > 1" class="followup-count">已创建 {{ result.followup_run_ids.length }} 个独立资源任务</span><el-button plain @click="router.push('/report')">查看学习报告</el-button><el-button type="primary" plain :disabled="!result.followup_run_id" @click="goToFollowupRun">查看已选资源</el-button></div>
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
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { CircleCheck, VideoPlay } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { feedbackApi, generateApi, knowledgeApi, profileApi, resourceApi } from '../../api'
import { useAppStore } from '../../stores/app'
import { formatDateTime } from '../../utils/generationDisplay'
import TutorDrawer from '../tutor/TutorDrawer.vue'
import { countTutorTurns } from '../../utils/tutorState'

const router = useRouter()
const route = useRoute()
const store = useAppStore()
const workspaceRef = ref(null)
const resultPanelRef = ref(null)
const selectedLearnerId = ref(route.query.learnerId || store.currentLearnerId || localStorage.getItem('last_learner_id') || '')
const form = reactive({ learner_id: selectedLearnerId.value, completed: true, time_spent_seconds: 1800, self_rating: 4, difficulty_feeling: '', helpful_part: '', confusing_part: '', comment: '' })
const resources = ref([])
const generationJobs = ref([])
const feedbackResults = ref([])
const profiles = ref([])
const tracks = ref([])
const selectedRunId = ref(route.query.batchId || route.query.runId || localStorage.getItem('current_generation_run_id') || '')
const submitting = ref(false)
const feedbackStatus = ref('')
const selectingOption = ref('')
const result = ref(null)
const selectedResourceTypes = ref([])
const includeClaimCheck = ref(false)
const selectedDifficulty = ref('中级')
const learningIntent = ref('reinforce_weakness')
const selectedIntentNodes = ref([])
const selectedNewIntentNodes = ref([])
const selectedReviewIntentNodes = ref([])
const evaluation = reactive({ topic: '', questions: [], resourceIds: [] })
const evaluationAnswers = reactive({})
const tutorOpen = ref(false)
const tutorQuestion = ref(null)
const tutorHelpCount = ref(0)

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
    if (!groups.has(batchId)) groups.set(batchId, { runId: batchId, batchId, shortRunId: batchId.startsWith('resource:') ? '独立资源' : batchId.slice(0, 8).toUpperCase(), finishedAt: resource.created_at || '', resources: [] })
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
      const pendingCorrectionRun = correctionRuns.find((job) => !completedRunIds.value.has(job.run_id))
      const completed = task.resources.some((resource) => (
        completedRunIds.value.has(resource.run_id) || completedRunIds.value.has(resource.batch_id)
      )) && !pendingCorrectionRun
      return {
        ...task,
        completed,
        pendingCorrectionRunId: pendingCorrectionRun?.run_id || '',
        batchLabel,
        label: `${batchLabel} / ${task.resources.length} 份资源 / ${formatTaskTime(task.finishedAt)} / ${pendingCorrectionRun ? '待纠错测评' : completed ? '已反馈' : '待反馈'}`,
      }
    })
})
const activeTask = computed(() => taskGroups.value.find((item) => item.runId === selectedRunId.value) || taskGroups.value[0] || null)
const selectedBatchHasFeedback = computed(() => Boolean(taskGroups.value.find((item) => item.runId === selectedRunId.value)?.completed))
const pendingCorrectionRunId = computed(() => activeTask.value?.pendingCorrectionRunId || '')
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
const nextStepResourceLabel = computed(() => {
  if (!result.value?.followup_run_id) return '由你决定'
  const names = feedbackReport.value?.followup_selection?.node_names || []
  return names.length ? names.join('、') : '已确认'
})
const studyTimeLabel = computed(() => `${Math.floor((form.time_spent_seconds || 0) / 60)} 分钟`)
const generationOptions = computed(() => result.value?.generation_options || null)
const tierProgress = computed(() => generationOptions.value?.tier_progress || null)
const correctionPackageOption = computed(() => result.value?.correction_package_option || null)
const intentCandidates = computed(() => {
  // 升阶学习只能选择当前阶的可学习新节点；learning_candidates 还包含
  // 降阶/复习场景使用的历史节点，不能直接用于升阶选择器。
  if (learningIntent.value === 'upgrade_learning') return generationOptions.value?.learn_new_knowledge || []
  return generationOptions.value?.[learningIntent.value] || []
})
const learningCandidates = computed(() => learningIntent.value === 'downgrade_learning'
  ? result.value?.feedback_report?.downgrade_learning_candidates || []
  : generationOptions.value?.learning_candidates || [])
const preferredLearningNodes = computed(() => {
  const preferredIds = nextStepRecommendation.value?.default_learning_node_ids || []
  const byId = new Map(learningCandidates.value.map((node) => [node.skill_node_id, node]))
  return preferredIds.map((nodeId) => byId.get(nodeId)).filter(Boolean)
})
const isTierLearning = computed(() => ['downgrade_learning', 'upgrade_learning'].includes(learningIntent.value))
const isDowngradeLearning = computed(() => learningIntent.value === 'downgrade_learning')
const isUpgradeLearning = computed(() => learningIntent.value === 'upgrade_learning')
const learningModeLabel = computed(() => ({
  downgrade_learning: '降阶学习',
  upgrade_learning: '升阶学习',
}[learningIntent.value] || '学习方式'))
const learningIntentTitle = computed(() => ({
  learn_new_knowledge: '学习新节点',
  reinforce_weakness: '复习旧节点',
  learn_new_and_reinforce: '一新一旧学习',
  downgrade_learning: '降阶学习',
  upgrade_learning: '升阶学习',
}[learningIntent.value] || '选择学习方式'))
const feedbackReport = computed(() => result.value?.feedback_report || {})
const nextStepRecommendation = computed(() => feedbackReport.value?.next_step_recommendation || {})
const followupSelection = computed(() => feedbackReport.value?.followup_selection || {})
const followupSelectionLabel = computed(() => ({
  correction_package: '纠错包巩固',
  lower_tier_selection: '降阶学习（低阶前置）',
  same_tier_prerequisite: '降阶学习（同阶前置）',
  cross_tier_prerequisite_review: '前置复习与进阶学习',
  same_tier: '当前阶学习',
}[followupSelection.value?.selection_type] || '已选学习方案'))
const newIntentCandidates = computed(() => [
  ...(generationOptions.value?.learn_new_knowledge || []),
  ...(generationOptions.value?.cross_tier_new_knowledge || []),
])
const reviewIntentCandidates = computed(() => [
  ...(generationOptions.value?.reinforce_weakness || []),
  ...(generationOptions.value?.cross_tier_prerequisite_review || []),
])
const canUseMixedIntent = computed(() => newIntentCandidates.value.some((item) => !(item.blocked_by_node_ids || []).length) && reviewIntentCandidates.value.length > 0)
const selectedNodesForFollowup = computed(() => learningIntent.value === 'learn_new_and_reinforce'
  ? [...selectedNewIntentNodes.value, ...selectedReviewIntentNodes.value]
  : selectedIntentNodes.value)
const canGenerateSelectedIntent = computed(() => learningIntent.value === 'learn_new_and_reinforce'
  ? selectedNewIntentNodes.value.length === 1 && selectedReviewIntentNodes.value.length === 1
  : selectedIntentNodes.value.length > 0)

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
    const recommendation = value?.feedback_report?.next_step_recommendation || {}
    const scoreRate = Number(value?.feedback_report?.score_rate)
    const scoreBasedIntent = scoreRate >= 0.8 && options.recommendation_type === 'advance'
      ? 'upgrade_learning'
      : (scoreRate < 0.8 && value?.feedback_report?.downgrade_learning_candidates?.length ? 'downgrade_learning' : null)
    const scoreRequiresDowngrade = Boolean(recommendation.recommended_action === 'correction_package'
      && scoreRate < 0.8
      && value?.feedback_report?.downgrade_learning_candidates?.length)
    const suggestedIntent = scoreRequiresDowngrade
      ? 'downgrade_learning'
      : recommendation.learning_intent || recommendation.alternative_learning_intent || scoreBasedIntent
    const usingAlternativeIntent = Boolean(scoreRequiresDowngrade)
      || (!recommendation.learning_intent && Boolean(recommendation.alternative_learning_intent))
    const supportedIntents = ['downgrade_learning', 'upgrade_learning', 'learn_new_knowledge', 'reinforce_weakness', 'learn_new_and_reinforce']
    learningIntent.value = supportedIntents.includes(suggestedIntent)
      ? suggestedIntent
      : 'learn_new_knowledge'
    selectedNewIntentNodes.value = [...(usingAlternativeIntent
      ? recommendation.alternative_new_node_ids || []
      : recommendation.default_new_node_ids || [])].slice(0, 1)
    selectedReviewIntentNodes.value = [...(usingAlternativeIntent
      ? recommendation.alternative_review_node_ids || []
      : recommendation.default_review_node_ids || [])].slice(0, 1)
    const defaultNodeIds = usingAlternativeIntent
      ? (recommendation.alternative_learning_node_ids || [])
      : (recommendation.default_learning_node_ids || recommendation.default_new_node_ids || recommendation.default_review_node_ids || [])
    selectedIntentNodes.value = [...defaultNodeIds].slice(0, 2)
    if (learningIntent.value !== 'learn_new_and_reinforce') resetIntentNodes(selectedIntentNodes.value)
  } else {
    selectedIntentNodes.value = []
    selectedNewIntentNodes.value = []
    selectedReviewIntentNodes.value = []
  }
})

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
function resetIntentNodes(preferredIds = []) {
  const candidates = (isDowngradeLearning.value ? learningCandidates.value : intentCandidates.value)
    .filter((item) => !(item.blocked_by_node_ids || []).length)
    .map((item) => item.skill_node_id)
  const preferred = preferredIds.filter((id) => candidates.includes(id))
  selectedIntentNodes.value = preferred.length
    ? preferred.slice(0, 2)
    : isTierLearning.value || learningIntent.value === 'learn_new_knowledge' ? candidates.slice(0, 1) : candidates.slice(0, 2)
}
function downgradeCandidateLabel(node) {
  if (node?.reason_codes?.includes('SAME_TIER_PREREQUISITE')) return '同阶前置'
  const distance = (node?.reason_codes || []).find((code) => code.startsWith('PREREQUISITE_DISTANCE_'))
  const suffix = distance ? ` · 前置 ${distance.split('_').pop()} 层` : ''
  return `${node?.tier < (tierProgress.value?.active_tier || node?.tier) ? '低阶前置' : '同阶前置'}${suffix}`
}
watch(learningIntent, (intent) => {
  if (!generationOptions.value || intent === 'learn_new_and_reinforce') return
  resetIntentNodes()
})
function scrollToWorkspace() { workspaceRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
async function startEvaluation() { await loadEvaluationSession({ forceNew: true }); scrollToWorkspace() }
function selectBatch() {
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
  const evaluationRunId = pendingCorrectionRunId.value
  const existing = feedbackResults.value.find((item) => (
    item.attempt?.source_run_id === (evaluationRunId || selectedRunId.value)
    || (!evaluationRunId && item.attempt?.metadata?.session_id === selectedRunId.value)
  ))
  if (existing && !forceNew) { result.value = existing; return }
  result.value = null
  if (!form.learner_id || !selectedRunId.value) return
  try {
    const res = evaluationRunId
      ? await feedbackApi.getRunEvaluationSession(form.learner_id, evaluationRunId)
      : await feedbackApi.getBatchEvaluationSession(form.learner_id, selectedRunId.value)
    evaluation.topic = res.data.topic || ''
    evaluation.questions = res.data.questions || []
    evaluation.resourceIds = res.data.resource_ids || []
    resetEvaluationAnswers()
    evaluation.questions.forEach((question) => { evaluationAnswers[question.question_id] = question.question_type === 'multiple_choice' ? [] : '' })
    localStorage.setItem('current_generation_run_id', evaluationRunId || selectedRunId.value)
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
  feedbackStatus.value = '已提交反馈，正在生成反馈报告与建议。'
  try {
    const submittedAt = new Date()
    const evaluationRunId = pendingCorrectionRunId.value
    const payload = {
      learner_id: form.learner_id, source_resource_id: evaluation.resourceIds[0] || activeTask.value?.resources?.[0]?.resource_id,
      idempotency_key: buildIdempotencyKey(evaluationRunId || selectedRunId.value, submittedAt), expected_profile_version: store.currentProfile?.profile_version || 1,
      submitted_at: submittedAt.toISOString(), duration_ms: (form.time_spent_seconds || 0) * 1000, hint_count: tutorHelpCount.value,
      answers: evaluation.questions.map((question) => ({ question_id: question.question_id, answer: evaluationAnswers[question.question_id] })),
      metadata: { source: 'feedback_view', client_version: 'web', session_id: evaluationRunId || selectedRunId.value, learning_reflection: { completed: form.completed, time_spent_seconds: form.time_spent_seconds, self_rating: form.self_rating, difficulty_feeling: form.difficulty_feeling, helpful_part: form.helpful_part.trim(), confusing_part: form.confusing_part.trim(), comment: form.comment.trim() } },
    }
    const res = evaluationRunId
      ? await feedbackApi.submitRunAttempt({ ...payload, run_id: evaluationRunId })
      : await feedbackApi.submitBatchAttempt({ ...payload, batch_id: selectedRunId.value })
    result.value = res.data
    feedbackResults.value = [res.data, ...feedbackResults.value.filter((item) => item.attempt?.attempt_id !== res.data.attempt?.attempt_id)]
    if (store.currentProfile) store.setCurrentProfile({ ...store.currentProfile, profile_version: res.data.profile_version })
    ElMessage.success('本轮练习反馈已提交')
    await nextTick()
    resultPanelRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    feedbackStatus.value = ''
  } catch (error) {
    console.error(error)
    feedbackStatus.value = ''
    ElMessage.error(error?.response?.data?.message || '提交失败，请稍后再试')
  } finally { submitting.value = false }
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
      include_claim_check: includeClaimCheck.value,
      ...(!generationOptions.value ? { difficulty: selectedDifficulty.value } : {}),
      ...(generationOptions.value ? {
        learning_intent: learningIntent.value,
        selected_skill_node_ids: selectedNodesForFollowup.value,
        next_generation_snapshot_hash: generationOptions.value.snapshot_hash,
      } : {}),
    })
    result.value = res.data
    ElMessage.success('已确认下一步资源方案，正在创建生成任务')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || error?.response?.data?.detail || '资源方案确认失败')
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
      include_claim_check: includeClaimCheck.value,
      selected_skill_node_ids: option.recommended_target_ids,
      next_generation_snapshot_hash: option.snapshot_hash,
    })
    result.value = res.data
    ElMessage.success('纠错包与新测评题正在创建')
  } catch (error) {
    console.error(error)
    ElMessage.error(error?.response?.data?.message || error?.response?.data?.detail || '强化包创建失败')
  } finally { selectingOption.value = '' }
}
function goToFollowupRun() {
  const runIds = result.value?.followup_run_ids?.length ? result.value.followup_run_ids : [result.value?.followup_run_id]
  const runId = runIds[0]
  if (!runId) return
  localStorage.setItem('current_generation_run_id', runId)
  localStorage.setItem('current_generation_run_ids', JSON.stringify(runIds.filter(Boolean)))
  router.push({ path: '/generate', query: { runId, learnerId: form.learner_id } })
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
.question-tools { display: flex; grid-column: 3; align-items: center; align-self: start; justify-content: flex-end; flex-wrap: wrap; gap: 4px; }
.question-tools :deep(.el-tag) { max-width: 180px; height: auto; padding: 4px 7px; white-space: normal; text-align: center; line-height: 1.25; }
.question-tools :deep(.question-type-tag) { color: #35628e; border-color: #c6d8eb; background: #f3f8fd; }
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
  display: flex;
  flex-wrap: wrap;
  min-height: 64px;
  margin-top: 14px;
  padding: 12px 13px;
  border: 1px solid #cfe2ff;
  border-radius: 10px;
  background: #f6f9ff;
}
.submit-box strong { color: #17447e; letter-spacing: .01em; }
.feedback-generation-status {
  flex: 0 0 100%;
  margin: 8px 0 0;
  color: #2058a7;
  font-size: 13px;
  font-weight: 700;
}
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
.intent-mode-choice { display:flex; flex-wrap:wrap; gap:4px; }
.mixed-intent-row { align-items:flex-start; }
.mixed-node-choice { display:grid; gap:6px; min-width:230px; padding:8px 10px; border-radius:8px; background:#fff; }
.mixed-node-choice b { color:#355571; font-size:12px; }
.resource-type-choice { display:flex; flex-wrap:wrap; gap:5px 13px; }
.difficulty-choice { width:120px; }
.custom-generation-button { margin-left:auto; font-weight:750; }
.result-actions { display:flex; grid-column:auto; justify-content:flex-end; gap:10px; }

@media (max-width: 900px) {
  .result-header,.next-step-panel { grid-template-columns:1fr; }
  .result-metrics,.capability-result-list { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .correction-package-card { grid-template-columns:1fr; }.correction-package-card small { grid-column:auto; }
}
.analysis-summary {
  padding: 20px 22px;
  border: 1px solid #cfe3f3;
  border-left: 4px solid #2058a7;
  border-radius: 12px;
  background: linear-gradient(135deg, #f7fbff 0%, #f4fcf8 100%);
  box-shadow: 0 8px 20px rgb(36 83 116 / 7%);
}
.analysis-summary .analysis-heading {
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid #dce9f2;
}
.analysis-summary .analysis-heading strong { color: #183b5a; font-size: 20px; letter-spacing: .01em; }
.analysis-summary .analysis-heading span { color: #6a8196; font-size: 12px; }
.analysis-summary > p { margin: 15px 0 0; color: #304f6b; font-size: 15px; line-height: 1.8; }
.analysis-summary > .reflection-insight {
  margin-top: 13px;
  padding: 12px 14px;
  border-left: 3px solid #46a98e;
  border-radius: 0 8px 8px 0;
  background: rgb(255 255 255 / 72%);
  color: #376354;
}
.analysis-summary ul { display: grid; gap: 8px; margin: 15px 0 0; padding: 0; list-style: none; }
.analysis-summary li {
  position: relative;
  padding: 10px 12px 10px 31px;
  border: 1px solid #dce9f1;
  border-radius: 8px;
  background: rgb(255 255 255 / 82%);
  color: #49657e;
  font-size: 13px;
  line-height: 1.55;
}
.analysis-summary li::before {
  position: absolute;
  top: 10px;
  left: 12px;
  color: #2d997c;
  content: '✓';
  font-weight: 800;
}
@media (max-width: 560px) {
  .analysis-summary { padding: 16px; }
  .analysis-summary .analysis-heading { align-items: flex-start; flex-direction: column; gap: 4px; }
  .analysis-summary > p { font-size: 14px; }
}
.next-step-panel {
  grid-template-columns: minmax(225px, .34fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
  padding: 16px 18px;
}
.next-step-copy { min-width: 0; padding: 4px 16px 4px 2px; border-right: 1px solid #d9e9e4; }
.next-step-copy h4 { font-size: 21px; line-height: 1.25; }
.next-step-copy p { margin-top: 7px; font-size: 12px; line-height: 1.55; }
.next-step-copy small { display: block; margin-top: 10px; color: #52786d; font-size: 11px; line-height: 1.5; }
.next-step-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; align-content: start; }
.next-step-actions > * { min-width: 0; }
.correction-package-card { grid-column: 1 / -1; grid-template-columns: minmax(180px, 1fr) auto auto; gap: 9px 14px; padding: 12px 14px; }
.correction-package-card > div:first-child p { margin: 3px 0 0; }
.correction-package-card small { grid-column: auto; align-self: center; }
.correction-package-card .el-button { white-space: nowrap; }
.fixed-correction-targets { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.curriculum-progress-row,.intent-selection-row,.intent-node-row,.resource-selection-row { grid-column: 1 / -1; margin: 0; }
.curriculum-progress-row { align-items: center; padding: 9px 11px; font-size: 12px; }
.intent-selection-row { display: flex; align-items: center; padding: 9px 11px; border-color: #cfe2ff; background: #f4f8ff; }
.intent-selection-row > span:first-child { color: #28517d; }
.intent-mode-choice :deep(.el-radio-button__inner) { padding: 6px 10px; font-size: 12px; }
.intent-selection-row small { margin-left: auto; width: auto; }
.intent-node-row { display: grid; grid-template-columns: auto minmax(0, 1fr); align-items: center; padding: 9px 11px; font-size: 12px; }
.intent-node-row > span:first-child { color: #355571; }
.intent-node-row .resource-type-choice { min-width: 0; }
.intent-node-row em { grid-column: 2; }
.mixed-intent-row { grid-template-columns: auto minmax(0, 1fr) minmax(0, 1fr); align-items: start; }
.mixed-intent-row > span:first-child { padding-top: 8px; }
.mixed-node-choice { min-width: 0; padding: 7px 9px; border: 1px solid #d9e6f4; }
.resource-selection-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto auto; align-items: center; gap: 8px 11px; padding-top: 1px; font-size: 12px; }
.resource-selection-row .resource-type-choice { min-width: 0; }
.resource-selection-row .claim-check-choice { white-space: nowrap; }
.resource-selection-row .difficulty-choice { width: 126px; }
.custom-generation-button { margin-left: 0; white-space: nowrap; }
@media (max-width: 1120px) {
  .next-step-panel { grid-template-columns: 1fr; }
  .next-step-copy { padding: 0 0 12px; border-right: 0; border-bottom: 1px solid #d9e9e4; }
}
@media (max-width: 820px) {
  .next-step-actions { grid-template-columns: 1fr; }
  .correction-package-card,.curriculum-progress-row,.intent-selection-row,.intent-node-row,.resource-selection-row { grid-column: auto; }
  .resource-selection-row { display: flex; flex-wrap: wrap; }
  .resource-selection-row .resource-type-choice { flex: 1 1 100%; }
  .intent-selection-row small { width: 100%; margin-left: 0; }
  .mixed-intent-row { grid-template-columns: 1fr; }
  .mixed-intent-row > span:first-child { padding-top: 0; }
}
@media (max-width: 560px) {
  .next-step-panel { padding: 14px; }
  .correction-package-card { grid-template-columns: 1fr; }
  .correction-package-card small { grid-column: auto; }
  .intent-node-row { grid-template-columns: 1fr; gap: 6px; }
  .intent-node-row em { grid-column: auto; }
}
.next-step-actions { grid-template-columns: minmax(0, 1fr); gap: 12px; }
.followup-choice { grid-column: auto; }
.choice-kicker { display: block; color: #47708d; font-size: 15px; font-weight: 800; letter-spacing: .03em; line-height: 1.25; }
.correction-choice { grid-template-columns: minmax(220px, 1.15fr) minmax(170px, .85fr) minmax(150px, auto); grid-template-rows: auto auto; border-color: #9fdcc9; background: linear-gradient(125deg, #effcf7, #f8fffc); }
.correction-choice > div:first-child { grid-column: 1; grid-row: 1 / span 2; align-self: center; }
.correction-choice .fixed-correction-targets { grid-column: 2; grid-row: 1; align-self: end; }
.correction-choice small { grid-column: 2; grid-row: 2; align-self: start; }
.correction-choice > .el-button { grid-column: 3; grid-row: 1 / span 2; align-self: center; justify-self: end; min-width: 132px; }
.correction-choice .choice-kicker { color: #247a64; font-size: 15px; }
.correction-choice > div:first-child .choice-kicker { display: inline; margin-right: 10px; vertical-align: baseline; }
.correction-choice > div:first-child strong { display: inline; margin-top: 0; font-size: 18px; vertical-align: baseline; }
.tier-learning-choice { display: grid; gap: 10px; padding: 14px; border: 1px solid #cfe2ff; border-radius: 11px; background: #f7fbff; }
.tier-learning-choice.tier-downgrade_learning { border-color: #c8dbf5; background: linear-gradient(125deg, #f4f8ff, #fbfdff); }
.tier-learning-choice.tier-upgrade_learning { border-color: #b9dfd2; background: linear-gradient(125deg, #f2fbf8, #fbfffd); }
.tier-learning-choice .intent-selection-row { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; gap: 9px 12px; align-items: center; padding: 0 0 10px; border: 0; border-bottom: 1px solid #dce9f5; border-radius: 0; background: transparent; }
.tier-learning-choice .intent-selection-row strong { color: #1d4e7d; font-size: 17px; }
.tier-learning-choice .intent-selection-row .choice-kicker { font-size: 15px; }
.tier-upgrade_learning .intent-selection-row strong { color: #247a64; }
.tier-learning-choice .intent-selection-row small { grid-column: 1 / -1; width: auto; margin: 0; color: #637e97; }
.tier-learning-choice .intent-node-row { grid-column: auto; border-color: #d8e7f3; background: rgb(255 255 255 / 76%); }
.tier-learning-choice .resource-selection-row { grid-column: auto; padding: 10px 0 0; border-top: 1px solid #dce9f5; }
.next-step-panel { grid-template-columns: minmax(260px, .34fr) minmax(0, 1fr); gap: 16px; }
.next-step-actions { align-self: center; }
.next-step-copy {
  display: block;
  align-self: start;
  padding: 5px 17px 8px 2px;
  border: 0;
  border-right: 1px solid #d9e9e4;
  border-radius: 0;
  background: transparent;
}
.next-step-title { min-width: 0; }
.next-step-copy h4 { margin: 3px 0 0; font-size: 20px; }
.next-step-reason { min-width: 0; margin-top: 13px; padding: 11px 12px; border-left: 3px solid #54aa91; background: rgb(255 255 255 / 52%); }
.next-step-reason b { color: #2b6d5c; font-size: 12px; }
.next-step-reason p { margin: 3px 0 0; color: #526f85; font-size: 13px; line-height: 1.55; }
.next-step-copy > small { margin-top: 11px; padding-left: 0; border-left: 0; white-space: normal; }
.preferred-learning-nodes {
  grid-column: 2;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 7px;
  color: #45637d;
}
.preferred-learning-nodes b { color: #28517d; font-size: 12px; }
.preferred-learning-nodes .el-tag { border-color: #9fc5f6; color: #2861a1; }
.preferred-learning-nodes small { flex: 1 0 100%; color: #698298; font-size: 11px; }
.selected-followup-card {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) minmax(240px, 1.25fr) auto auto;
  gap: 14px 22px;
  align-items: center;
  min-height: 132px;
  padding: 18px 20px;
  border: 1px solid #9fdcc9;
  border-radius: 12px;
  background: linear-gradient(125deg, #effcf7, #fbfffd);
}
.selected-followup-heading strong { display: block; margin-top: 3px; color: #176950; font-size: 20px; }
.selected-followup-heading p { margin: 5px 0 0; color: #547a70; font-size: 13px; line-height: 1.55; }
.selected-followup-targets { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
.selected-followup-targets b { flex: 0 0 100%; color: #2c6455; font-size: 12px; }
.selected-followup-targets .el-tag { border-color: #9fdcc9; color: #21745e; background: #fff; }
.selected-followup-targets > span { color: #698298; font-size: 13px; }
.selected-followup-meta { display: grid; gap: 3px; color: #2a705c; font-size: 13px; white-space: nowrap; }
.selected-followup-meta small { color: #698298; font-size: 11px; }
.selected-followup-card .el-button { white-space: nowrap; }
@media (max-width: 980px) {
  .next-step-panel { grid-template-columns: 1fr; }
  .next-step-copy { padding: 0 0 12px; border-right: 0; border-bottom: 1px solid #d9e9e4; }
  .next-step-actions { align-self: stretch; }
  .selected-followup-card { grid-template-columns: 1fr auto; }
  .selected-followup-targets { grid-column: 1 / -1; }
}
@media (max-width: 820px) {
  .correction-choice { grid-template-columns: 1fr; grid-template-rows: none; }
  .correction-choice > div:first-child, .correction-choice .fixed-correction-targets, .correction-choice small, .correction-choice > .el-button { grid-column: auto; grid-row: auto; align-self: auto; justify-self: stretch; }
  .tier-learning-choice .intent-selection-row { grid-template-columns: 1fr; gap: 5px; }
}
.tier-learning-choice .resource-type-choice :deep(.el-checkbox) {
  min-height: 34px;
  margin: 0;
  padding: 6px 10px;
  border: 1px solid #d7e3ef;
  border-radius: 9px;
  background: #fff;
  color: #536b83;
  transition: border-color .2s ease, background .2s ease, color .2s ease, box-shadow .2s ease;
}
.tier-learning-choice .resource-type-choice :deep(.el-checkbox:hover) {
  border-color: #8bbcf2;
  color: #2d6fac;
  box-shadow: 0 3px 9px rgb(48 124 214 / 9%);
}
.tier-learning-choice .resource-type-choice :deep(.el-checkbox.is-checked) {
  border-color: #72b2f5;
  background: #eef6ff;
  color: #2875bd;
  box-shadow: 0 3px 9px rgb(48 124 214 / 10%);
}
.tier-learning-choice .resource-type-choice :deep(.el-checkbox.is-disabled) {
  border-color: #e1e8ef;
  background: #f6f8fa;
  color: #9aa8b6;
  box-shadow: none;
  cursor: not-allowed;
}
.tier-learning-choice .resource-type-choice :deep(.el-checkbox__label) {
  padding-left: 7px;
  color: inherit;
  font-weight: 600;
  line-height: 1.35;
  white-space: normal;
}
.tier-learning-choice .resource-type-choice :deep(.el-checkbox__input.is-checked .el-checkbox__inner) {
  border-color: #4297ef;
  background: #4297ef;
}
.tier-learning-choice .intent-node-row .resource-type-choice {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(205px, 1fr));
  gap: 8px;
}
.tier-learning-choice .intent-node-row .resource-type-choice :deep(.el-checkbox) {
  min-width: 0;
  min-height: 40px;
  align-items: center;
  padding: 9px 11px;
}
.tier-learning-choice .resource-selection-row .resource-type-choice :deep(.el-checkbox) {
  min-height: 32px;
  padding: 5px 9px;
  border-radius: 8px;
}
@media (max-width: 820px) {
  .tier-learning-choice .intent-node-row .resource-type-choice { grid-template-columns: 1fr; }
}
</style>
