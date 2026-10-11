<template>
  <div class="feedback-page">
    <section class="feedback-hero">
      <div class="task-selection task-selection-inline">
        <label class="task-filter-field">
          <span class="task-selection-label">学习画像<small aria-hidden="true">PROFILE</small></span>
          <el-select v-model="selectedLearnerId" filterable aria-label="学习画像" placeholder="选择学习画像" class="profile-select" popper-class="refined-select-dropdown" @change="handleProfileChange">
            <el-option v-for="profile in profileOptions" :key="profile.learner_id" :label="profile.label" :value="profile.learner_id" />
          </el-select>
        </label>
        <label class="task-filter-field">
          <span class="task-selection-label">本轮资源批次<small aria-hidden="true">BATCH</small></span>
          <el-select v-model="selectedRunId" filterable aria-label="本轮资源批次" placeholder="选择要反馈的学习资源批次" class="task-select" popper-class="refined-select-dropdown" @change="selectBatch">
            <el-option v-for="task in taskGroups" :key="task.runId" :label="task.label" :value="task.runId" />
          </el-select>
        </label>
        <el-button class="start-evaluation-button" type="primary" :icon="VideoPlay" @click="startEvaluation" :disabled="!selectedRunId">{{ selectedBatchHasFeedback ? '再次测评' : '开始测评' }}</el-button>
      </div>

      <p v-if="!activeTask" class="task-empty-tip">暂时没有可用于反馈的资源任务，请先完成一轮学习资源生成。</p>
    </section>

    <section v-if="!result" ref="workspaceRef" class="feedback-workspace" :class="{ 'has-empty-evaluation': !evaluation.questions.length }" v-module-motion="evaluation.questions.length ? selectedRunId : 'preparation'">
      <article class="evaluation-panel" :class="{ 'is-empty-evaluation': !evaluation.questions.length }">
        <div class="section-heading">
          <div>
            <span class="page-kicker">01 / PRACTICE CHECK</span>
            <h2>完成知识测评</h2>
            <p>题目会优先覆盖本轮资源涉及的知识点。</p>
          </div>
          <span v-if="evaluation.questions.length" class="progress-pill" :class="{ ready: allQuestionsAnswered }">{{ answeredCount }} / {{ evaluation.questions.length }} 已作答</span>
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
            { title: '应用与表达', description: '结合实际情境作答，需要时向 Tutor 获取提示。' },
            { title: '结果与下一步', description: '了解掌握情况，选择继续探索或巩固薄弱点。' },
          ]"
        >
          <template #footer><el-icon aria-hidden="true"><CircleCheck /></el-icon><span>用作答结果，了解真实掌握情况。</span></template>
        </PreparationPanel>

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
            <span class="page-kicker">02 / REFLECTION</span>
            <h2>记录学习感受</h2>
            <p>{{ evaluation.questions.length ? '这些反馈会跟随本次练习保存，为后续推荐提供依据。' : '记录你的体验，为后续推荐提供依据。' }}</p>
          </div>
          <span v-if="!evaluation.questions.length" class="progress-pill preparation-status">测评后记录</span>
        </div>

        <PreparationPanel
          v-if="!evaluation.questions.length"
          class="reflection-preparation"
          compact
          eyebrow="MAKE LEARNING YOURS"
          title="用一次复盘，找到下一轮的重点。"
          description="开始测评后，记录学习体验，让后续建议更贴近你。"
          :steps="[
            { title: '投入与节奏', description: '记录学习耗时与难度感受，找到适合自己的节奏。' },
            { title: '理解与掌握', description: '回顾掌握程度，留下对你最有帮助的内容。' },
            { title: '困惑与期待', description: '说明仍需解释的问题，以及下一轮想强化的重点。' },
          ]"
        >
          <template #mark><el-icon><ChatDotRound /></el-icon></template>
          <template #footer><el-icon aria-hidden="true"><CircleCheck /></el-icon><span>用体验反馈，完善后续学习建议。</span></template>
        </PreparationPanel>
        <div v-else class="reflection-fields">
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

        <div v-if="evaluation.questions.length" class="submit-box">
          <div>
            <strong>{{ allQuestionsAnswered ? '可以提交本轮反馈' : '请先完成全部测评题' }}</strong>
            <span>{{ allQuestionsAnswered ? '系统会根据结果为下一轮学习调整资源与重点。' : `还差 ${Math.max(evaluation.questions.length - answeredCount, 0)} 题未作答` }}</span>
          </div>
          <el-button class="submit-feedback-button" type="primary" :icon="CircleCheck" :loading="submitting" :disabled="!canSubmit || submitting" @click="submitEvaluation">提交反馈</el-button>
          <p v-if="feedbackStatus" class="feedback-generation-status" role="status">{{ feedbackStatus }}</p>
        </div>
      </aside>
    </section>

    <section v-if="result" id="feedback-report" ref="resultPanelRef" class="result-panel" v-module-motion="{ key: selectedRunId, appear: true }">
      <header class="result-header">
        <div class="result-summary">
        <span class="page-kicker">03 / LEARNING REVIEW</span>
        <h2>这次学习的回顾</h2>
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
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ChatDotRound, CircleCheck, VideoPlay } from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { feedbackApi, generateApi, knowledgeApi, profileApi, resourceApi } from '../../api'
import { useAppStore } from '../../stores/app'
import { formatDateTime } from '../../utils/generationDisplay'
import PreparationPanel from '../../components/PreparationPanel.vue'
import TutorDrawer from '../tutor/TutorDrawer.vue'
import { useFeedbackEvaluation } from './useFeedbackEvaluation.js'
import { useFeedbackFollowup } from './useFeedbackFollowup.js'
import { createRequestGuard } from '../../utils/requestContext.js'

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
  helpful_part: '',
  confusing_part: '',
  comment: ''
})
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
const feedbackContextVersion = ref(0)
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
const resourceRequests = createRequestGuard(() => ({
  learnerId: selectedLearnerId.value,
  formLearnerId: form.learner_id,
  contextVersion: feedbackContextVersion.value,
}))
const profileRequests = createRequestGuard(() => ({ contextVersion: feedbackContextVersion.value }))

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
    feedbackContextVersion.value += 1
    selectingOption.value = ''
    selectedLearnerId.value = value
    form.learner_id = value
  }
}, { flush: 'sync' })
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

function formatTaskTime(value) { return formatDateTime(value) }
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
function feedbackScrollBehavior() { return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }
function scrollToWorkspace() { workspaceRef.value?.scrollIntoView({ behavior: feedbackScrollBehavior(), block: 'start' }) }
async function startEvaluation() {
  const learnerId = form.learner_id
  const batchId = selectedRunId.value
  const contextVersion = feedbackContextVersion.value
  selectingOption.value = ''
  await loadEvaluationSession({ forceNew: true })
  if (learnerId === form.learner_id && batchId === selectedRunId.value && contextVersion === feedbackContextVersion.value) {
    scrollToWorkspace()
  }
}
function selectBatch() {
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
  feedbackContextVersion.value += 1
  resourceRequests.invalidate()
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
  try {
    const [res, jobsRes, resultsRes] = await Promise.all([
      resourceApi.listByLearner(learnerId),
      generateApi.listJobs(learnerId),
      feedbackApi.listResults(learnerId, { limit: 50 }),
    ])
    if (!request.isCurrent()) return
    resources.value = res.data.resources || []
    generationJobs.value = jobsRes.data.items || []
    feedbackResults.value = resultsRes.data || []
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
  resetEvaluationAnswers, requestTutorHint, recordTutorHelp, restoreTutorHelp,
  loadEvaluationSession, submitEvaluation, dispose: disposeEvaluation,
} = useFeedbackEvaluation({
  feedbackApi,
  form, selectedRunId, pendingCorrectionRunId, feedbackResults, result, evaluation,
  evaluationAnswers, tutorOpen, tutorQuestion, tutorHelpCount, canSubmit, submitting,
  feedbackStatus, activeTask, store, resultPanelRef, feedbackScrollBehavior, messages: ElMessage,
  contextVersion: feedbackContextVersion,
})


const {
  selectFeedbackOption, selectCorrectionPackage, goToFollowupRun, dispose: disposeFollowup,
} = useFeedbackFollowup({
  feedbackApi,
  form, result, selectingOption, selectedResourceTypes, includeClaimCheck, generationOptions,
  selectedDifficulty, learningIntent, selectedNodesForFollowup, correctionPackageOption,
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

<style scoped>
.feedback-page {
  --feedback-ink: #132c40;
  --feedback-muted: #536b7d;
  --feedback-navy: #11283c;
  --feedback-teal: #086575;
  --feedback-mint: #9cecdf;
  --feedback-line: #d9e4eb;
  --feedback-paper: #f5f7fa;
  --rag-ink: var(--feedback-ink);
  --rag-line: var(--feedback-line);
  --rag-surface: #fff;
  --rag-surface-alt: #f8fafb;
  --rag-blue-700: var(--feedback-navy);
  --rag-blue-800: #1d4055;
  --rag-blue-500: #187487;
  --rag-blue-50: #edf8f6;
  --rag-radius: 6px;
  --rag-shadow-soft: none;
  --page-gap: 16px;
  --el-color-primary: #167c7c;
  --el-color-primary-light-3: #529b9b;
  --el-color-primary-light-5: #8bbfbe;
  --el-color-primary-light-7: #c2e3de;
  --el-color-primary-light-8: #d9eeea;
  --el-color-primary-light-9: #edf8f6;
  --el-color-primary-dark-2: #086575;
  display: flex;
  min-width: 0;
  flex-direction: column;
  padding-top: 20px;
  color: var(--feedback-ink);
}
:global(.app-shell.is-feedback) { background: #f5f7fa; }
:global(.app-shell.is-feedback .topbar-kicker) { color: #086575; font: 11px/1.5 Consolas, 'SFMono-Regular', monospace; }
:global(.app-shell.is-feedback .topbar h1) { color: #132c40; font-weight: 700; }
:global(.app-shell.is-feedback .topbar-action) { min-height: 44px; border-radius: 5px; font-size: 12px; font-weight: 600; }
:global(.app-shell.is-feedback .topbar-meta span) { color: #536b7d; }
:global(.app-shell.is-feedback .topbar-meta strong) { color: #132c40; }
.feedback-hero, .evaluation-panel, .reflection-panel, .result-panel { min-width: 0; border: 1px solid var(--feedback-line); border-radius: 6px; background: #fff; }
.feedback-page .feedback-hero { padding: 16px 20px; border-top: 2px solid var(--feedback-navy) !important; }
.task-selection { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; align-items: end; }
.task-filter-field { display: grid; min-width: 0; gap: 6px; }
.task-selection-label { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; color: var(--feedback-muted); font-size: 12px; font-weight: 500; }
.task-selection-label small { flex-shrink: 0; font: 11px/1.5 Consolas, 'SFMono-Regular', monospace; }
.profile-select, .task-select { width: 100%; min-width: 0; }
.task-empty-tip { margin: 14px 0 0; padding-top: 12px; border-top: 1px solid var(--feedback-line); color: var(--feedback-muted); font-size: 13px; line-height: 1.6; }
.feedback-page :deep(.el-button) { min-height: 44px; height: auto; margin: 0; padding: 10px 16px; border-radius: 5px; font-size: 13px; font-weight: 600; line-height: 1.5; box-shadow: none; transition: border-color .18s ease, background-color .18s ease, color .18s ease; }
.feedback-page :deep(.el-button--primary) { border-color: var(--feedback-navy); background: var(--feedback-navy); color: #fff; }
.feedback-page :deep(.el-button--primary:hover) { border-color: #1d4055; background: #1d4055; color: #fff; }
.feedback-page :deep(.el-button--primary.is-plain), .result-actions :deep(.el-button) { border-color: #b9cdd8; background: #fff; color: var(--feedback-ink); }
.feedback-page :deep(.el-button--primary.is-plain:hover), .result-actions :deep(.el-button:hover) { border-color: var(--feedback-teal); background: #edf8f6; color: var(--feedback-teal); }
.feedback-page .start-evaluation-button { min-width: 120px; border-color: var(--feedback-navy) !important; background: var(--feedback-navy) !important; color: #fff !important; }
.feedback-page .start-evaluation-button:hover { border-color: #1d4055 !important; background: #1d4055 !important; }
.feedback-page .submit-feedback-button { width: 100%; border-color: #8bd8cc !important; background: var(--feedback-mint) !important; color: #123747 !important; }
.feedback-page .submit-feedback-button:hover { border-color: #6cc4b8 !important; background: #b4f2e8 !important; }
.feedback-page :deep(.el-button.is-disabled), .feedback-page :deep(.el-button.is-disabled:hover) { border-color: #d9e4e9 !important; background: #edf1f4 !important; color: #687b88 !important; box-shadow: none; }
.feedback-page :deep(.el-select__wrapper), .feedback-page :deep(.el-input__wrapper) { min-height: 44px; border-radius: 5px; background: #fff; box-shadow: 0 0 0 1px #cbdbe4 inset; }
.feedback-page :deep(.el-select__wrapper:hover), .feedback-page :deep(.el-input__wrapper:hover) { box-shadow: 0 0 0 1px #7099a7 inset; }
.feedback-page :deep(.el-select__wrapper.is-focused), .feedback-page :deep(.el-input__wrapper.is-focus) { box-shadow: 0 0 0 2px var(--feedback-teal) inset; }
.feedback-page :deep(.el-select__selection), .feedback-page :deep(.el-select__selected-item) { min-width: 0; }
.feedback-page :deep(.el-select__selected-item), .feedback-page :deep(.el-input__inner) { color: var(--feedback-ink); font-size: 14px; }
.feedback-page :deep(.el-textarea__inner) { padding: 11px 12px; border-radius: 5px; color: var(--feedback-ink); font-size: 14px; line-height: 1.65; box-shadow: 0 0 0 1px #cbdbe4 inset; }
.feedback-page :deep(.el-textarea__inner:focus) { box-shadow: 0 0 0 2px var(--feedback-teal) inset; }
.feedback-page :deep(.el-input__inner::placeholder), .feedback-page :deep(.el-textarea__inner::placeholder) { color: #617786; }
.feedback-page :deep(.el-tag) { height: auto; min-height: 26px; padding: 4px 8px; border-color: #c6dfe0; border-radius: 4px; background: #edf7f6; color: var(--feedback-teal); font-size: 12px; line-height: 1.4; white-space: normal; overflow-wrap: anywhere; }
.feedback-page :deep(.el-tag--warning) { border-color: #e6d7bc; background: #fcf8ef; color: #875914; }
.feedback-page .page-kicker { display: block; color: var(--feedback-teal) !important; font: 11px/1.5 Consolas, 'SFMono-Regular', monospace; }
.feedback-workspace { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(340px, .8fr); gap: 20px; align-items: start; }
.evaluation-panel { overflow: hidden; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 20px 24px 18px; border-bottom: 1px solid var(--feedback-line); }
.section-heading h2 { margin: 5px 0 0; font-size: 22px; font-weight: 650; line-height: 1.5; }
.section-heading p { margin: 6px 0 0; color: var(--feedback-muted); font-size: 13px; line-height: 1.65; }
.progress-pill { display: flex; flex: 0 0 auto; align-items: center; gap: 7px; padding: 6px 9px; border: 1px solid var(--feedback-line); border-radius: 4px; color: var(--feedback-muted); font: 12px/1.5 Consolas, 'Microsoft YaHei', monospace; white-space: nowrap; }
.progress-pill::before { width: 5px; height: 5px; flex-shrink: 0; border-radius: 50%; background: #78919f; content: ''; }
.progress-pill.ready { border-color: #a9d4cc; background: #edf8f6; color: var(--feedback-teal); }
.progress-pill.ready::before { background: #167c7c; }
.question-list { padding: 0 24px; }
.feedback-page .question-card { padding: 22px 0; border: 0; border-bottom: 1px solid var(--feedback-line); border-radius: 0; background: #fff !important; }
.feedback-page .question-card:last-child { border-bottom: 0; }
.feedback-page .question-card:hover { border-color: var(--feedback-line) !important; background: #fff !important; box-shadow: none !important; }
.question-topline { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.question-index { display: grid; flex: 0 0 32px; height: 32px; place-items: center; border: 1px solid #b9d8d8; border-radius: 4px; background: #edf7f6; color: var(--feedback-teal); font: 12px/1 Consolas, monospace; }
.question-tools { display: flex; min-width: 0; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; }
.question-tools :deep(.el-tag) { max-width: 240px; }
.question-tools :deep(.question-type-tag) { background: #f5f8fa; border-color: var(--feedback-line); color: var(--feedback-muted); }
.question-tools :deep(.el-button) { min-width: 88px; padding-inline: 12px; border: 1px solid #b9cdd8; background: #fff; color: var(--feedback-teal); }
.question-tools :deep(.el-button:hover) { border-color: #80b5b7; background: #edf8f6; }
.question-card > strong { display: block; margin: 14px 0 0; font-size: 16px; font-weight: 600; line-height: 1.75; overflow-wrap: anywhere; }
.answer-options { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 16px; }
.answer-options :deep(.el-radio), .answer-options :deep(.el-checkbox) { display: flex; align-items: flex-start; width: 100%; min-width: 0; height: auto; min-height: 48px; margin: 0; padding: 13px 12px; border: 1px solid var(--feedback-line); border-radius: 5px; background: #f8fafb; color: var(--feedback-ink); white-space: normal; transition: border-color .18s ease; }
.answer-options :deep(.el-radio:hover), .answer-options :deep(.el-checkbox:hover) { border-color: #8bb6bf; background: #f1f7f8; }
.answer-options :deep(.el-radio.is-checked), .answer-options :deep(.el-checkbox.is-checked) { border-color: #8bbfbe; background: #edf8f6; box-shadow: inset 3px 0 #167c7c; }
.answer-options :deep(.el-radio__input), .answer-options :deep(.el-checkbox__input) { margin-top: 3px; }
.answer-options :deep(.el-radio__label), .answer-options :deep(.el-checkbox__label) { min-width: 0; color: var(--feedback-ink); font-size: 14px; line-height: 1.6; overflow-wrap: anywhere; white-space: normal; }
.answer-options :deep(.is-checked .el-radio__label), .answer-options :deep(.is-checked .el-checkbox__label) { color: #164754; }
.question-card :deep(.el-textarea) { margin-top: 16px; }
.has-empty-evaluation { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; align-items: stretch; overflow: hidden; border: 1px solid var(--feedback-line); border-radius: 6px; background: #fff; box-shadow: 0 8px 32px rgb(17 40 60 / 3%); }
.has-empty-evaluation > .evaluation-panel, .has-empty-evaluation > .reflection-panel { border: 0; border-radius: 0; }
.has-empty-evaluation > :is(.evaluation-panel, .reflection-panel) > .section-heading { min-height: 114px; margin: 0; padding: 20px 24px 18px; }
.has-empty-evaluation :is(.evaluation-panel, .reflection-panel) .section-heading h2 { font-size: 22px; }
.has-empty-evaluation > .reflection-panel { position: static; display: flex; flex-direction: column; padding: 0; border-left: 1px solid var(--feedback-line); }
.is-empty-evaluation { display: flex; min-height: 0; flex-direction: column; }
.evaluation-preparation, .reflection-preparation { flex: 1; gap: 20px; padding: 28px 24px 24px; background: linear-gradient(150deg, #f1f8f7, #fff 65%); }
.reflection-preparation { background: linear-gradient(150deg, #f1f6fa, #fff 65%); }
.has-empty-evaluation :deep(.preparation-heading) { min-height: 116px; grid-template-columns: 44px minmax(0, 1fr); gap: 16px; }
.has-empty-evaluation :deep(.preparation-mark) { width: 44px; height: 44px; background: #e3f3f0; border-color: #afd2ce; }
.has-empty-evaluation :deep(.preparation-mark .el-icon) { font-size: 26px; }
.has-empty-evaluation :deep(.preparation-heading h3) { margin-top: 8px; font-size: 22px; line-height: 1.55; }
.has-empty-evaluation :deep(.preparation-heading p) { margin-top: 12px; font-size: 13px; line-height: 1.8; }
.has-empty-evaluation :deep(.preparation-steps) { flex: 1; }
.has-empty-evaluation :deep(.preparation-steps li) { min-height: 86px; padding: 16px 0; border-top: 0; }
.has-empty-evaluation :deep(.preparation-steps li::before) { position: absolute; top: 0; right: 0; left: 46px; height: 1px; background: #dce7e9; content: ''; }
.has-empty-evaluation :deep(.preparation-steps li::after) { top: 52px; bottom: -10px; }
.has-empty-evaluation :deep(.preparation-steps strong) { font-size: 15px; }
.has-empty-evaluation :deep(.preparation-steps p) { font-size: 13px; }
.has-empty-evaluation :deep(.preparation-footer) { position: relative; min-height: 54px; justify-content: flex-start; flex-wrap: nowrap; gap: 8px; padding-top: 16px; border-top: 0; color: var(--feedback-teal); }
.has-empty-evaluation :deep(.preparation-footer::before) { position: absolute; top: 0; right: 0; left: 46px; height: 1px; background: #dce7e9; content: ''; }
.has-empty-evaluation :deep(.preparation-footer .el-icon) { flex: 0 0 auto; font-size: 16px; }
.preparation-status { background: #f5f9fa; color: var(--feedback-teal); }
.reflection-panel { position: sticky; top: 16px; padding: 0 20px 20px; }
.reflection-panel .section-heading { padding: 20px 0 16px; }
.reflection-panel .section-heading h2 { font-size: 21px; }
.reflection-fields { display: grid; gap: 15px; padding-top: 18px; }
.reflection-fields label { display: grid; min-width: 0; gap: 7px; color: var(--feedback-ink); font-size: 13px; font-weight: 500; }
.reflection-fields label > span { display: flex; justify-content: space-between; align-items: baseline; gap: 6px; }
.reflection-fields small { color: var(--feedback-muted); font-size: 11px; font-weight: 400; }
.completion-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 12px; border: 1px solid #d5e6e4; border-radius: 4px; background: #f0f7f7; }
.completion-row strong, .completion-row span { display: block; }
.completion-row strong { font-size: 13px; font-weight: 600; }
.completion-row span { margin-top: 3px; color: var(--feedback-muted); font-size: 12px; line-height: 1.5; }
.completion-row :deep(.el-switch) { --el-switch-on-color: #167c7c; --el-switch-off-color: #849aa6; flex: 0 0 auto; height: 44px; }
.completion-row :deep(.el-switch__core) { min-width: 44px; }
.tutor-usage-row { display: flex; align-items: center; justify-content: space-between; padding-bottom: 12px; border-bottom: 1px solid var(--feedback-line); color: var(--feedback-muted); font-size: 13px; }
.tutor-usage-row strong { color: var(--feedback-teal); font: 13px/1.5 Consolas, 'Microsoft YaHei', monospace; }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.field-grid :deep(.el-input-number), .field-grid :deep(.el-select) { width: 100%; min-width: 0; }
.field-grid :deep(.el-input-number__increase), .field-grid :deep(.el-input-number__decrease) { border-color: var(--feedback-line); background: #f5f8fa; color: var(--feedback-muted); }
.rating-field { padding: 10px 12px; border: 1px solid var(--feedback-line); border-radius: 4px; background: #f8fafb; }
.rating-field :deep(.el-rate) { height: 44px; --el-rate-fill-color: #086575; --el-rate-void-color: #91a9b5; }
.rating-field :deep(.el-rate__item) { display: inline-grid; width: 44px; height: 44px; place-items: center; }
.rating-field :deep(.el-rate__icon) { margin: 0; font-size: 23px; }
.rating-field :deep(.el-rate__text) { margin-left: 4px; color: var(--feedback-teal); font: 13px/1.5 Consolas, monospace; }
.submit-box { display: grid; gap: 14px; margin-top: 20px; padding: 18px 0 0; border-top: 1px solid var(--feedback-line) !important; border-radius: 0; background: #fff !important; }
.submit-box strong, .submit-box span { display: block; }
.submit-box strong { color: var(--feedback-ink); font-size: 13px; font-weight: 600; }
.submit-box span { margin-top: 4px; color: var(--feedback-muted); font-size: 12px; line-height: 1.6; }
.feedback-generation-status { margin: 0; color: var(--feedback-teal); font-size: 13px; line-height: 1.6; }
.result-panel { display: grid; gap: 26px; padding: 26px; }
.result-header { display: grid; grid-template-columns: minmax(0, .8fr) minmax(0, 1.2fr); gap: 24px; align-items: start; }
.result-summary { min-width: 0; }
.result-summary h2 { margin: 7px 0 0; font-size: 26px; font-weight: 650; line-height: 1.4; }
.result-summary p { margin: 10px 0 0; color: var(--feedback-muted); font-size: 14px; line-height: 1.75; overflow-wrap: anywhere; }
.weak-points { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; margin-top: 14px; }
.weak-points span { color: var(--feedback-muted); font-size: 12px; }
.weak-points b { padding: 4px 8px; border: 1px solid #e6d7bc; border-radius: 4px; background: #fcf8ef; color: #875914; font-size: 12px; font-weight: 500; overflow-wrap: anywhere; }
.result-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; border: 1px solid var(--feedback-line); border-radius: 5px; background: #f8fafb; }
.result-metrics div { min-width: 0; padding: 15px 18px; }
.result-metrics div:nth-child(odd) { border-right: 1px solid var(--feedback-line); }
.result-metrics div:nth-child(-n+2) { border-bottom: 1px solid var(--feedback-line); }
.result-metrics span, .result-metrics strong { display: block; overflow-wrap: anywhere; }
.result-metrics span { color: var(--feedback-muted); font-size: 12px; }
.result-metrics strong { margin-top: 7px; font-size: 19px; font-weight: 650; line-height: 1.4; }
.result-metrics div:nth-child(2) strong { color: var(--feedback-teal); font: 600 28px/1.2 Consolas, monospace; }
.analysis-summary, .capability-result-panel { min-width: 0; padding-top: 22px; border-top: 1px solid var(--feedback-line); }
.analysis-heading { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px 14px; }
.analysis-heading strong { color: var(--feedback-ink); font-size: 18px; font-weight: 650; }
.analysis-heading span { color: var(--feedback-muted); font-size: 12px; line-height: 1.6; }
.analysis-summary > p { margin: 14px 0 0; color: var(--feedback-ink); font-size: 15px; line-height: 1.8; overflow-wrap: anywhere; }
.analysis-summary > .reflection-insight { padding: 12px 16px; border-left: 3px solid #65aeb0; background: #f0f7f7; color: #345c65; }
.analysis-summary ul { display: grid; gap: 7px; margin: 12px 0 0; padding-left: 20px; color: var(--feedback-muted); font-size: 14px; line-height: 1.7; }
.analysis-summary li::marker { color: var(--feedback-teal); }
.capability-result-list { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0; margin-top: 14px; border-top: 1px solid var(--feedback-line); border-left: 1px solid var(--feedback-line); }
.capability-result-list div { display: grid; min-width: 0; gap: 5px; padding: 13px 15px; border-right: 1px solid var(--feedback-line); border-bottom: 1px solid var(--feedback-line); }
.capability-result-list strong { color: var(--feedback-ink); font-size: 13px; font-weight: 600; overflow-wrap: anywhere; }
.capability-result-list span { color: var(--feedback-muted); font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.next-step-panel { display: grid; grid-template-columns: minmax(220px, .34fr) minmax(0, 1fr); align-items: start; gap: 24px; padding-top: 24px; border-top: 1px solid var(--feedback-line); }
.next-step-copy { min-width: 0; padding-right: 22px; border-right: 1px solid var(--feedback-line); }
.next-step-copy h4 { margin: 6px 0 0; font-size: 21px; font-weight: 650; line-height: 1.5; overflow-wrap: anywhere; }
.next-step-reason { margin-top: 18px; }
.next-step-reason b { color: var(--feedback-teal); font-size: 12px; font-weight: 600; }
.next-step-reason p { margin: 6px 0 0; color: var(--feedback-muted); font-size: 14px; line-height: 1.75; overflow-wrap: anywhere; }
.next-step-copy > small { display: block; margin-top: 16px; color: var(--feedback-muted); font-size: 12px; line-height: 1.6; }
.next-step-copy :deep(.el-alert) { margin-bottom: 16px; padding: 10px 12px; border: 1px solid #bfded7; border-radius: 4px; background: #edf8f6; color: var(--feedback-teal); }
.next-step-actions { display: grid; min-width: 0; gap: 16px; }
.followup-choice, .selected-followup-card { min-width: 0; padding: 20px; border: 1px solid var(--feedback-line); border-radius: 5px; background: #fff; }
.choice-kicker { display: block; color: var(--feedback-teal); font-size: 12px; font-weight: 500; line-height: 1.5; }
.correction-choice { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px 16px; border-left: 3px solid #6cb4af; }
.correction-choice > div:first-child { grid-column: 1 / -1; }
.correction-choice > div:first-child strong { display: block; margin-top: 5px; color: var(--feedback-ink); font-size: 18px; font-weight: 600; line-height: 1.5; }
.correction-choice p { margin: 8px 0 0; color: var(--feedback-muted); font-size: 13px; line-height: 1.75; overflow-wrap: anywhere; }
.fixed-correction-targets { display: flex; flex-wrap: wrap; align-items: center; gap: 7px; }
.correction-choice > small { grid-column: 1; color: var(--feedback-muted); font-size: 12px; line-height: 1.6; overflow-wrap: anywhere; }
.correction-choice > .el-button { grid-column: 2; grid-row: 2 / span 2; align-self: center; }
.correction-choice.is-disabled { border-left-color: #a9bac3; background: #f8fafb; }
.tier-learning-choice { display: grid; gap: 18px; }
.intent-selection-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; padding-bottom: 16px; border-bottom: 1px solid var(--feedback-line); }
.intent-selection-row > strong { flex: 1 1 auto; min-width: 0; color: var(--feedback-ink); font-size: 18px; font-weight: 600; overflow-wrap: anywhere; }
.intent-selection-row > small { flex: 0 1 100%; color: var(--feedback-muted); font-size: 12px; line-height: 1.6; }
.intent-mode-choice { display: flex; min-width: 0; flex-wrap: wrap; gap: 4px; }
.intent-mode-choice :deep(.el-radio-button__inner) { display: flex; min-height: 44px; align-items: center; justify-content: center; padding: 10px 12px; border: 1px solid var(--feedback-line); border-radius: 4px; background: #fff; color: var(--feedback-muted); font-size: 13px; box-shadow: none; }
.intent-mode-choice :deep(.el-radio-button.is-active .el-radio-button__inner) { border-color: #8bbfbe; background: #edf8f6; color: #164754; box-shadow: inset 0 -2px #167c7c; }
.intent-node-row { display: grid; min-width: 0; gap: 10px; }
.intent-node-row > span, .resource-selection-row > span { color: var(--feedback-ink); font-size: 13px; font-weight: 500; }
.intent-node-row em { color: var(--feedback-muted); font-size: 13px; font-style: normal; }
.resource-type-choice { display: flex; min-width: 0; flex-wrap: wrap; gap: 8px; }
.resource-type-choice :deep(.el-checkbox) { width: auto; min-width: 0; min-height: 44px; height: auto; margin: 0; padding: 10px 12px; border: 1px solid var(--feedback-line); border-radius: 4px; background: #f8fafb; color: var(--feedback-ink); }
.resource-type-choice :deep(.el-checkbox:hover) { border-color: #8bb6bf; }
.resource-type-choice :deep(.el-checkbox.is-checked) { border-color: #8bbfbe; background: #edf8f6; }
.resource-type-choice :deep(.el-checkbox.is-disabled) { border-color: #d9e4e9; background: #f3f5f7; color: #687b88; }
.resource-type-choice :deep(.el-checkbox__label) { min-width: 0; color: inherit; font-size: 13px; line-height: 1.6; white-space: normal; overflow-wrap: anywhere; }
.resource-type-choice :deep(.el-checkbox__label small) { color: var(--feedback-muted); font-size: 12px; }
.intent-node-row .resource-type-choice { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.preferred-learning-nodes { display: flex; flex-wrap: wrap; gap: 6px 8px; align-items: center; }
.preferred-learning-nodes b { color: var(--feedback-teal); font-size: 12px; }
.preferred-learning-nodes small { color: var(--feedback-muted); font-size: 12px; line-height: 1.6; }
.mixed-intent-row { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.mixed-intent-row > span { grid-column: 1 / -1; }
.mixed-node-choice { display: grid; min-width: 0; gap: 8px; }
.mixed-node-choice b { color: var(--feedback-muted); font-size: 12px; font-weight: 500; }
.mixed-node-choice .resource-type-choice { grid-template-columns: 1fr; }
.resource-selection-row { display: flex; min-width: 0; flex-wrap: wrap; align-items: center; gap: 10px 12px; padding-top: 16px; border-top: 1px solid var(--feedback-line); }
.resource-selection-row > span, .resource-selection-row > .resource-type-choice { flex: 0 1 100%; }
.claim-check-choice { min-height: 44px; height: auto; margin: 0; }
.claim-check-choice :deep(.el-checkbox__label) { color: var(--feedback-muted); font-size: 13px; white-space: normal; }
.difficulty-choice { width: 130px; }
.locked-difficulty { width: auto; }
.custom-generation-button { margin-left: auto !important; }
.selected-followup-card { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px; border-left: 3px solid #6cb4af; background: #f5faf9; }
.selected-followup-heading { grid-column: 1 / -1; }
.selected-followup-heading > strong { display: block; margin-top: 5px; font-size: 20px; font-weight: 600; }
.selected-followup-heading p { margin: 8px 0 0; color: var(--feedback-muted); font-size: 13px; line-height: 1.6; }
.selected-followup-targets { display: flex; flex-wrap: wrap; gap: 7px; align-items: center; min-width: 0; }
.selected-followup-targets b { flex: 0 0 100%; color: var(--feedback-muted); font-size: 12px; font-weight: 500; }
.selected-followup-targets > span { color: var(--feedback-muted); font-size: 13px; }
.selected-followup-meta { grid-column: 1; color: var(--feedback-teal); font-size: 13px; line-height: 1.6; }
.selected-followup-meta small { display: block; margin-top: 4px; color: var(--feedback-muted); font-size: 12px; }
.selected-followup-card > .el-button { grid-column: 2; grid-row: 2 / span 2; align-self: center; }
.result-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px; padding-top: 20px; border-top: 1px solid var(--feedback-line); }
.followup-count { margin-right: auto; color: var(--feedback-muted); font-size: 13px; }
/* Inputs use the component's outer focus border; outline only buttons and option labels. */
.feedback-page :deep(:is(button, .el-radio, .el-checkbox):focus-visible), .feedback-page :deep(.el-radio:has(input:focus-visible)), .feedback-page :deep(.el-checkbox:has(input:focus-visible)), .feedback-page :deep(.el-radio-button:has(input:focus-visible)) { outline: 3px solid #16758a; outline-offset: 3px; }
@media (max-width: 1180px) {
  .result-header { grid-template-columns: minmax(0, 1fr); }
  .result-metrics { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .result-metrics div:not(:last-child) { border-right: 1px solid var(--feedback-line); }
  .result-metrics div:nth-child(-n+2) { border-bottom: 0; }
  .result-metrics div:nth-child(3) { border-right: 1px solid var(--feedback-line); }
  .next-step-panel { grid-template-columns: minmax(0, 1fr); }
  .next-step-copy { padding: 0 0 20px; border-right: 0; border-bottom: 1px solid var(--feedback-line); }
}
@media (max-width: 960px) {
  .feedback-workspace { grid-template-columns: minmax(0, 1fr); }
  .has-empty-evaluation > .reflection-panel { border-left: 0; border-top: 1px solid var(--feedback-line); }
  .has-empty-evaluation .section-heading { min-height: 0; }
  .reflection-panel { position: static; }
  .reflection-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .reflection-fields > .completion-row, .reflection-fields > .tutor-usage-row, .reflection-fields > .field-grid, .reflection-fields > label:last-child { grid-column: 1 / -1; }
}
@media (max-width: 760px) {
  .feedback-page { padding-top: 16px; }
  .task-selection { grid-template-columns: minmax(0, 1fr); }
  .feedback-hero { padding: 14px; }
  .task-selection .start-evaluation-button { width: 100%; }
  .section-heading { padding: 18px; align-items: flex-start; flex-wrap: wrap; gap: 10px; }
  .section-heading h2 { font-size: 21px; }
  .section-heading p { font-size: 13px; }
  .question-list { padding: 0 18px; }
  .answer-options { grid-template-columns: 1fr; }
  .question-tools { gap: 6px; }
  .question-tools :deep(.el-tag) { max-width: 150px; }
  .reflection-panel { padding: 0 18px 18px; }
  .reflection-fields { grid-template-columns: minmax(0, 1fr); }
  .reflection-fields > * { grid-column: 1 !important; }
  .feedback-page :deep(.el-input__inner), .feedback-page :deep(.el-select__selected-item), .feedback-page :deep(.el-textarea__inner) { font-size: 16px; }
  .result-panel { gap: 22px; padding: 20px 18px; }
  .result-summary h2 { font-size: 24px; }
  .result-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .result-metrics div { padding: 13px; }
  .result-metrics div:nth-child(-n+2) { border-bottom: 1px solid var(--feedback-line); }
  .result-metrics div:nth-child(even) { border-right: 0; }
  .capability-result-list { grid-template-columns: minmax(0, 1fr); }
  .followup-choice, .selected-followup-card { padding: 16px; }
  .correction-choice, .selected-followup-card, .mixed-intent-row { grid-template-columns: minmax(0, 1fr); }
  .correction-choice > *, .selected-followup-card > * { grid-column: 1 !important; grid-row: auto !important; }
  .correction-choice > .el-button, .selected-followup-card > .el-button, .custom-generation-button { width: 100%; }
  .intent-node-row .resource-type-choice { grid-template-columns: minmax(0, 1fr); }
  .intent-mode-choice { width: 100%; }
  .intent-mode-choice :deep(.el-radio-button) { flex: 1 1 auto; }
  .intent-mode-choice :deep(.el-radio-button__inner) { padding-inline: 8px; font-size: 12px; }
  .result-actions { justify-content: stretch; }
  .result-actions :deep(.el-button) { flex: 1 1 auto; }
}
@media (max-width: 600px) {
  :global(.app-shell.is-feedback .sidebar .sidebar-inner) { grid-template-columns: minmax(0, 1fr) 44px 44px; grid-template-rows: auto; gap: 4px; padding: 7px 8px; }
  :global(.app-shell.is-feedback .sidebar .brand-block), :global(.app-shell.is-feedback .sidebar .nav-text) { display: none; }
  :global(.app-shell.is-feedback .sidebar .nav-list) { grid-template-columns: repeat(5, minmax(0, 1fr)); grid-template-rows: auto; gap: 2px; }
  :global(.app-shell.is-feedback .sidebar .nav-item) { width: auto; min-width: 0; min-height: 44px; padding: 6px 4px; }
  :global(.app-shell.is-feedback .sidebar .sidebar-toggle), :global(.app-shell.is-feedback .sidebar .logout-button) { width: 44px; min-width: 44px; }
}
@media (max-height: 760px) { .reflection-panel { position: static; } }
@media (prefers-reduced-motion: reduce) { .feedback-page *, .feedback-page :deep(*) { transition: none !important; animation: none !important; scroll-behavior: auto !important; } }
</style>
