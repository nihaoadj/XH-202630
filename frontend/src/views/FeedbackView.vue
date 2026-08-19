<template>
  <div class="feedback-page">
    <section class="feedback-hero">
      <div class="hero-copy">
        <span class="page-kicker">PRACTICE REFLECTION</span>
        <h2>练习反馈</h2>
        <p>完成本轮资源练习后，用测评和真实感受更新学习画像，让下一轮内容更贴近你的掌握情况。</p>
      </div>

      <div class="hero-focus">
        <span class="focus-state"><i />当前学习方向</span>
        <strong>{{ currentDirectionName }}</strong>
        <div class="focus-divider" />
        <div class="focus-details">
          <span>待反馈任务 <b>{{ taskGroups.length }}</b></span>
        </div>
      </div>

      <div class="task-selection task-selection-inline">
        <span class="task-selection-label">本轮资源批次</span>
        <el-select v-model="selectedRunId" filterable placeholder="选择要反馈的学习资源批次" class="task-select">
          <el-option v-for="task in taskGroups" :key="task.runId" :label="task.label" :value="task.runId" />
        </el-select>
        <el-button class="start-evaluation-button" type="primary" :icon="VideoPlay" @click="startEvaluation" :disabled="!selectedRunId">开始测评</el-button>
      </div>

      <div v-if="activeTask" class="task-stats hero-task-stats">
        <div><span>学习方向</span><strong>{{ currentDirectionName }}</strong></div>
        <div><span>本轮资源</span><strong>{{ activeTask.resources.length }} 份</strong></div>
        <div><span>测评题目</span><strong>{{ evaluation.questions.length }} 题</strong></div>
        <div><span>完成进度</span><strong>{{ answeredCount }} / {{ evaluation.questions.length || 0 }}</strong></div>
      </div>
      <p v-else class="task-empty-tip">暂时没有可用于反馈的资源任务，请先完成一轮学习资源生成。</p>
    </section>

    <section ref="workspaceRef" class="feedback-workspace">
      <article class="evaluation-panel">
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
      <div class="result-summary">
        <span class="page-kicker">LEARNING RESULT</span>
        <h3>本轮反馈已记录</h3>
        <p>{{ result.decision.decision_reason }}</p>
        <div v-if="weakKnowledgePoints.length" class="weak-points"><span>优先巩固</span><b v-for="item in weakKnowledgePoints" :key="item">{{ item }}</b></div>
      </div>
      <div class="result-metrics">
        <div><span>测评正确率</span><strong>{{ Math.round(result.attempt.overall_score * 100) }}%</strong></div>
        <div><span>答对题数</span><strong>{{ attemptCorrectSummary }}</strong></div>
        <div><span>系统建议</span><strong>{{ feedbackActionLabel(result.decision.action) }}</strong></div>
        <div><span>下一轮状态</span><strong>{{ followupStatusLabel(result.followup_generation_status) }}</strong></div>
      </div>
      <div class="result-actions"><el-button plain @click="router.push('/report')">查看学习报告</el-button><el-button type="primary" plain :disabled="!result.followup_run_id" @click="goToFollowupRun">查看下一轮资源</el-button></div>
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
import { feedbackApi, generateApi, resourceApi } from '../api'
import { useAppStore } from '../stores/app'
import { formatDateTime } from '../utils/generationDisplay'
import TutorDrawer from '../components/TutorDrawer.vue'
import { countTutorTurns } from '../utils/tutorState'

const router = useRouter()
const store = useAppStore()
const workspaceRef = ref(null)
const form = reactive({ learner_id: store.currentLearnerId || localStorage.getItem('last_learner_id') || '', completed: true, time_spent_seconds: 1800, self_rating: 4, difficulty_feeling: '', helpful_part: '', confusing_part: '', comment: '' })
const resources = ref([])
const generationJobs = ref([])
const selectedRunId = ref(localStorage.getItem('current_generation_run_id') || '')
const submitting = ref(false)
const result = ref(null)
const evaluation = reactive({ topic: '', questions: [], resourceIds: [] })
const evaluationAnswers = reactive({})
const tutorOpen = ref(false)
const tutorQuestion = ref(null)
const tutorHelpCount = ref(0)

const currentDirectionName = computed(() => store.currentLearningDirectionName || localStorage.getItem('learning_direction_name') || '未选择学习方向')
const taskGroups = computed(() => {
  const groups = new Map()
  for (const resource of resources.value) {
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
      return { ...task, batchLabel, label: `${batchLabel} / ${task.resources.length} 份资源 / ${formatTaskTime(task.finishedAt)}` }
    })
})
const activeTask = computed(() => taskGroups.value.find((item) => item.runId === selectedRunId.value) || taskGroups.value[0] || null)
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

watch(() => store.currentLearnerId, (value) => { if (value) form.learner_id = value })

function hasAnswer(value) { return Array.isArray(value) ? value.length > 0 : String(value || '').trim().length > 0 }
function resetEvaluationAnswers() { Object.keys(evaluationAnswers).forEach((key) => delete evaluationAnswers[key]) }
function formatTaskTime(value) { return formatDateTime(value) }
function feedbackActionLabel(action) { return { remediate: '补救学习', practice: '强化练习', advance: '继续进阶', hold: '保持路径', human_review: '人工复核' }[action] || action || '已记录' }
function followupStatusLabel(status) { return { not_requested: '未触发', queued: '已排队', failed: '触发失败' }[status] || status || '待更新' }
function buildIdempotencyKey(runId, submittedAt) { return `web-${runId.slice(0, 24)}-${submittedAt.toISOString().replace(/[^0-9]/g, '')}`.slice(0, 128) }
function scrollToWorkspace() { workspaceRef.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
async function startEvaluation() { await loadEvaluationSession(); scrollToWorkspace() }
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
  const storedResource = resources.value.find((item) => item.run_id === storedId)
  const storedBatchId = storedResource?.batch_id || storedResource?.run_id || storedId
  selectedRunId.value = taskGroups.value.some((item) => item.runId === storedBatchId) ? storedBatchId : taskGroups.value[0].runId
}
async function loadResources() {
  if (!form.learner_id) return
  try {
    const [res, jobsRes] = await Promise.all([
      resourceApi.listByLearner(form.learner_id),
      generateApi.listJobs(form.learner_id),
    ])
    resources.value = res.data.resources || []
    generationJobs.value = jobsRes.data.items || []
    syncSelectedRun()
  }
  catch (error) { console.error(error); ElMessage.warning('资源加载失败，请先完成资源生成。') }
}
async function loadEvaluationSession() {
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
    if (store.currentProfile) store.setCurrentProfile({ ...store.currentProfile, profile_version: res.data.profile_version })
    ElMessage.success('本轮练习反馈已提交')
  } catch (error) { console.error(error); ElMessage.error(error?.response?.data?.message || '提交失败，请稍后再试') }
  finally { submitting.value = false }
}
function goToFollowupRun() {
  if (!result.value?.followup_run_id) return
  localStorage.setItem('current_generation_run_id', result.value.followup_run_id)
  router.push({ path: '/generate', query: { runId: result.value.followup_run_id, learnerId: form.learner_id } })
}
onMounted(async () => { await loadResources(); if (selectedRunId.value && !selectedRunId.value.startsWith('resource:')) await loadEvaluationSession() })
</script>

<style scoped>
.feedback-page { --ink:#10233f; --muted:#617691; --line:#dce6f1; display:flex; flex-direction:column; gap:16px; color:var(--ink); }
.feedback-hero,.task-panel,.evaluation-panel,.reflection-panel,.result-panel,.history-panel { border:1px solid var(--line); border-radius:18px; background:rgba(255,255,255,.96); box-shadow:0 12px 28px rgba(24,60,96,.055); }
.feedback-hero { position:relative; display:grid; grid-template-columns:minmax(0,1fr) minmax(290px,.55fr); gap:28px; align-items:center; min-height:164px; padding:25px 28px; overflow:hidden; background:radial-gradient(circle at 87% 15%,rgba(50,206,176,.2),transparent 29%),linear-gradient(118deg,#eff6ff,#fbfdff 58%,#eefaf7); }
.feedback-hero::after { position:absolute; right:24%; bottom:-80px; width:210px; height:150px; border:1px solid rgba(71,170,148,.16); border-radius:50%; content:''; }.hero-copy,.hero-focus { position:relative; z-index:1; }.page-kicker { display:block; color:#176f61; font-size:12px; font-weight:800; letter-spacing:.09em; line-height:1; }.hero-copy h2 { margin:8px 0 0; font-size:clamp(30px,2.4vw,40px); font-weight:800; letter-spacing:-.045em; line-height:1.08; }.hero-copy p { max-width:720px; margin:10px 0 0; color:#536d8d; font-size:15px; line-height:1.6; }.hero-actions { display:flex; gap:10px; margin-top:15px; }.hero-actions :deep(.el-button) { height:36px; font-weight:700; }
.hero-focus { padding:18px 20px; border:1px solid rgba(255,255,255,.86); border-radius:14px; background:rgba(255,255,255,.76); backdrop-filter:blur(8px); }.focus-state { display:flex; align-items:center; gap:8px; color:#607891; font-size:12px; }.focus-state i { width:8px; height:8px; border-radius:50%; background:#19af8c; box-shadow:0 0 0 5px rgba(25,175,140,.12); }.hero-focus strong { display:block; margin-top:11px; overflow:hidden; font-size:21px; text-overflow:ellipsis; white-space:nowrap; }.focus-divider { height:1px; margin:14px 0 10px; background:#d9e6ee; }.focus-details { display:grid; grid-template-columns:1fr 1fr; gap:14px; }.focus-details span { color:#6b829a; font-size:12px; }.focus-details b { display:block; margin-top:4px; color:#203b5b; font-size:16px; }
.task-panel,.evaluation-panel,.reflection-panel,.history-panel { padding:20px; }.section-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; }.section-heading h3 { margin:7px 0 0; color:var(--ink); font-size:23px; font-weight:800; letter-spacing:-.035em; line-height:1.1; }.section-heading p { margin:7px 0 0; color:#627691; font-size:13px; line-height:1.5; }.section-heading :deep(.el-button) { font-weight:700; }.task-selection { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; max-width:830px; margin-top:18px; }.task-select { width:100%; }.task-selection :deep(.el-button) { height:34px; font-weight:700; }.task-stats { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin-top:15px; }.task-stats div { min-width:0; padding:12px 14px; border:1px solid #dce7f2; border-radius:11px; background:#fbfdff; }.task-stats div:nth-child(2n) { border-color:#cce9df; background:#f3fbf8; }.task-stats span,.task-stats strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.task-stats span { color:#71859d; font-size:12px; }.task-stats strong { margin-top:6px; color:#1d3958; font-size:17px; }
.feedback-workspace { display:grid; grid-template-columns:minmax(0,1.42fr) minmax(330px,.58fr); gap:16px; align-items:start; }.progress-pill { padding:7px 10px; border-radius:999px; background:#f1f5f9; color:#667b93; font-size:12px; font-weight:700; white-space:nowrap; }.progress-pill.ready { background:#eaf8f1; color:#168468; }.question-list { display:grid; gap:12px; margin-top:19px; }.question-card { padding:16px; border:1px solid #e0e8f1; border-radius:13px; background:#fbfdff; }.question-topline { display:flex; align-items:center; justify-content:space-between; gap:12px; }.question-index { color:#2e73cb; font-size:12px; font-weight:800; letter-spacing:.06em; }.question-tools { display:flex; align-items:center; gap:6px; }.question-tools :deep(.el-button) { padding:3px 5px; font-weight:750; }.question-card > strong { display:block; margin-top:10px; color:#1b3554; font-size:16px; line-height:1.6; }.answer-options { display:flex; flex-direction:column; gap:8px; margin-top:13px; }.answer-options :deep(.el-radio),.answer-options :deep(.el-checkbox) { height:auto; min-height:25px; margin-right:0; white-space:normal; }.question-card :deep(.el-textarea) { margin-top:13px; }.tutor-usage-row { display:flex; align-items:center; justify-content:space-between; padding:10px 12px; border-radius:10px; background:#eef7ff; color:#58718c; font-size:12px; }.tutor-usage-row strong { color:#2868ae; font-size:13px; }
.reflection-panel { position:sticky; top:0; }.compact-heading { padding-bottom:15px; border-bottom:1px solid #e5edf5; }.reflection-fields { display:grid; gap:13px; margin-top:16px; }.reflection-fields label { display:grid; gap:7px; color:#3d5874; font-size:13px; font-weight:700; }.reflection-fields label > span { color:#526b86; }.completion-row { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:13px; border:1px solid #d9e9e3; border-radius:11px; background:#f5fcf8; }.completion-row strong,.completion-row span { display:block; }.completion-row strong { color:#1f5f50; font-size:14px; }.completion-row span { margin-top:3px; color:#668377; font-size:11px; }.field-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }.field-grid :deep(.el-input-number),.field-grid :deep(.el-select) { width:100%; }.reflection-fields small { color:#8391a4; font-size:11px; font-weight:500; }.rating-field { padding:12px; border-radius:10px; background:#f7faff; }.submit-box { display:flex; align-items:center; justify-content:space-between; gap:13px; margin-top:17px; padding:14px; border-radius:12px; background:linear-gradient(135deg,#eef6ff,#f0fbf7); }.submit-box strong,.submit-box span { display:block; }.submit-box strong { color:#1b3857; font-size:14px; }.submit-box span { max-width:210px; margin-top:4px; color:#678099; font-size:11px; line-height:1.45; }.submit-box :deep(.el-button) { flex:0 0 auto; height:36px; font-weight:700; }
.result-panel { display:grid; grid-template-columns:minmax(260px,.7fr) minmax(0,1.3fr); gap:16px; padding:20px; background:linear-gradient(112deg,#fbfefd,#effaf6); }.result-summary h3 { margin:7px 0 0; font-size:23px; letter-spacing:-.035em; }.result-summary p { margin:10px 0 0; color:#567089; font-size:14px; line-height:1.55; }.weak-points { display:flex; flex-wrap:wrap; gap:7px; margin-top:13px; }.weak-points span,.weak-points b { padding:6px 8px; border-radius:999px; font-size:11px; }.weak-points span { background:#e8f6ef; color:#247a64; }.weak-points b { background:#fff; color:#b26327; }.result-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; align-content:start; }.result-metrics div { min-width:0; padding:13px; border:1px solid #d8e9e3; border-radius:11px; background:rgba(255,255,255,.78); }.result-metrics span,.result-metrics strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.result-metrics span { color:#70859c; font-size:12px; }.result-metrics strong { margin-top:7px; color:#183856; font-size:18px; }.result-actions { grid-column:2; display:flex; justify-content:flex-end; gap:10px; }.result-actions :deep(.el-button) { font-weight:700; }
.history-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin-top:17px; }.history-item { display:grid; grid-template-columns:auto minmax(0,1fr) auto; align-items:center; gap:11px; min-width:0; padding:12px; border:1px solid #e0e8f1; border-radius:11px; background:#fbfdff; color:inherit; text-align:left; cursor:pointer; transition:border-color .2s ease,box-shadow .2s ease,transform .2s ease; }.history-item:hover,.history-item.selected { border-color:#91b9ee; box-shadow:0 6px 14px rgba(31,78,130,.08); transform:translateY(-1px); }.history-score { display:grid; width:45px; height:36px; place-items:center; border-radius:9px; background:#eaf2ff; color:#286bd0; font-size:13px; font-weight:800; }.history-copy { min-width:0; }.history-copy strong,.history-copy small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }.history-copy strong { color:#203b59; font-size:13px; }.history-copy small { margin-top:4px; color:#74869c; font-size:11px; }.history-decision { color:#258069; font-size:12px; font-weight:700; white-space:nowrap; }.history-selection-tip { margin:13px 0 0; color:#667b93; font-size:12px; }
@media (max-width:1180px) { .feedback-workspace,.result-panel { grid-template-columns:1fr; }.reflection-panel { position:static; }.result-actions { grid-column:auto; }.result-metrics { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:820px) { .feedback-hero { grid-template-columns:1fr; }.task-stats { grid-template-columns:repeat(2,minmax(0,1fr)); }.history-list { grid-template-columns:1fr; } }
@media (max-width:560px) { .feedback-hero,.task-panel,.evaluation-panel,.reflection-panel,.history-panel,.result-panel { padding:18px; }.hero-copy h2 { font-size:30px; }.hero-actions { flex-direction:column; }.hero-actions :deep(.el-button),.task-selection :deep(.el-button) { width:100%; }.task-selection,.field-grid,.result-metrics { grid-template-columns:1fr; }.submit-box { align-items:stretch; flex-direction:column; }.submit-box :deep(.el-button) { width:100%; }.history-item { grid-template-columns:auto minmax(0,1fr); }.history-decision { grid-column:2; }.section-heading { flex-direction:column; } }

/* Keep selection context available without competing with the practice workspace. */
.feedback-page { gap: 12px; }
.feedback-hero { grid-template-columns: minmax(0, 1fr) minmax(250px, .36fr); min-height: 168px; gap: 12px 20px; padding: 16px 22px; border-radius: 10px; }
.feedback-hero::after { right: 12%; bottom: -98px; width: 170px; height: 132px; }
.hero-copy h2 { margin-top: 5px; font-size: 27px; letter-spacing: 0; }
.hero-copy p { display: none; }
.hero-actions { margin-top: 10px; }
.hero-actions :deep(.el-button) { height: 30px; padding: 0 12px; }
.hero-focus { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 4px 14px; padding: 11px 14px; border-radius: 10px; }
.focus-state { grid-column: 1 / -1; font-size: 11px; }
.hero-focus strong { min-width: 0; margin: 0; font-size: 15px; }
.focus-divider { display: none; }
.focus-details { display: flex; gap: 12px; }
.focus-details span { white-space: nowrap; font-size: 11px; }
.focus-details b { display: inline; margin: 0 0 0 4px; font-size: 13px; }
.task-panel { padding: 13px 18px; border-radius: 10px; }
.task-panel .section-heading h3 { margin: 4px 0 0; font-size: 18px; }
.task-panel .page-kicker { font-size: 10px; }
.task-selection { max-width: none; margin-top: 10px; }
.task-selection-inline { grid-column: 1 / -1; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; margin-top: 2px; }
.task-selection-label { color: #47637e; font-size: 12px; font-weight: 800; white-space: nowrap; }
.task-selection :deep(.el-select__wrapper) { min-height: 34px; }
.hero-task-stats { grid-column: 1 / -1; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin-top: 0; }
.task-stats div { padding: 8px 11px; border-radius: 8px; }
.task-stats strong { margin-top: 3px; font-size: 14px; }
.task-stats span { font-size: 11px; }
.task-empty-tip { grid-column: 1 / -1; margin: 0; color: #6e8198; font-size: 12px; }
.feedback-workspace { grid-template-columns: minmax(0, 1.55fr) minmax(360px, .65fr); gap: 12px; align-items: start; }
.evaluation-panel, .reflection-panel { padding: 16px; border-radius: 10px; }
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
  .feedback-hero { grid-template-columns: minmax(0, 1fr) minmax(230px, .42fr); }
  .feedback-workspace { grid-template-columns: minmax(0, 1.45fr) minmax(285px, .55fr); }
}

@media (max-width: 820px) {
  .feedback-hero { grid-template-columns: 1fr; }
  .hero-focus { display: none; }
  .task-selection-inline { grid-template-columns: auto minmax(0, 1fr) auto; }
  .feedback-workspace { grid-template-columns: 1fr; }
  .reflection-panel { position: static; }
  .question-card { grid-template-columns: 34px minmax(0, 1fr) auto; gap: 9px; }
}

@media (max-width: 560px) {
  .feedback-hero { min-height: 0; }
  .task-selection-inline { grid-template-columns: 1fr auto; }
  .task-selection-label { grid-column: 1 / -1; }
  .task-selection-inline :deep(.el-button) { width: auto; }
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
  border-top: 3px solid #2d796b;
  background: #ffffff;
  box-shadow: 0 14px 32px rgb(25 65 74 / 9%);
}
.reflection-panel .compact-heading {
  display: flex;
  align-items: flex-end;
  min-height: 48px;
  padding-bottom: 12px;
  border-color: #dce9e5;
}
.reflection-panel .page-kicker { color: #247063; letter-spacing: .12em; }
.reflection-panel .section-heading h3 { color: #18354d; }
.completion-row {
  padding: 13px 14px;
  border-color: #c9e3da;
  border-radius: 9px;
  background: #f3faf7;
}
.completion-row strong { color: #205f53; letter-spacing: .01em; }
.completion-row :deep(.el-switch) { --el-switch-on-color: #28796a; --el-switch-off-color: #b9c8d3; }
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
  border-color: #398b7d;
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
  border: 1px solid #d1e8df;
  border-radius: 10px;
  background: #f4faf8;
}
.submit-box strong { color: #1c4c49; letter-spacing: .01em; }
.start-evaluation-button,
.submit-feedback-button {
  border-color: #236e62 !important;
  color: #fff !important;
  background: #236e62 !important;
  box-shadow: 0 7px 14px rgb(35 110 98 / 20%);
  font-weight: 750 !important;
}
.start-evaluation-button { min-width: 106px; }
.submit-feedback-button { min-width: 118px; }
.start-evaluation-button:hover,
.start-evaluation-button:focus-visible,
.submit-feedback-button:hover,
.submit-feedback-button:focus-visible {
  border-color: #194f48 !important;
  background: #194f48 !important;
  box-shadow: 0 8px 18px rgb(25 79 72 / 26%);
}
.start-evaluation-button.is-disabled,
.submit-feedback-button.is-disabled {
  border-color: #d7e3e6 !important;
  color: #8ca1ae !important;
  background: #e8f0f2 !important;
  box-shadow: none;
}
</style>
